"""Tests for game/transactions/rats/jubilant.py.

Jubilant mood: after Incite in the Warlord's clearing, the player may roll the
mob die up to four times, placing a mob in a matching clearing adjacent to any
existing mob.

Map reference (Autumn map, 1-indexed):
  Fox (r):    1, 6, 8, 12
  Rabbit (y): 3, 4, 5, 10
  Mouse (o):  2, 7, 9, 11

  C2 (mouse/orange) — Warlord setup corner
  C2 ↔ C5 (rabbit), C6 (fox), C10 (rabbit)
  C5 ↔ C1 (fox), C2 (mouse)
  C6 ↔ C2 (mouse), C3 (rabbit), C11 (mouse)
  C10 ↔ C1 (fox), C2 (mouse), C12 (fox)
  C12 ↔ C4 (rabbit), C7 (mouse), C9 (mouse), C10 (rabbit), C11 (mouse)
"""

from unittest.mock import patch

from django.test import TestCase

from game.errors import IllegalActionError, UnavailableActionError
from game.models.enums import Suit
from game.models.events.event import EventType
from game.models.events.rats import JubilantMobSpreadEvent
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing, Faction, Game, Warrior
from game.models.rats.player import RatsPlayerState
from game.models.rats.tokens import Mob, Warlord
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsEvening, RatsTurn
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Shared base: Rats game at INCITE step, Jubilant mood
# ---------------------------------------------------------------------------


class JubilantBaseTestCase(TestCase):
    """RATS + CATS game at the INCITE Evening step with Jubilant mood.

    Warlord is in C2 (mouse/orange) after setup.
    Mobs start fully in supply (none placed).
    """

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
        birdsong = self.rats_turn.birdsong.first()
        birdsong.step = RatsBirdsong.Steps.COMPLETED
        birdsong.save()
        daylight = self.rats_turn.daylight.first()
        daylight.step = RatsDaylight.Steps.COMPLETED
        daylight.save()
        self.evening = self.rats_turn.evening.first()
        self.evening.step = RatsEvening.Steps.INCITE
        self.evening.save()

        self.warlord = Warlord.objects.get(player=self.player)

        # Set Jubilant mood
        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": RatsPlayerState.MoodType.JUBILANT},
        )

    def _place_mob(self, clearing: Clearing) -> Mob:
        mob = Mob.objects.filter(player=self.player, clearing__isnull=True).first()
        self.assertIsNotNone(mob, "No mobs in supply")
        mob.clearing = clearing
        mob.save()
        return mob

    def _create_jubilant_event(self, rolls_remaining=4) -> JubilantMobSpreadEvent:
        evt = JubilantMobSpreadEvent.create(self.player)
        evt.rolls_remaining = rolls_remaining
        evt.save()
        return evt

    def _clearing(self, n: int) -> Clearing:
        return Clearing.objects.get(game=self.game, clearing_number=n)


# ===========================================================================
# incite() hook — event creation
# ===========================================================================


