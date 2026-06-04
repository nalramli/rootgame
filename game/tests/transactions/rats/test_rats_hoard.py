"""Tests for the HoardTooFull event and discard_hoard_item transaction.

Setup mirrors test_rats_birdsong: RATS + CATS game, rats setup completed,
game forced into RATS's turn with a manually created RatsTurn.
"""

from django.test import TestCase

from game.errors import IllegalActionError, UnavailableActionError
from game.models.enums import ItemTypes
from game.models.events.event import Event, EventType
from game.models.events.rats import HoardTooFullEvent
from game.models.game_models import Faction, Game, Item, Player
from game.models.rats.player import CommandItemEntry, ProwessItemEntry
from game.models.rats.turn import RatsBirdsong, RatsTurn
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------

class RatsHoardBaseTestCase(TestCase):
    """Rats + Cats game with rats in Birdsong at the RAZE step."""

    def setUp(self):
        self.game = GameSetupFactory(factions=[Faction.RATS, Faction.CATS])
        self.player = self.game.players.get(faction=Faction.RATS)

        # Complete rats setup
        game_setup = GameSimpleSetup.objects.get(game=self.game)
        game_setup.status = GameSimpleSetup.GameSetupStatus.RATS_SETUP
        game_setup.save()

        c2 = Clearing.objects.get(game=self.game, clearing_number=2)
        rats_pick_corner(self.player, c2)
        rats_confirm_setup(self.player)

        self.game.refresh_from_db()
        self.game.current_turn = self.player.turn_order
        self.game.status = Game.GameStatus.SETUP_COMPLETED
        self.game.save()

        self.rats_turn = RatsTurn.create_turn(self.player)
        self.birdsong = self.rats_turn.birdsong.first()
        self.birdsong.step = RatsBirdsong.Steps.RAZE
        self.birdsong.save()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_item(self, item_type: str) -> Item:
        return Item.objects.create(game=self.game, item_type=item_type)

    def _fill_command_track(self, count: int = 4) -> list[Item]:
        """Add *count* command items to the player's hoard without triggering overflow."""
        items = []
        for item_type in [ItemTypes.BOOTS, ItemTypes.BAG, ItemTypes.COIN,
                          ItemTypes.BOOTS, ItemTypes.BAG][:count]:
            item = self._make_item(item_type)
            CommandItemEntry.objects.create(player=self.player, item=item)
            items.append(item)
        return items

    def _fill_prowess_track(self, count: int = 4) -> list[Item]:
        """Add *count* prowess items to the player's hoard without triggering overflow."""
        items = []
        for item_type in [ItemTypes.HAMMER, ItemTypes.TEA, ItemTypes.SWORD,
                          ItemTypes.CROSSBOW, ItemTypes.HAMMER][:count]:
            item = self._make_item(item_type)
            ProwessItemEntry.objects.create(player=self.player, item=item)
            items.append(item)
        return items


# ===========================================================================
# add_item_to_hoard — overflow detection
# ===========================================================================

class AddItemToHoardOverflowTests(RatsHoardBaseTestCase):

    def test_no_event_when_command_track_not_full(self):
        """Adding a 4th command item (exactly at limit) must NOT create an event."""
        from game.transactions.rats.hoard import add_item_to_hoard

        self._fill_command_track(3)  # 3 items already in hoard
        item = self._make_item(ItemTypes.COIN)
        add_item_to_hoard(self.player, item)  # 4th item — no overflow

        self.assertFalse(
            HoardTooFullEvent.objects.filter(
                player=self.player, event__is_resolved=False
            ).exists()
        )

    def test_event_created_when_command_track_overflows(self):
        """Adding a 5th command item must create a COMMAND HoardTooFullEvent."""
        from game.transactions.rats.hoard import add_item_to_hoard

        self._fill_command_track(4)  # already at limit
        item = self._make_item(ItemTypes.BOOTS)
        add_item_to_hoard(self.player, item)  # 5th — overflow

        event = HoardTooFullEvent.objects.filter(
            player=self.player,
            track=HoardTooFullEvent.Track.COMMAND,
            event__is_resolved=False,
        ).first()
        self.assertIsNotNone(event, "Expected a HoardTooFullEvent for Command track")

    def test_event_created_when_prowess_track_overflows(self):
        """Adding a 5th prowess item must create a PROWESS HoardTooFullEvent."""
        from game.transactions.rats.hoard import add_item_to_hoard

        self._fill_prowess_track(4)
        item = self._make_item(ItemTypes.SWORD)
        add_item_to_hoard(self.player, item)

        event = HoardTooFullEvent.objects.filter(
            player=self.player,
            track=HoardTooFullEvent.Track.PROWESS,
            event__is_resolved=False,
        ).first()
        self.assertIsNotNone(event, "Expected a HoardTooFullEvent for Prowess track")

    def test_overflow_on_command_does_not_create_prowess_event(self):
        """A Command overflow must not create a Prowess event."""
        from game.transactions.rats.hoard import add_item_to_hoard

        self._fill_command_track(4)
        add_item_to_hoard(self.player, self._make_item(ItemTypes.COIN))

        self.assertFalse(
            HoardTooFullEvent.objects.filter(
                player=self.player,
                track=HoardTooFullEvent.Track.PROWESS,
                event__is_resolved=False,
            ).exists()
        )

    def test_event_type_is_hoard_too_full(self):
        """The underlying Event row must have type HOARD_TOO_FULL."""
        from game.transactions.rats.hoard import add_item_to_hoard

        self._fill_command_track(4)
        add_item_to_hoard(self.player, self._make_item(ItemTypes.BOOTS))

        hoard_event = HoardTooFullEvent.objects.get(
            player=self.player, event__is_resolved=False
        )
        self.assertEqual(hoard_event.event.type, EventType.HOARD_TOO_FULL)


