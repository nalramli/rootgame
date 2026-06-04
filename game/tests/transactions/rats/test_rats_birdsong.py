"""Tests for game/transactions/rats/birdsong.py.

Transaction functions are imported locally inside each test method so this
file can be created before the transactions module exists (they already do
exist; the local import style is kept for consistency with the project pattern).

Setup approach
--------------
* Use GameSetupFactory(factions=[Faction.RATS, Faction.CATS]) — RATS is fully
  supported by begin_faction_setup (start_simple_rats_setup is wired in).
* After GameSetupFactory returns the game is in STARTED state but rats setup
  is not yet complete (begin_faction_setup only initialises pieces).
* We therefore:
  1. Force game_setup.status = RATS_SETUP.
  2. Call pick_corner (clearing 2) + confirm_completed_setup to complete rats
     setup, which calls next_player_setup and eventually transitions to
     SETUP_COMPLETED and creates the first faction's turn.
  3. Force game.current_turn to the rats player's turn_order so that
     validate_turn() passes.
  4. Manually create a RatsTurn and set birdsong.step to the step under test.

Map reference (Autumn map, 1-indexed)
--------------------------------------
Fox (r):    1, 6, 8, 12
Rabbit (y): 3, 4, 5, 10
Mouse (o):  2, 7, 9, 11

Corner clearings: 1–4.

Key adjacencies (0-indexed in code, 1-indexed here):
  C1  ↔ C5, C9, C10
  C2  ↔ C5, C6, C10
  C3  ↔ C6, C7, C11
  C4  ↔ C8, C9, C12
  C5  ↔ C1, C2
  C6  ↔ C2, C3, C11
  C7  ↔ C3, C8, C12
  C8  ↔ C4, C7
  C9  ↔ C1, C4, C12
  C10 ↔ C1, C2, C12
  C11 ↔ C3, C6, C12
  C12 ↔ C4, C7, C9, C10, C11
"""

from django.test import TestCase

from game.errors import IllegalActionError, UnavailableActionError
from game.models.enums import ItemTypes, Suit
from game.models.game_models import (
    BuildingSlot,
    Clearing,
    Faction,
    Item,
    Player,
    Ruin,
    Warrior,
)
from game.models.rats.buildings import Stronghold
from game.models.rats.player import CommandItemEntry, RatsPlayerState, ProwessItemEntry
from game.models.rats.tokens import Mob, Warlord
from game.models.rats.turn import RatsBirdsong, RatsTurn
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Game
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats.turn import reset_rats_turn
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)

# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------


class RatsBirdsongBaseTestCase(TestCase):
    """Creates a RATS + CATS game with rats in Birdsong at the RAZE step."""

    def setUp(self):
        self.game = GameSetupFactory(factions=[Faction.RATS, Faction.CATS])
        self.player = self.game.players.get(faction=Faction.RATS)
        self.cats_player = self.game.players.get(faction=Faction.CATS)

        # Complete rats setup: force status, pick corner 2, confirm.
        game_setup = GameSimpleSetup.objects.get(game=self.game)
        game_setup.status = GameSimpleSetup.GameSetupStatus.RATS_SETUP
        game_setup.save()

        c2 = Clearing.objects.get(game=self.game, clearing_number=2)
        rats_pick_corner(self.player, c2)
        rats_confirm_setup(self.player)

        # Point game.current_turn at the rats player and set status.
        self.game.refresh_from_db()
        self.game.current_turn = self.player.turn_order
        self.game.status = Game.GameStatus.SETUP_COMPLETED
        self.game.save()

        # Create a rats turn and advance birdsong to RAZE.
        self.rats_turn = RatsTurn.create_turn(self.player)
        self.birdsong = self.rats_turn.birdsong.first()
        self.birdsong.step = RatsBirdsong.Steps.RAZE
        self.birdsong.save()

        # Warlord was placed in clearing 2 by pick_corner.
        self.warlord_clearing = c2

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mob_in_clearing(self, clearing: Clearing) -> Mob:
        """Place one mob token from supply into *clearing*."""
        mob = Mob.objects.filter(player=self.player, clearing__isnull=True).first()
        self.assertIsNotNone(mob, "No mobs left in supply")
        mob.clearing = clearing
        mob.save()
        return mob

    def _warrior_in_clearing(self, clearing: Clearing) -> Warrior:
        """Place one regular warrior (not warlord) from supply into *clearing*."""
        w = (
            Warrior.objects.filter(player=self.player, clearing__isnull=True)
            .filter(warlord__isnull=True)
            .first()
        )
        self.assertIsNotNone(w, "No regular warriors left in supply")
        w.clearing = clearing
        w.save()
        return w

    def _set_step(self, step: RatsBirdsong.Steps):
        self.birdsong.step = step
        self.birdsong.save()

    def _total_hoard_items(self) -> int:
        cmd = CommandItemEntry.objects.filter(player=self.player).count()
        prw = ProwessItemEntry.objects.filter(player=self.player).count()
        return cmd + prw


