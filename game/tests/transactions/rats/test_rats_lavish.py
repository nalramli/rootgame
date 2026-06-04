"""Tests for game/transactions/rats/lavish.py and the BEFORE_END Lavish hook.

Lavish mood: at the end of Birdsong, the player may remove any number of items
from their Hoard permanently. For each item removed, 2 warriors are placed in
the Warlord's clearing. The event fires at the BEFORE_END step and is guarded
by lavish_complete to prevent double-triggering after resolution.

Map reference (Autumn map):
  C2 (mouse/orange) — Warlord setup corner
"""

from django.test import TestCase

from game.errors import IllegalActionError, UnavailableActionError
from game.models.enums import ItemTypes
from game.models.events.event import EventType
from game.models.events.rats import LavishEvent
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing, Faction, Game, Item, Warrior
from game.models.rats.player import CommandItemEntry, RatsPlayerState, ProwessItemEntry
from game.models.rats.tokens import Warlord
from game.models.rats.turn import RatsBirdsong, RatsTurn
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats.lavish import end_lavish_step, liquidate_hoard_item
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------


class LavishBaseTestCase(TestCase):
    """RATS + CATS game at BEFORE_END birdsong step with Lavish mood and
    the Warlord placed in C2."""

    def setUp(self):
        self.game = GameSetupFactory(factions=[Faction.RATS, Faction.CATS])
        self.player = self.game.players.get(faction=Faction.RATS)

        game_setup = GameSimpleSetup.objects.get(game=self.game)
        game_setup.status = GameSimpleSetup.GameSetupStatus.RATS_SETUP
        game_setup.save()

        self.c2 = Clearing.objects.get(game=self.game, clearing_number=2)
        rats_pick_corner(self.player, self.c2)
        rats_confirm_setup(self.player)

        self.game.refresh_from_db()
        self.game.current_turn = self.player.turn_order
        self.game.status = Game.GameStatus.SETUP_COMPLETED
        self.game.save()

        self.rats_turn = RatsTurn.create_turn(self.player)
        self.birdsong = self.rats_turn.birdsong.first()
        self.birdsong.step = RatsBirdsong.Steps.BEFORE_END
        self.birdsong.save()

        self.warlord = Warlord.objects.get(player=self.player)

        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": RatsPlayerState.MoodType.LAVISH},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_item(self, item_type: str) -> Item:
        return Item.objects.create(game=self.game, item_type=item_type)

    def _add_command_item(self, item_type: str = ItemTypes.BOOTS) -> Item:
        item = self._make_item(item_type)
        CommandItemEntry.objects.create(player=self.player, item=item)
        return item

    def _add_prowess_item(self, item_type: str = ItemTypes.HAMMER) -> Item:
        item = self._make_item(item_type)
        ProwessItemEntry.objects.create(player=self.player, item=item)
        return item

    def _create_lavish_event(self) -> LavishEvent:
        return LavishEvent.create(self.player)

    def _warrior_count_in_clearing(self, clearing: Clearing) -> int:
        return Warrior.objects.filter(
            player=self.player, clearing=clearing, warlord__isnull=True
        ).count()

    def _warrior_supply_count(self) -> int:
        return Warrior.objects.filter(
            player=self.player, clearing__isnull=True, warlord__isnull=True
        ).count()


# ===========================================================================
# BEFORE_END hook — event creation via step_effect
# ===========================================================================


class LavishHookTests(LavishBaseTestCase):
    """step_effect at BEFORE_END should create LavishEvent when conditions met."""

    def _run_step_effect(self):
        from game.transactions.rats.turn import step_effect
        self.birdsong.refresh_from_db()
        step_effect(self.player, self.birdsong)

    def test_creates_lavish_event_when_lavish_and_has_items(self):
        """BEFORE_END creates a LavishEvent when Lavish mood + hoard has items."""
        self._add_command_item()
        self._run_step_effect()

        self.assertTrue(
            LavishEvent.objects.filter(
                player=self.player, event__is_resolved=False
            ).exists()
        )

    def test_does_not_create_event_when_not_lavish(self):
        """BEFORE_END does not create event if mood is not Lavish."""
        self._add_command_item()
        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": RatsPlayerState.MoodType.GRANDIOSE},
        )

        self._run_step_effect()

        self.assertFalse(
            LavishEvent.objects.filter(player=self.player).exists()
        )

    def test_does_not_create_event_when_hoard_empty(self):
        """BEFORE_END does not create event if hoard has no items (nothing to liquidate)."""
        # Hoard is empty by default — no items added
        self._run_step_effect()

        self.assertFalse(
            LavishEvent.objects.filter(player=self.player).exists()
        )

    def test_non_lavish_advances_step_to_completed(self):
        """BEFORE_END auto-advances to COMPLETED when not Lavish (Emigre not active)."""
        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": RatsPlayerState.MoodType.GRANDIOSE},
        )

        self._run_step_effect()

        self.birdsong.refresh_from_db()
        self.assertEqual(self.birdsong.step, RatsBirdsong.Steps.COMPLETED)

    def test_no_double_trigger_after_event_resolves(self):
        """After end_lavish_step resolves the event and calls step_effect, BEFORE_END
        does not create a second LavishEvent — lavish_complete guards it."""
        self._add_command_item()

        # First call: creates event
        self._run_step_effect()
        self.assertEqual(LavishEvent.objects.filter(player=self.player).count(), 1)

        # Resolve the event (simulates what end_lavish_step does)
        evt = LavishEvent.objects.get(player=self.player)
        evt.event.is_resolved = True
        evt.event.save()
        self.birdsong.lavish_complete = True
        self.birdsong.save()

        # Second call from step_effect (as called by end_lavish_step): no new event
        self._run_step_effect()

        self.assertEqual(LavishEvent.objects.filter(player=self.player).count(), 1)