class JubilantInciteHookTests(JubilantBaseTestCase):
    """incite() should create a JubilantMobSpreadEvent when conditions are met."""

    def _add_card_to_hand(self, card_enum):
        from game.game_data.cards.exiles_and_partisans import CardsEP
        from game.models.game_models import Card, HandEntry
        card = Card.objects.create(game=self.game, card_type=card_enum.name)
        return HandEntry.objects.create(player=self.player, card=card)

    def test_incite_in_warlord_clearing_creates_jubilant_event(self):
        """Inciting in the Warlord's clearing while Jubilant creates a JubilantMobSpreadEvent."""
        from game.game_data.cards.exiles_and_partisans import CardsEP
        from game.transactions.rats.evening import incite

        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        incite(self.player, self.c2, CardsEP.ROOT_TEA_ORANGE)

        self.assertTrue(
            JubilantMobSpreadEvent.objects.filter(
                player=self.player, event__is_resolved=False
            ).exists()
        )

    def test_incite_outside_warlord_clearing_no_event(self):
        """Inciting outside the Warlord's clearing does not create the event."""
        from game.game_data.cards.exiles_and_partisans import CardsEP
        from game.models.game_models import Warrior
        from game.transactions.rats.evening import incite

        # Place a warrior in C5 (rabbit/yellow) and use a matching card
        warrior = Warrior.objects.filter(player=self.player, clearing__isnull=True, warlord__isnull=True).first()
        c5 = self._clearing(5)
        warrior.clearing = c5
        warrior.save()

        self._add_card_to_hand(CardsEP.RABBIT_PARTISANS)
        incite(self.player, c5, CardsEP.RABBIT_PARTISANS)

        self.assertFalse(
            JubilantMobSpreadEvent.objects.filter(
                player=self.player, event__is_resolved=False
            ).exists()
        )

    def test_incite_no_mob_in_supply_no_event(self):
        """If no mobs remain in supply after placing, no JubilantMobSpreadEvent is created."""
        from game.game_data.cards.exiles_and_partisans import CardsEP
        from game.transactions.rats.evening import incite

        # Exhaust all supply mobs except the one incite will place
        clearings = list(
            Clearing.objects.filter(game=self.game).exclude(pk=self.c2.pk)
        )
        supply_mobs = list(Mob.objects.filter(player=self.player, clearing__isnull=True))
        # Leave exactly 1 in supply (incite will use it) and place the rest
        for mob, clearing in zip(supply_mobs[:-1], clearings):
            mob.clearing = clearing
            mob.save()

        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        incite(self.player, self.c2, CardsEP.ROOT_TEA_ORANGE)

        # After incite, supply is empty → no event should be created
        self.assertFalse(
            JubilantMobSpreadEvent.objects.filter(
                player=self.player, event__is_resolved=False
            ).exists()
        )

    def test_incite_non_jubilant_mood_no_event(self):
        """A non-Jubilant mood does not create the event even when inciting in Warlord's clearing."""
        from game.game_data.cards.exiles_and_partisans import CardsEP
        from game.transactions.rats.evening import incite

        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": RatsPlayerState.MoodType.GRANDIOSE},
        )

        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        incite(self.player, self.c2, CardsEP.ROOT_TEA_ORANGE)

        self.assertFalse(
            JubilantMobSpreadEvent.objects.filter(
                player=self.player, event__is_resolved=False
            ).exists()
        )


# ===========================================================================
# jubilant_roll
# ===========================================================================