# ===========================================================================
# raze()
# ===========================================================================


class RazeTests(RatsBirdsongBaseTestCase):

    def test_raze_removes_enemy_building_in_mob_clearing(self):
        """Enemy building in a mob clearing should be removed by raze."""
        from game.transactions.rats.birdsong import raze
        from game.models.cats.buildings import Sawmill

        # Place mob and a cats sawmill both in clearing 6 (fox).
        c6 = Clearing.objects.get(game=self.game, clearing_number=6)
        self._mob_in_clearing(c6)

        slot = BuildingSlot.objects.filter(clearing=c6).first()
        self.assertIsNotNone(slot)
        sawmill = Sawmill(player=self.cats_player, building_slot=slot)
        sawmill.save()
        sawmill_pk = sawmill.pk

        self._set_step(RatsBirdsong.Steps.RAZE)
        raze(self.player)

        sawmill = Sawmill.objects.get(pk=sawmill_pk)
        self.assertIsNone(
            sawmill.building_slot,
            "Enemy building should have been returned to supply by raze",
        )

    def test_raze_removes_enemy_token_in_mob_clearing(self):
        """Enemy token in a mob clearing should be removed; the mob itself stays."""
        from game.transactions.rats.birdsong import raze
        from game.models.cats.tokens import CatWood

        c6 = Clearing.objects.get(game=self.game, clearing_number=6)
        self._mob_in_clearing(c6)

        cat_wood = CatWood(player=self.cats_player, clearing=c6)
        cat_wood.save()
        cat_wood_pk = cat_wood.pk

        self._set_step(RatsBirdsong.Steps.RAZE)
        raze(self.player)

        cat_wood = CatWood.objects.get(pk=cat_wood_pk)
        self.assertIsNone(
            cat_wood.clearing,
            "Enemy token should have been returned to supply by raze",
        )
        # Mob stays
        self.assertTrue(
            Mob.objects.filter(player=self.player, clearing=c6).exists(),
            "Mob should remain after raze",
        )

    def test_raze_grants_ruin_item_when_mob_is_on_ruin_clearing(self):
        """Raze should add the ruin's item to the hoard when a mob is on a ruin clearing."""
        from game.transactions.rats.birdsong import raze

        ruin = Ruin.objects.filter(game=self.game, building_slot__isnull=False).first()
        self.assertIsNotNone(ruin, "Expected at least one ruin on the map")
        ruin_clearing = ruin.building_slot.clearing

        self._mob_in_clearing(ruin_clearing)
        self._set_step(RatsBirdsong.Steps.RAZE)

        hoard_before = self._total_hoard_items()
        raze(self.player)
        hoard_after = self._total_hoard_items()

        self.assertGreater(
            hoard_after, hoard_before, "Ruin item should be added to hoard"
        )

    def test_raze_does_not_remove_own_pieces(self):
        """Raze should never remove rats' own pieces from mob clearings."""
        from game.transactions.rats.birdsong import raze

        c6 = Clearing.objects.get(game=self.game, clearing_number=6)
        self._mob_in_clearing(c6)
        self._warrior_in_clearing(c6)
        warrior_count_before = Warrior.objects.filter(
            player=self.player, clearing=c6, warlord__isnull=True
        ).count()

        self._set_step(RatsBirdsong.Steps.RAZE)
        raze(self.player)

        warrior_count_after = Warrior.objects.filter(
            player=self.player, clearing=c6, warlord__isnull=True
        ).count()
        self.assertEqual(warrior_count_after, warrior_count_before)

    def test_raze_advances_step_past_raze(self):
        """After raze, birdsong step should advance past RAZE.

        SPREAD_MOB may itself auto-advance (no mobs on board yet), so we only
        assert the step changed — not that it stopped at a specific value.
        """
        from game.transactions.rats.birdsong import raze

        self._set_step(RatsBirdsong.Steps.RAZE)
        raze(self.player)

        self.birdsong.refresh_from_db()
        self.assertNotEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.RAZE,
            "Step should have advanced past RAZE",
        )