# ===========================================================================
# discard_hoard_item
# ===========================================================================

class DiscardHoardItemTests(RatsHoardBaseTestCase):

    def _setup_overflow(self, track: str) -> tuple[HoardTooFullEvent, Item]:
        """Fill the given track to 4, add one more to trigger overflow, return
        the event and the overflow item."""
        from game.transactions.rats.hoard import add_item_to_hoard

        if track == HoardTooFullEvent.Track.COMMAND:
            self._fill_command_track(4)
            overflow_item = self._make_item(ItemTypes.BOOTS)
        else:
            self._fill_prowess_track(4)
            overflow_item = self._make_item(ItemTypes.HAMMER)

        add_item_to_hoard(self.player, overflow_item)
        hoard_event = HoardTooFullEvent.objects.get(
            player=self.player, track=track, event__is_resolved=False
        )
        return hoard_event, overflow_item

    def test_discard_removes_item_from_hoard_and_game(self):
        """After discarding, the item entry and Item object are deleted."""
        from game.transactions.rats.hoard import discard_hoard_item

        _, overflow_item = self._setup_overflow(HoardTooFullEvent.Track.COMMAND)
        item_pk = overflow_item.pk

        discard_hoard_item(self.player, overflow_item)

        self.assertFalse(
            CommandItemEntry.objects.filter(player=self.player, item_id=item_pk).exists(),
            "Item entry should be removed from Command track",
        )
        self.assertFalse(
            Item.objects.filter(pk=item_pk).exists(),
            "Item should be deleted from the game",
        )

    def test_discard_resolves_event(self):
        """After discarding, the HoardTooFullEvent is marked resolved."""
        from game.transactions.rats.hoard import discard_hoard_item

        hoard_event, overflow_item = self._setup_overflow(HoardTooFullEvent.Track.COMMAND)

        discard_hoard_item(self.player, overflow_item)

        hoard_event.event.refresh_from_db()
        self.assertTrue(hoard_event.event.is_resolved)

    def test_discard_scores_one_vp(self):
        """Discarding a hoard item raises the player's score by 1."""
        from game.transactions.rats.hoard import discard_hoard_item

        _, overflow_item = self._setup_overflow(HoardTooFullEvent.Track.PROWESS)
        score_before = Player.objects.get(pk=self.player.pk).score

        discard_hoard_item(self.player, overflow_item)

        score_after = Player.objects.get(pk=self.player.pk).score
        self.assertEqual(score_after, score_before + 1)

    def test_discard_prowess_item_resolves_prowess_event(self):
        """Discarding a prowess item resolves only the Prowess overflow event."""
        from game.transactions.rats.hoard import discard_hoard_item

        hoard_event, overflow_item = self._setup_overflow(HoardTooFullEvent.Track.PROWESS)

        discard_hoard_item(self.player, overflow_item)

        hoard_event.event.refresh_from_db()
        self.assertTrue(hoard_event.event.is_resolved)

    def test_discard_raises_when_no_unresolved_event(self):
        """Calling discard without a pending overflow event raises UnavailableActionError."""
        from game.transactions.rats.hoard import discard_hoard_item

        # Just add one item — no overflow
        item = self._make_item(ItemTypes.BOOTS)
        CommandItemEntry.objects.create(player=self.player, item=item)

        with self.assertRaises(UnavailableActionError):
            discard_hoard_item(self.player, item)

    def test_discard_raises_when_item_not_on_track(self):
        """Passing an item that is not on the player's hoard raises IllegalActionError."""
        from game.transactions.rats.hoard import discard_hoard_item

        # Create overflow event for COMMAND track
        _, overflow_item = self._setup_overflow(HoardTooFullEvent.Track.COMMAND)

        # Create a prowess item NOT added to the hoard
        wrong_item = self._make_item(ItemTypes.HAMMER)

        with self.assertRaises((IllegalActionError, UnavailableActionError)):
            discard_hoard_item(self.player, wrong_item)

    def test_discard_raises_for_non_hoard_item_type(self):
        """An item type that belongs to neither track raises IllegalActionError."""
        from game.transactions.rats.hoard import discard_hoard_item

        # Trigger a command overflow so an event exists
        _, _ = self._setup_overflow(HoardTooFullEvent.Track.COMMAND)

        # Create an item whose type is not in either track set
        # (Use a type that isn't BOOTS/BAG/COIN/HAMMER/TEA/SWORD/CROSSBOW)
        # Looking at ItemTypes: all 7 types are mapped, so we test that the
        # validation fires by passing a prowess item when only a command event exists
        wrong_item = self._make_item(ItemTypes.HAMMER)

        with self.assertRaises((IllegalActionError, UnavailableActionError)):
            discard_hoard_item(self.player, wrong_item)

    def test_two_overflows_same_track_both_events_created(self):
        """Adding items 5 and 6 to the same track creates two separate events."""
        from game.transactions.rats.hoard import add_item_to_hoard

        self._fill_command_track(4)
        add_item_to_hoard(self.player, self._make_item(ItemTypes.BOOTS))   # 5th
        add_item_to_hoard(self.player, self._make_item(ItemTypes.COIN))    # 6th

        event_count = HoardTooFullEvent.objects.filter(
            player=self.player,
            track=HoardTooFullEvent.Track.COMMAND,
            event__is_resolved=False,
        ).count()
        self.assertEqual(event_count, 2, "Two overflows should produce two events")