class JubilantRollTests(JubilantBaseTestCase):
    """Tests for jubilant_roll()."""

    def test_roll_with_no_active_event_raises(self):
        """jubilant_roll raises if no active event exists."""
        from game.transactions.rats.jubilant import jubilant_roll

        with self.assertRaises(UnavailableActionError):
            jubilant_roll(self.player)

    def test_roll_when_no_mobs_in_supply_resolves_event(self):
        """jubilant_roll resolves immediately if no mobs remain in supply."""
        from game.transactions.rats.jubilant import jubilant_roll

        # Exhaust all mobs
        clearings = list(Clearing.objects.filter(game=self.game))
        for mob, clearing in zip(Mob.objects.filter(player=self.player), clearings):
            mob.clearing = clearing
            mob.save()

        evt = self._create_jubilant_event(rolls_remaining=4)
        jubilant_roll(self.player)

        evt.event.refresh_from_db()
        self.assertTrue(evt.event.is_resolved)

    def test_roll_zero_remaining_resolves_event(self):
        """jubilant_roll resolves event if rolls_remaining is already 0."""
        from game.transactions.rats.jubilant import jubilant_roll

        evt = self._create_jubilant_event(rolls_remaining=0)
        jubilant_roll(self.player)

        evt.event.refresh_from_db()
        self.assertTrue(evt.event.is_resolved)

    def test_roll_no_targets_decrements_rolls(self):
        """jubilant_roll with no valid targets wastes the roll and decrements counter."""
        from game.transactions.rats.jubilant import jubilant_roll

        # Place a mob somewhere so roll can happen, but mock targets to empty set
        self._place_mob(self.c2)
        evt = self._create_jubilant_event(rolls_remaining=2)

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value=set(),
        ):
            jubilant_roll(self.player)

        evt.refresh_from_db()
        self.assertEqual(evt.rolls_remaining, 1)
        self.assertIsNone(evt.current_roll)
        evt.event.refresh_from_db()
        self.assertFalse(evt.event.is_resolved)

    def test_roll_no_targets_last_roll_resolves_event(self):
        """jubilant_roll with no targets and 1 roll remaining resolves the event."""
        from game.transactions.rats.jubilant import jubilant_roll

        self._place_mob(self.c2)
        evt = self._create_jubilant_event(rolls_remaining=1)

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value=set(),
        ):
            jubilant_roll(self.player)

        evt.event.refresh_from_db()
        self.assertTrue(evt.event.is_resolved)

    def test_roll_one_target_auto_places_mob(self):
        """jubilant_roll with exactly one target auto-places the mob."""
        from game.transactions.rats.jubilant import jubilant_roll

        # Place mob in C2; C6 (fox) is adjacent → one fox target
        self._place_mob(self.c2)
        c6 = self._clearing(6)

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c6},
        ):
            evt = self._create_jubilant_event(rolls_remaining=2)
            jubilant_roll(self.player)

        self.assertTrue(Mob.objects.filter(player=self.player, clearing=c6).exists())

    def test_roll_one_target_decrements_rolls(self):
        """After auto-placing, rolls_remaining is decremented."""
        from game.transactions.rats.jubilant import jubilant_roll

        self._place_mob(self.c2)
        c6 = self._clearing(6)

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c6},
        ):
            evt = self._create_jubilant_event(rolls_remaining=3)
            jubilant_roll(self.player)

        evt.refresh_from_db()
        self.assertEqual(evt.rolls_remaining, 2)

    def test_roll_one_target_last_roll_resolves(self):
        """Auto-placing on the last roll resolves the event."""
        from game.transactions.rats.jubilant import jubilant_roll

        self._place_mob(self.c2)
        c6 = self._clearing(6)

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c6},
        ):
            evt = self._create_jubilant_event(rolls_remaining=1)
            jubilant_roll(self.player)

        evt.event.refresh_from_db()
        self.assertTrue(evt.event.is_resolved)

    def test_roll_multiple_targets_stores_suit(self):
        """jubilant_roll with multiple targets records current_roll and waits for choice."""
        from game.transactions.rats.jubilant import jubilant_roll

        self._place_mob(self.c2)
        c5 = self._clearing(5)
        c10 = self._clearing(10)

        with patch(
            "game.transactions.rats.jubilant.random.choice",
            return_value=Suit.YELLOW,
        ):
            with patch(
                "game.transactions.rats.jubilant.get_mob_spread_targets",
                return_value={c5, c10},
            ):
                evt = self._create_jubilant_event(rolls_remaining=4)
                jubilant_roll(self.player)

        evt.refresh_from_db()
        self.assertEqual(evt.current_roll, Suit.YELLOW)
        self.assertEqual(evt.rolls_remaining, 3)
        evt.event.refresh_from_db()
        self.assertFalse(evt.event.is_resolved)


# ===========================================================================
# jubilant_choose_clearing
# ===========================================================================