# ===========================================================================
# roll_mob_die_and_spread()
# ===========================================================================


class RollMobDieTests(RatsBirdsongBaseTestCase):

    def test_no_mobs_in_supply_advances_step(self):
        """If all mobs are already on the map, skip spreading and advance."""
        from game.transactions.rats.birdsong import roll_mob_die_and_spread

        # Deplete supply by placing all mobs on the map
        supply_mobs = list(
            Mob.objects.filter(player=self.player, clearing__isnull=True)
        )
        clearings = list(Clearing.objects.filter(game=self.game))
        for i, mob in enumerate(supply_mobs):
            mob.clearing = clearings[i % len(clearings)]
            mob.save()

        self._set_step(RatsBirdsong.Steps.SPREAD_MOB)
        roll_mob_die_and_spread(self.player)

        self.birdsong.refresh_from_db()
        self.assertNotEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.SPREAD_MOB,
            "Step should have advanced when no mobs remain in supply",
        )

    def test_exactly_one_valid_target_places_mob_and_advances(self):
        """When exactly one valid clearing exists, mob is placed there automatically."""
        from game.transactions.rats.birdsong import roll_mob_die_and_spread
        from unittest.mock import patch

        # Place a mob in C2 (mouse/orange).
        # C2 is adjacent to C5(rabbit), C6(fox), C10(rabbit).
        # Fox (red) neighbour of C2 not already containing a mob: C6 only.
        # That is exactly one fox target adjacent to the mob.
        c2 = Clearing.objects.get(game=self.game, clearing_number=2)
        self._mob_in_clearing(c2)

        supply_before = Mob.objects.filter(
            player=self.player, clearing__isnull=True
        ).count()

        self._set_step(RatsBirdsong.Steps.SPREAD_MOB)

        # Patch random.choice to return RED so C6 is the only target
        with patch(
            "game.transactions.rats.birdsong.random.choice",
            return_value=Suit.RED,
        ):
            roll_mob_die_and_spread(self.player)

        supply_after = Mob.objects.filter(
            player=self.player, clearing__isnull=True
        ).count()
        self.assertEqual(supply_after, supply_before - 1, "One mob should leave supply")

        # Step should have advanced
        self.birdsong.refresh_from_db()
        self.assertNotEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.SPREAD_MOB,
            "Step should advance after auto-placement",
        )
        # mob_die_suit should be None (no pending choice)
        self.assertIsNone(self.birdsong.mob_die_suit)

    def test_multiple_valid_targets_sets_mob_die_suit_does_not_advance(self):
        """When multiple targets exist, mob_die_suit is set and step stays at SPREAD_MOB."""
        from game.transactions.rats.birdsong import roll_mob_die_and_spread
        from unittest.mock import patch

        # Place mobs in C9 (mouse) and C11 (mouse).
        # Fox (red) clearings adjacent to each:
        #   C9 ↔ C1(fox), C4(rabbit), C12(fox) — fox neighbours: C1, C12
        #   C11 ↔ C3(rabbit), C6(fox), C12(fox) — fox neighbours: C6, C12
        # Combined fox targets: C1, C6, C12 → multiple.
        c9 = Clearing.objects.get(game=self.game, clearing_number=9)
        c11 = Clearing.objects.get(game=self.game, clearing_number=11)
        self._mob_in_clearing(c9)
        self._mob_in_clearing(c11)

        self._set_step(RatsBirdsong.Steps.SPREAD_MOB)

        with patch(
            "game.transactions.rats.birdsong.random.choice",
            return_value=Suit.RED,
        ):
            roll_mob_die_and_spread(self.player)

        self.birdsong.refresh_from_db()
        self.assertEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.SPREAD_MOB,
            "Step should NOT advance when multiple targets exist",
        )
        self.assertEqual(
            self.birdsong.mob_die_suit,
            Suit.RED,
            "mob_die_suit should be set to the rolled suit",
        )

    def test_no_valid_targets_for_rolled_suit_advances(self):
        """When the rolled suit has no valid adjacent clearings, step advances."""
        from game.transactions.rats.birdsong import roll_mob_die_and_spread
        from unittest.mock import patch

        # Place mob at C1 (fox). Rolling RED (fox):
        # Fox clearings adjacent to C1: none — C1 connects to C5(rabbit), C9(mouse), C10(mouse).
        # So there are zero fox targets → step advances.
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        self._mob_in_clearing(c1)

        self._set_step(RatsBirdsong.Steps.SPREAD_MOB)

        with patch(
            "game.transactions.rats.birdsong.random.choice",
            return_value=Suit.RED,
        ):
            roll_mob_die_and_spread(self.player)

        self.birdsong.refresh_from_db()
        self.assertNotEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.SPREAD_MOB,
            "Step should advance when no valid targets exist for rolled suit",
        )