# ===========================================================================
# liquidate_hoard_item
# ===========================================================================


class LavishLiquidateTests(LavishBaseTestCase):

    def setUp(self):
        super().setUp()
        self.evt = self._create_lavish_event()

    def test_removes_command_entry_and_item(self):
        """Liquidating a command item deletes CommandItemEntry and Item."""
        item = self._add_command_item()
        item_id = item.id

        liquidate_hoard_item(self.player, item.item_type)

        self.assertFalse(CommandItemEntry.objects.filter(player=self.player, item_id=item_id).exists())
        self.assertFalse(Item.objects.filter(id=item_id).exists())

    def test_removes_prowess_entry_and_item(self):
        """Liquidating a prowess item deletes ProwessItemEntry and Item."""
        item = self._add_prowess_item()
        item_id = item.id

        liquidate_hoard_item(self.player, item.item_type)

        self.assertFalse(ProwessItemEntry.objects.filter(player=self.player, item_id=item_id).exists())
        self.assertFalse(Item.objects.filter(id=item_id).exists())

    def test_places_two_warriors_in_warlord_clearing(self):
        """Liquidating an item places 2 warriors in the Warlord's clearing."""
        item = self._add_command_item()
        before = self._warrior_count_in_clearing(self.c2)

        liquidate_hoard_item(self.player, item.item_type)

        after = self._warrior_count_in_clearing(self.c2)
        self.assertEqual(after - before, 2)

    def test_places_one_warrior_when_supply_has_one(self):
        """When supply has exactly 1 warrior, only 1 is placed (no error)."""
        item = self._add_command_item()
        # Leave exactly 1 warrior in supply
        warriors = list(
            Warrior.objects.filter(
                player=self.player, clearing__isnull=True, warlord__isnull=True
            )
        )
        for w in warriors[1:]:
            w.clearing = self.c2
            w.save()

        before = self._warrior_count_in_clearing(self.c2)
        liquidate_hoard_item(self.player, item.item_type)
        after = self._warrior_count_in_clearing(self.c2)
        self.assertEqual(after - before, 1)

    def test_raises_illegal_action_if_supply_empty(self):
        """Raises IllegalActionError when warrior supply is 0."""
        item = self._add_command_item()
        # Exhaust all warriors
        for w in Warrior.objects.filter(
            player=self.player, clearing__isnull=True, warlord__isnull=True
        ):
            w.clearing = self.c2
            w.save()

        with self.assertRaises(IllegalActionError):
            liquidate_hoard_item(self.player, item.item_type)

    def test_raises_illegal_action_if_item_not_in_hoard(self):
        """Raises IllegalActionError if the item is not in this player's Hoard."""
        other_item = self._make_item(ItemTypes.BOOTS)  # not added to any entry

        with self.assertRaises(IllegalActionError):
            liquidate_hoard_item(self.player, other_item.item_type)

    def test_raises_unavailable_if_no_active_event(self):
        """Raises UnavailableActionError if no LavishEvent is active."""
        self.evt.event.is_resolved = True
        self.evt.event.save()
        item = self._add_command_item()

        with self.assertRaises(UnavailableActionError):
            liquidate_hoard_item(self.player, item.item_type)

    def test_auto_resolves_event_when_last_item_liquidated(self):
        """When the last hoard item is liquidated, the event auto-resolves."""
        item = self._add_command_item()  # only item in hoard

        liquidate_hoard_item(self.player, item.item_type)

        self.evt.event.refresh_from_db()
        self.assertTrue(self.evt.event.is_resolved)

    def test_does_not_auto_resolve_when_items_remain(self):
        """The event is NOT resolved when items still remain in the hoard."""
        item1 = self._add_command_item(ItemTypes.BOOTS)
        self._add_command_item(ItemTypes.BAG)  # second item

        liquidate_hoard_item(self.player, item1.item_type)

        self.evt.event.refresh_from_db()
        self.assertFalse(self.evt.event.is_resolved)


# ===========================================================================
# end_lavish_step
# ===========================================================================


class LavishEndTests(LavishBaseTestCase):

    def setUp(self):
        super().setUp()
        self.evt = self._create_lavish_event()

    def test_resolves_event(self):
        """end_lavish_step marks the event as resolved."""
        end_lavish_step(self.player)

        self.evt.event.refresh_from_db()
        self.assertTrue(self.evt.event.is_resolved)

    def test_sets_lavish_complete_on_birdsong(self):
        """end_lavish_step sets lavish_complete=True on the RatsBirdsong phase."""
        end_lavish_step(self.player)

        self.birdsong.refresh_from_db()
        self.assertTrue(self.birdsong.lavish_complete)

    def test_advances_birdsong_past_before_end(self):
        """After end_lavish_step, birdsong step advances past BEFORE_END."""
        end_lavish_step(self.player)

        self.birdsong.refresh_from_db()
        self.assertNotEqual(self.birdsong.step, RatsBirdsong.Steps.BEFORE_END)

    def test_raises_unavailable_if_no_active_event(self):
        """Raises UnavailableActionError if no LavishEvent is active."""
        self.evt.event.is_resolved = True
        self.evt.event.save()

        with self.assertRaises(UnavailableActionError):
            end_lavish_step(self.player)