class JubilantChooseClearingTests(JubilantBaseTestCase):
    """Tests for jubilant_choose_clearing()."""

    def _setup_pending_choice(self, suit: Suit, targets: set) -> JubilantMobSpreadEvent:
        """Create an event with a pending roll choice already recorded."""
        evt = self._create_jubilant_event(rolls_remaining=2)
        evt.current_roll = suit
        evt.save()
        return evt

    def test_choose_with_no_event_raises(self):
        from game.transactions.rats.jubilant import jubilant_choose_clearing

        c6 = self._clearing(6)
        with self.assertRaises(UnavailableActionError):
            jubilant_choose_clearing(self.player, c6)

    def test_choose_when_no_roll_in_progress_raises(self):
        from game.transactions.rats.jubilant import jubilant_choose_clearing

        self._create_jubilant_event(rolls_remaining=2)  # current_roll is None
        c6 = self._clearing(6)
        with self.assertRaises(UnavailableActionError):
            jubilant_choose_clearing(self.player, c6)

    def test_choose_invalid_clearing_raises(self):
        from game.transactions.rats.jubilant import jubilant_choose_clearing

        self._place_mob(self.c2)
        evt = self._setup_pending_choice(Suit.YELLOW, set())

        # C8 is fox, not adjacent to C2's mobs in a typical config; use empty targets mock
        c8 = self._clearing(8)
        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value=set(),
        ):
            with self.assertRaises(IllegalActionError):
                jubilant_choose_clearing(self.player, c8)

    def test_choose_valid_clearing_places_mob(self):
        from game.transactions.rats.jubilant import jubilant_choose_clearing

        self._place_mob(self.c2)
        c5 = self._clearing(5)  # rabbit adjacent to C2
        c10 = self._clearing(10)  # rabbit adjacent to C2

        evt = self._setup_pending_choice(Suit.YELLOW, {c5, c10})

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c5, c10},
        ):
            jubilant_choose_clearing(self.player, c5)

        self.assertTrue(Mob.objects.filter(player=self.player, clearing=c5).exists())

    def test_choose_clears_current_roll(self):
        from game.transactions.rats.jubilant import jubilant_choose_clearing

        self._place_mob(self.c2)
        c5 = self._clearing(5)
        c10 = self._clearing(10)
        evt = self._setup_pending_choice(Suit.YELLOW, {c5, c10})

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c5, c10},
        ):
            jubilant_choose_clearing(self.player, c5)

        evt.refresh_from_db()
        self.assertIsNone(evt.current_roll)

    def test_choose_last_roll_resolves_event(self):
        from game.transactions.rats.jubilant import jubilant_choose_clearing

        self._place_mob(self.c2)
        c5 = self._clearing(5)
        evt = self._setup_pending_choice(Suit.YELLOW, {c5})
        evt.rolls_remaining = 0
        evt.save()

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c5},
        ):
            jubilant_choose_clearing(self.player, c5)

        evt.event.refresh_from_db()
        self.assertTrue(evt.event.is_resolved)

    def test_choose_with_rolls_remaining_does_not_resolve(self):
        from game.transactions.rats.jubilant import jubilant_choose_clearing

        self._place_mob(self.c2)
        c5 = self._clearing(5)
        c10 = self._clearing(10)
        evt = self._setup_pending_choice(Suit.YELLOW, {c5, c10})

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c5, c10},
        ):
            jubilant_choose_clearing(self.player, c5)

        evt.event.refresh_from_db()
        self.assertFalse(evt.event.is_resolved)

    def test_choose_exhausts_supply_resolves_event(self):
        """If placing the mob exhausts the supply, the event resolves even with rolls left."""
        from game.transactions.rats.jubilant import jubilant_choose_clearing

        # Place all supply mobs except exactly one (which jubilant_choose_clearing will use)
        all_supply = list(Mob.objects.filter(player=self.player, clearing__isnull=True))
        # Need at least 2 mobs to make this test meaningful; place all but the last
        other_clearings = list(Clearing.objects.filter(game=self.game).exclude(pk=self.c2.pk))
        for mob, cl in zip(all_supply[:-1], other_clearings):
            mob.clearing = cl
            mob.save()
        # Exactly 1 mob left in supply

        # Also need a mob on the board so get_mob_spread_targets can return targets
        # Place the "spread from" mob directly (not from supply — use c2 which already has warlord)
        # Actually we need a mob in a clearing so targets can be calculated.
        # Bypass this by mocking targets.
        c5 = self._clearing(5)
        evt = self._setup_pending_choice(Suit.YELLOW, {c5})
        evt.rolls_remaining = 2  # still has rolls left
        evt.save()

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c5},
        ):
            jubilant_choose_clearing(self.player, c5)

        # Supply is now empty → event should resolve despite rolls_remaining = 1
        evt.event.refresh_from_db()
        self.assertTrue(evt.event.is_resolved)


# ===========================================================================
# jubilant_end
# ===========================================================================


class JubilantEndTests(JubilantBaseTestCase):
    """Tests for jubilant_end()."""

    def test_end_with_no_event_raises(self):
        from game.transactions.rats.jubilant import jubilant_end

        with self.assertRaises(UnavailableActionError):
            jubilant_end(self.player)

    def test_end_resolves_event(self):
        from game.transactions.rats.jubilant import jubilant_end

        evt = self._create_jubilant_event(rolls_remaining=3)
        jubilant_end(self.player)

        evt.event.refresh_from_db()
        self.assertTrue(evt.event.is_resolved)

    def test_end_with_zero_rolls_remaining_resolves(self):
        from game.transactions.rats.jubilant import jubilant_end

        evt = self._create_jubilant_event(rolls_remaining=0)
        jubilant_end(self.player)

        evt.event.refresh_from_db()
        self.assertTrue(evt.event.is_resolved)