# ===========================================================================
# choose_mob_clearing()
# ===========================================================================


class ChooseMobClearingTests(RatsBirdsongBaseTestCase):
    """Set up a situation with multiple fox targets so choose_mob_clearing is relevant."""

    def setUp(self):
        super().setUp()
        # Same scenario as test_multiple_valid_targets: mobs at C9 and C11
        # yield fox targets C1, C6, C12.
        c9 = Clearing.objects.get(game=self.game, clearing_number=9)
        c11 = Clearing.objects.get(game=self.game, clearing_number=11)
        self._mob_in_clearing(c9)
        self._mob_in_clearing(c11)

        self._set_step(RatsBirdsong.Steps.SPREAD_MOB)
        self.birdsong.mob_die_suit = Suit.RED
        self.birdsong.save()

    def test_valid_clearing_places_mob_and_advances_step(self):
        """Choosing a valid fox clearing places a mob there and advances the step."""
        from game.transactions.rats.birdsong import choose_mob_clearing

        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        supply_before = Mob.objects.filter(
            player=self.player, clearing__isnull=True
        ).count()

        choose_mob_clearing(self.player, c1)

        self.assertEqual(
            Mob.objects.filter(player=self.player, clearing=c1).count(),
            1,
            "Mob should be placed in C1",
        )
        self.assertEqual(
            Mob.objects.filter(player=self.player, clearing__isnull=True).count(),
            supply_before - 1,
        )
        self.birdsong.refresh_from_db()
        self.assertNotEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.SPREAD_MOB,
            "Step should advance after placement",
        )

    def test_wrong_suit_clearing_raises_illegal_action(self):
        """Choosing a clearing of the wrong suit raises IllegalActionError."""
        from game.transactions.rats.birdsong import choose_mob_clearing

        # C2 is mouse (ORANGE) — wrong suit for a RED roll
        c2 = Clearing.objects.get(game=self.game, clearing_number=2)
        with self.assertRaises(IllegalActionError):
            choose_mob_clearing(self.player, c2)

    def test_no_mob_die_suit_raises_unavailable(self):
        """Calling choose_mob_clearing when mob_die_suit is None raises UnavailableActionError."""
        from game.transactions.rats.birdsong import choose_mob_clearing

        self.birdsong.mob_die_suit = None
        self.birdsong.save()

        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        with self.assertRaises(UnavailableActionError):
            choose_mob_clearing(self.player, c1)

    def test_clearing_not_adjacent_to_mob_raises_illegal_action(self):
        """Choosing a fox clearing that is not adjacent to any mob raises IllegalActionError."""
        from game.transactions.rats.birdsong import choose_mob_clearing

        # C8 is fox but not adjacent to C9 or C11 (C9 ↔ C1,C4,C12; C11 ↔ C3,C6,C12)
        c8 = Clearing.objects.get(game=self.game, clearing_number=8)
        with self.assertRaises(IllegalActionError):
            choose_mob_clearing(self.player, c8)


# ===========================================================================
# recruit()
# ===========================================================================


class RecruitTests(RatsBirdsongBaseTestCase):

    def test_recruit_places_prowess_value_warriors_at_warlord_clearing(self):
        """recruit() places prowess_value warriors in the warlord's clearing.

        pick_corner places both the warlord and the first stronghold in C2, so
        recruit also places 1 warrior there for the deployed stronghold.  The
        expected delta is prowess_value + 1 (stronghold in same clearing).
        """
        from game.transactions.rats.birdsong import recruit
        from game.queries.rats.birdsong import get_prowess_value

        warlord = Warlord.objects.get(player=self.player)
        self.assertIsNotNone(warlord.clearing, "Warlord must be on the map")
        warlord_clearing = warlord.clearing

        initial_at_warlord = Warrior.objects.filter(
            player=self.player,
            clearing=warlord_clearing,
            warlord__isnull=True,
        ).count()

        prowess = get_prowess_value(self.player)
        strongholds_in_warlord_clearing = Stronghold.objects.filter(
            player=self.player,
            building_slot__clearing=warlord_clearing,
        ).count()

        self._set_step(RatsBirdsong.Steps.RECRUIT)
        reset_rats_turn(self.player)
        recruit(self.player)

        final_at_warlord = Warrior.objects.filter(
            player=self.player,
            clearing=warlord_clearing,
            warlord__isnull=True,
        ).count()
        self.assertEqual(
            final_at_warlord,
            initial_at_warlord + prowess + strongholds_in_warlord_clearing,
        )

    def test_recruit_places_one_warrior_per_deployed_stronghold(self):
        """recruit() places 1 warrior in each clearing that has a deployed stronghold."""
        from game.transactions.rats.birdsong import recruit

        # Deploy a stronghold in C3 (different from warlord clearing C2)
        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        slot = BuildingSlot.objects.filter(clearing=c3).first()
        self.assertIsNotNone(slot)
        stronghold = Stronghold.objects.filter(
            player=self.player, building_slot__isnull=True
        ).first()
        self.assertIsNotNone(stronghold, "Need a stronghold in supply")
        stronghold.building_slot = slot
        stronghold.save()

        initial_at_c3 = Warrior.objects.filter(
            player=self.player, clearing=c3, warlord__isnull=True
        ).count()

        self._set_step(RatsBirdsong.Steps.RECRUIT)
        recruit(self.player)

        final_at_c3 = Warrior.objects.filter(
            player=self.player, clearing=c3, warlord__isnull=True
        ).count()
        self.assertEqual(final_at_c3, initial_at_c3 + 1)

    def test_recruit_advances_step_to_anoint(self):
        """After recruit, birdsong step should advance to ANOINT.

        Move the warlord off-map first so ANOINT doesn't auto-skip (the
        warlord-on-map auto-skip would cascade straight past ANOINT).
        """
        from game.transactions.rats.birdsong import recruit

        # Warlord off-map means step_effect(ANOINT) will block, waiting for player.
        warlord = Warlord.objects.get(player=self.player)
        warlord.clearing = None
        warlord.save()

        self._set_step(RatsBirdsong.Steps.RECRUIT)
        recruit(self.player)

        self.birdsong.refresh_from_db()
        self.assertEqual(self.birdsong.step, RatsBirdsong.Steps.ANOINT)

    def test_recruit_with_warlord_off_map_skips_warlord_clearing(self):
        """If warlord is off-map, prowess warriors are NOT placed (no warlord clearing)."""
        from game.transactions.rats.birdsong import recruit

        # Remove warlord from map
        warlord = Warlord.objects.get(player=self.player)
        warlord_clearing = warlord.clearing
        warlord.clearing = None
        warlord.save()

        # Also retract the stronghold from C2 so recruit has nothing to place there,
        # making it easy to assert the old warlord clearing is untouched.
        stronghold = Stronghold.objects.filter(
            player=self.player,
            building_slot__clearing=warlord_clearing,
        ).first()
        if stronghold:
            stronghold.building_slot = None
            stronghold.save()

        initial_at_old_clearing = Warrior.objects.filter(
            player=self.player,
            clearing=warlord_clearing,
            warlord__isnull=True,
        ).count()

        self._set_step(RatsBirdsong.Steps.RECRUIT)
        recruit(self.player)

        # Warriors should NOT have been added to the old warlord clearing
        final_at_old_clearing = Warrior.objects.filter(
            player=self.player,
            clearing=warlord_clearing,
            warlord__isnull=True,
        ).count()
        self.assertEqual(final_at_old_clearing, initial_at_old_clearing)


# ===========================================================================
# anoint()
# ===========================================================================


class AnointTests(RatsBirdsongBaseTestCase):

    def _send_warlord_to_supply(self) -> Warlord:
        """Remove the warlord from the map (simulate being off-map)."""
        warlord = Warlord.objects.get(player=self.player)
        warlord.clearing = None
        warlord.save()
        return warlord

    def test_anoint_removes_warrior_and_places_warlord_when_warriors_on_board(self):
        """When warlord is off-map and a warrior is in the chosen clearing, consume
        the warrior and place the warlord there."""
        from game.transactions.rats.birdsong import anoint

        self._send_warlord_to_supply()

        # Place a warrior in C5 (rabbit)
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        self._warrior_in_clearing(c5)

        warriors_before = Warrior.objects.filter(
            player=self.player, clearing=c5, warlord__isnull=True
        ).count()

        self._set_step(RatsBirdsong.Steps.ANOINT)
        anoint(self.player, c5)

        warriors_after = Warrior.objects.filter(
            player=self.player, clearing=c5, warlord__isnull=True
        ).count()
        self.assertEqual(
            warriors_after,
            warriors_before - 1,
            "One warrior should be consumed to anoint the Warlord",
        )

        warlord = Warlord.objects.get(player=self.player)
        self.assertEqual(warlord.clearing, c5)

    def test_anoint_places_warlord_directly_when_no_warriors_on_board(self):
        """When warlord is off-map and no warriors exist on the board, place warlord directly."""
        from game.transactions.rats.birdsong import anoint

        self._send_warlord_to_supply()

        # Remove all warriors from the map
        Warrior.objects.filter(
            player=self.player, clearing__isnull=False, warlord__isnull=True
        ).update(clearing=None)

        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        self._set_step(RatsBirdsong.Steps.ANOINT)
        anoint(self.player, c3)

        warlord = Warlord.objects.get(player=self.player)
        self.assertEqual(warlord.clearing, c3)

    def test_anoint_advances_step(self):
        """After anoint, the birdsong step should advance past ANOINT."""
        from game.transactions.rats.birdsong import anoint

        self._send_warlord_to_supply()

        # Remove warriors from map so no warrior-in-clearing check fires
        Warrior.objects.filter(
            player=self.player, clearing__isnull=False, warlord__isnull=True
        ).update(clearing=None)

        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        self._set_step(RatsBirdsong.Steps.ANOINT)
        anoint(self.player, c3)

        self.birdsong.refresh_from_db()
        self.assertNotEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.ANOINT,
            "Step should advance after anoint",
        )

    def test_anoint_raises_when_warlord_already_on_map(self):
        """Calling anoint while warlord is already on map raises UnavailableActionError."""
        from game.transactions.rats.birdsong import anoint

        # Warlord is on map after setup
        warlord = Warlord.objects.get(player=self.player)
        self.assertIsNotNone(warlord.clearing)

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        self._set_step(RatsBirdsong.Steps.ANOINT)

        with self.assertRaises(UnavailableActionError):
            anoint(self.player, c5)

    def test_anoint_raises_when_no_warrior_in_chosen_clearing_but_warriors_exist(self):
        """When warriors are on the board but the chosen clearing has none, raise IllegalActionError."""
        from game.transactions.rats.birdsong import anoint

        self._send_warlord_to_supply()

        # Warriors exist on board in C2; choose an empty clearing (C3)
        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        Warrior.objects.filter(
            player=self.player, clearing=c3, warlord__isnull=True
        ).update(clearing=None)

        # Ensure at least one warrior is on the board somewhere else
        c2 = Clearing.objects.get(game=self.game, clearing_number=2)
        self.assertTrue(
            Warrior.objects.filter(
                player=self.player, clearing=c2, warlord__isnull=True
            ).exists()
        )

        self._set_step(RatsBirdsong.Steps.ANOINT)

        with self.assertRaises(IllegalActionError):
            anoint(self.player, c3)


# ===========================================================================
# choose_mood()
# ===========================================================================


class ChooseMoodTests(RatsBirdsongBaseTestCase):

    def test_valid_mood_updates_current_mood(self):
        """Choosing a valid mood updates the RatsPlayerState record."""
        from game.transactions.rats.birdsong import choose_mood

        self._set_step(RatsBirdsong.Steps.CHOOSE_MOOD)

        # Default mood is STUBBORN. JUBILANT (blocked by BOOTS) is available
        # when no BOOTS are in the hoard.
        target_mood = RatsPlayerState.MoodType.JUBILANT
        choose_mood(self.player, target_mood)

        mood = RatsPlayerState.objects.get(player=self.player)
        self.assertEqual(mood.mood_type, target_mood)

    def test_choosing_current_mood_raises_error(self):
        """Choosing the currently active mood raises an error."""
        from game.transactions.rats.birdsong import choose_mood

        self._set_step(RatsBirdsong.Steps.CHOOSE_MOOD)

        current = RatsPlayerState.objects.get(player=self.player)
        current_type = RatsPlayerState.MoodType(current.mood_type)

        with self.assertRaises((IllegalActionError, UnavailableActionError)):
            choose_mood(self.player, current_type)

    def test_choosing_mood_blocked_by_hoard_item_raises_error(self):
        """Choosing a mood whose linked item is in the hoard raises an error."""
        from game.transactions.rats.birdsong import choose_mood

        self._set_step(RatsBirdsong.Steps.CHOOSE_MOOD)

        # JUBILANT is blocked by BOOTS — add boots to hoard
        boots = Item.objects.create(game=self.game, item_type=ItemTypes.BOOTS)
        CommandItemEntry.objects.create(player=self.player, item=boots)

        with self.assertRaises((IllegalActionError, UnavailableActionError)):
            choose_mood(self.player, RatsPlayerState.MoodType.JUBILANT)

    def test_choose_mood_advances_step(self):
        """After choosing a valid mood, birdsong step advances past CHOOSE_MOOD."""
        from game.transactions.rats.birdsong import choose_mood

        self._set_step(RatsBirdsong.Steps.CHOOSE_MOOD)

        # JUBILANT is valid (no BOOTS in hoard yet) and not the current mood
        choose_mood(self.player, RatsPlayerState.MoodType.JUBILANT)

        self.birdsong.refresh_from_db()
        self.assertNotEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.CHOOSE_MOOD,
            "Step should advance after mood chosen",
        )

    def test_lavish_is_always_available(self):
        """LAVISH mood has no blocking item and is always choosable (when not current mood)."""
        from game.transactions.rats.birdsong import choose_mood

        self._set_step(RatsBirdsong.Steps.CHOOSE_MOOD)

        # Set current mood to something other than LAVISH
        mood = RatsPlayerState.objects.get(player=self.player)
        mood.mood_type = RatsPlayerState.MoodType.STUBBORN
        mood.save()

        # Fill hoard with every item type to block all mood-linked items
        for item_type in [
            ItemTypes.HAMMER,
            ItemTypes.TEA,
            ItemTypes.BOOTS,
            ItemTypes.BAG,
            ItemTypes.COIN,
            ItemTypes.CROSSBOW,
            ItemTypes.SWORD,
        ]:
            item = Item.objects.create(game=self.game, item_type=item_type)
            CommandItemEntry.objects.create(player=self.player, item=item)

        # LAVISH should still be choosable
        choose_mood(self.player, RatsPlayerState.MoodType.LAVISH)

        mood.refresh_from_db()
        self.assertEqual(mood.mood_type, RatsPlayerState.MoodType.LAVISH)
