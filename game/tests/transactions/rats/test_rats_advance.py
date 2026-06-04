"""Tests for the Rats ADVANCE step transactions.

Transaction functions covered:
  advance_move          — move Warlord (+ optional warriors) to adjacent clearing
  advance_move_skip     — skip the move sub-step
  advance_battle        — battle in the Warlord's clearing
  advance_battle_skip   — skip the battle sub-step
  advance_relentless_skip — skip the Relentless bonus sub-step

Each advance cycle:
  MOVE  →  BATTLE  →  (RELENTLESS_BONUS if mood=RELENTLESS and both used)  →  cycle done

Auto-advance: when prowess_used == prowess_value (1 at 0 items), daylight advances
past the ADVANCE step.

Map reference (Autumn map, 1-indexed):
  Fox  (r): 1, 6, 8, 12
  Rabbit (y): 3, 4, 5, 10
  Mouse (o): 2, 7, 9, 11

Corner C2 (mouse/orange) is where warlord starts after pick_corner.
  C2  ↔ C5, C6, C10
  C5  ↔ C1, C2
  C3  is NOT adjacent to C2
"""

from django.test import TestCase

from game.errors import IllegalActionError, UnavailableActionError
from game.models.enums import Faction
from game.models.events.battle import Battle
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing, Game, Warrior
from game.models.rats.player import RatsPlayerState
from game.models.rats.tokens import Warlord
from game.models.rats.turn import RatsAdvance, RatsBirdsong, RatsDaylight, RatsTurn
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------


class RatsAdvanceBaseTestCase(TestCase):
    """Creates a RATS + CATS game at the ADVANCE step of Daylight."""

    def setUp(self):
        self.game = GameSetupFactory(factions=[Faction.RATS, Faction.CATS])
        self.player = self.game.players.get(faction=Faction.RATS)
        self.cats_player = self.game.players.get(faction=Faction.CATS)

        # Complete rats setup: force status, pick corner C2 (mouse/orange), confirm.
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
        self.daylight = self.rats_turn.daylight.first()
        self.daylight.step = RatsDaylight.Steps.ADVANCE
        self.daylight.save()

        self.warlord = Warlord.objects.get(player=self.player)
        self.advance = self.daylight.advance

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _place_warrior(self, clearing: Clearing, player=None) -> Warrior:
        """Move one supply warrior for *player* (default: self.player) into *clearing*."""
        if player is None:
            player = self.player
        w = Warrior.objects.filter(player=player, clearing__isnull=True).first()
        self.assertIsNotNone(w, "No warriors left in supply")
        w.clearing = clearing
        w.save()
        return w

    def _set_mood(self, mood_type: RatsPlayerState.MoodType) -> None:
        """Set the current mood for the Rats player, creating the record if needed."""
        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": mood_type},
        )

    def _exhaust_prowess(self) -> None:
        """Exhaust the prowess budget so no advance actions remain (1 at 0 items)."""
        self.daylight.prowess_used = 1
        self.daylight.save()


# ===========================================================================
# advance_move tests
# ===========================================================================


class RatsAdvanceMoveTests(RatsAdvanceBaseTestCase):
    """Tests for advance_move()."""

    def test_warlord_moves_to_destination(self):
        """Warlord's clearing changes to destination after advance_move."""
        from game.transactions.rats.daylight import advance_move

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)

        advance_move(self.player, c5, 0)

        self.warlord.refresh_from_db()
        self.assertEqual(self.warlord.clearing, c5, "Warlord should be in C5 after move")

    def test_additional_warriors_move(self):
        """With count=2, two additional warriors also move from C2 to C5."""
        from game.transactions.rats.daylight import advance_move

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)

        # Ensure two warriors are in C2 (setup places some there already; top up if needed).
        initial_c2_warriors = Warrior.objects.filter(
            player=self.player, clearing=self.c2
        ).exclude(warlord__isnull=False).count()
        while initial_c2_warriors < 2:
            self._place_warrior(self.c2)
            initial_c2_warriors += 1

        before_c5 = Warrior.objects.filter(player=self.player, clearing=c5).count()

        advance_move(self.player, c5, 2)

        after_c5 = Warrior.objects.filter(player=self.player, clearing=c5).count()
        # +1 for warlord, +2 for extra warriors
        self.assertEqual(after_c5, before_c5 + 3, "Warlord + 2 warriors should be in C5")

    def test_move_used_set_true(self):
        """advance.move_used is True after advance_move."""
        from game.transactions.rats.daylight import advance_move

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)

        advance_move(self.player, c5, 0)

        # advance_move transitions sub-step to BATTLE but move_used was set to True
        # before the possible RELENTLESS path; re-fetch to confirm.
        self.advance.refresh_from_db()
        self.assertTrue(self.advance.move_used, "move_used should be True after advance_move")

    def test_sub_step_advances_to_battle(self):
        """After advance_move from the MOVE sub-step, current_step == BATTLE."""
        from game.transactions.rats.daylight import advance_move

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        advance_move(self.player, c5, 0)

        self.advance.refresh_from_db()
        self.assertEqual(
            self.advance.current_step,
            RatsAdvance.AdvanceStep.BATTLE,
            "current_step should be BATTLE after advance_move",
        )

    def test_wrong_sub_step_raises(self):
        """UnavailableActionError if advance_move is called during BATTLE sub-step."""
        from game.transactions.rats.daylight import advance_move

        self.advance.current_step = RatsAdvance.AdvanceStep.BATTLE
        self.advance.save()

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        with self.assertRaises(UnavailableActionError):
            advance_move(self.player, c5, 0)

    def test_non_adjacent_raises(self):
        """IllegalActionError if destination is not adjacent to the Warlord's clearing.

        C3 is not adjacent to C2 (C2 ↔ C5, C6, C10 only).
        """
        from game.transactions.rats.daylight import advance_move

        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        with self.assertRaises(IllegalActionError):
            advance_move(self.player, c3, 0)

    def test_no_prowess_raises(self):
        """UnavailableActionError if the prowess budget is exhausted."""
        from game.transactions.rats.daylight import advance_move

        self._exhaust_prowess()

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        with self.assertRaises(UnavailableActionError):
            advance_move(self.player, c5, 0)

    def test_warlord_not_deployed_raises(self):
        """IllegalActionError if the Warlord is not on the map."""
        from game.transactions.rats.daylight import advance_move

        self.warlord.clearing = None
        self.warlord.save()

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        with self.assertRaises(IllegalActionError):
            advance_move(self.player, c5, 0)


# ===========================================================================
# advance_move_skip tests
# ===========================================================================


class RatsAdvanceMoveSkipTests(RatsAdvanceBaseTestCase):
    """Tests for advance_move_skip()."""

    def test_move_used_stays_false(self):
        """advance.move_used remains False after skipping the move sub-step."""
        from game.transactions.rats.daylight import advance_move_skip

        advance_move_skip(self.player)

        self.advance.refresh_from_db()
        self.assertFalse(
            self.advance.move_used,
            "move_used should remain False after advance_move_skip",
        )

    def test_sub_step_advances_to_battle(self):
        """After advance_move_skip, current_step == BATTLE."""
        from game.transactions.rats.daylight import advance_move_skip

        advance_move_skip(self.player)

        self.advance.refresh_from_db()
        self.assertEqual(
            self.advance.current_step,
            RatsAdvance.AdvanceStep.BATTLE,
            "current_step should be BATTLE after advance_move_skip",
        )

    def test_wrong_sub_step_raises(self):
        """UnavailableActionError if advance_move_skip is called during BATTLE sub-step."""
        from game.transactions.rats.daylight import advance_move_skip

        self.advance.current_step = RatsAdvance.AdvanceStep.BATTLE
        self.advance.save()

        with self.assertRaises(UnavailableActionError):
            advance_move_skip(self.player)

    def test_relentless_bonus_sub_step_raises(self):
        """UnavailableActionError if advance_move_skip is called during RELENTLESS_BONUS."""
        from game.transactions.rats.daylight import advance_move_skip

        self.advance.current_step = RatsAdvance.AdvanceStep.RELENTLESS_BONUS
        self.advance.save()

        with self.assertRaises(UnavailableActionError):
            advance_move_skip(self.player)


# ===========================================================================
# advance_battle tests
# ===========================================================================


class RatsAdvanceBattleTests(RatsAdvanceBaseTestCase):
    """Tests for advance_battle()."""

    def setUp(self):
        super().setUp()
        # Move advance tracker to BATTLE sub-step (normal state after a move).
        self.advance.current_step = RatsAdvance.AdvanceStep.BATTLE
        self.advance.move_used = True
        self.advance.save()

        # Place a Cats warrior in C2 (where the Warlord starts) to act as defender.
        self._place_warrior(self.c2, player=self.cats_player)

    def test_battle_created(self):
        """A Battle object is created after calling advance_battle."""
        from game.transactions.rats.daylight import advance_battle

        initial_battles = Battle.objects.filter(event__game=self.game).count()

        advance_battle(self.player, Faction.CATS)

        final_battles = Battle.objects.filter(event__game=self.game).count()
        self.assertEqual(
            final_battles,
            initial_battles + 1,
            "A new Battle should be created after advance_battle",
        )

    def test_battle_used_set_true(self):
        """advance.battle_used is True after advance_battle (before cycle completes)."""
        from game.transactions.rats.daylight import advance_battle

        # Use RELENTLESS mood so the cycle doesn't reset (RELENTLESS_BONUS is awarded),
        # letting us inspect battle_used before the record is reset.
        self._set_mood(RatsPlayerState.MoodType.RELENTLESS)

        advance_battle(self.player, Faction.CATS)

        self.advance.refresh_from_db()
        self.assertTrue(
            self.advance.battle_used,
            "battle_used should be True after advance_battle (in RELENTLESS_BONUS state)",
        )

    def test_non_relentless_mood_completes_cycle(self):
        """After advance_battle with non-relentless mood, prowess_used increments (cycle done)."""
        from game.transactions.rats.daylight import advance_battle

        self._set_mood(RatsPlayerState.MoodType.ROWDY)

        initial_prowess_used = self.daylight.prowess_used
        advance_battle(self.player, Faction.CATS)

        self.daylight.refresh_from_db()
        self.assertEqual(
            self.daylight.prowess_used,
            initial_prowess_used + 1,
            "prowess_used should increment after cycle completes (non-relentless mood)",
        )

    def test_relentless_mood_with_both_used_gives_bonus(self):
        """RELENTLESS mood + move_used=True → current_step becomes RELENTLESS_BONUS."""
        from game.transactions.rats.daylight import advance_battle

        self._set_mood(RatsPlayerState.MoodType.RELENTLESS)
        # move_used was already set to True in setUp.

        advance_battle(self.player, Faction.CATS)

        self.advance.refresh_from_db()
        self.assertEqual(
            self.advance.current_step,
            RatsAdvance.AdvanceStep.RELENTLESS_BONUS,
            "current_step should be RELENTLESS_BONUS when both move and battle were used",
        )

    def test_relentless_mood_without_move_completes(self):
        """RELENTLESS mood but move_used=False → no bonus, cycle completes normally."""
        from game.transactions.rats.daylight import advance_battle

        self._set_mood(RatsPlayerState.MoodType.RELENTLESS)
        # Override move_used back to False for this test.
        self.advance.move_used = False
        self.advance.save()

        initial_prowess_used = self.daylight.prowess_used
        advance_battle(self.player, Faction.CATS)

        self.daylight.refresh_from_db()
        self.assertEqual(
            self.daylight.prowess_used,
            initial_prowess_used + 1,
            "prowess_used should increment (no bonus when move was skipped)",
        )

    def test_wrong_sub_step_raises(self):
        """UnavailableActionError if advance_battle is called during MOVE sub-step."""
        from game.transactions.rats.daylight import advance_battle

        self.advance.current_step = RatsAdvance.AdvanceStep.MOVE
        self.advance.save()

        with self.assertRaises(UnavailableActionError):
            advance_battle(self.player, Faction.CATS)

    def test_no_prowess_raises(self):
        """UnavailableActionError if the prowess budget is exhausted."""
        from game.transactions.rats.daylight import advance_battle

        self._exhaust_prowess()

        with self.assertRaises(UnavailableActionError):
            advance_battle(self.player, Faction.CATS)

    def test_warlord_not_deployed_raises(self):
        """IllegalActionError if the Warlord is not on the map."""
        from game.transactions.rats.daylight import advance_battle

        self.warlord.clearing = None
        self.warlord.save()

        with self.assertRaises(IllegalActionError):
            advance_battle(self.player, Faction.CATS)


# ===========================================================================
# advance_battle_skip tests
# ===========================================================================


class RatsAdvanceBattleSkipTests(RatsAdvanceBaseTestCase):
    """Tests for advance_battle_skip()."""

    def setUp(self):
        super().setUp()
        # Start at BATTLE sub-step.
        self.advance.current_step = RatsAdvance.AdvanceStep.BATTLE
        self.advance.save()

    def test_battle_used_stays_false(self):
        """advance.battle_used remains False after skipping the battle sub-step."""
        from game.transactions.rats.daylight import advance_battle_skip

        advance_battle_skip(self.player)

        # After skip, cycle completes and advance.reset() is called, so battle_used
        # will be False either way.  Confirm it was never set to True.
        self.advance.refresh_from_db()
        self.assertFalse(
            self.advance.battle_used,
            "battle_used should be False after advance_battle_skip",
        )

    def test_cycle_completes(self):
        """prowess_used increments after skipping the battle sub-step."""
        from game.transactions.rats.daylight import advance_battle_skip

        initial_prowess_used = self.daylight.prowess_used
        advance_battle_skip(self.player)

        self.daylight.refresh_from_db()
        self.assertEqual(
            self.daylight.prowess_used,
            initial_prowess_used + 1,
            "prowess_used should increment after battle skip (cycle complete)",
        )

    def test_wrong_sub_step_raises(self):
        """UnavailableActionError if advance_battle_skip is called during MOVE sub-step."""
        from game.transactions.rats.daylight import advance_battle_skip

        self.advance.current_step = RatsAdvance.AdvanceStep.MOVE
        self.advance.save()

        with self.assertRaises(UnavailableActionError):
            advance_battle_skip(self.player)


# ===========================================================================
# advance_relentless_skip tests
# ===========================================================================


class RatsAdvanceRelentlessSkipTests(RatsAdvanceBaseTestCase):
    """Tests for advance_relentless_skip()."""

    def setUp(self):
        super().setUp()
        # Place tracker at RELENTLESS_BONUS sub-step.
        self.advance.current_step = RatsAdvance.AdvanceStep.RELENTLESS_BONUS
        self.advance.move_used = True
        self.advance.battle_used = True
        self.advance.save()

    def test_cycle_completes(self):
        """prowess_used increments after skipping the Relentless bonus."""
        from game.transactions.rats.daylight import advance_relentless_skip

        initial_prowess_used = self.daylight.prowess_used
        advance_relentless_skip(self.player)

        self.daylight.refresh_from_db()
        self.assertEqual(
            self.daylight.prowess_used,
            initial_prowess_used + 1,
            "prowess_used should increment after relentless_skip (cycle complete)",
        )

    def test_wrong_sub_step_raises(self):
        """UnavailableActionError if advance_relentless_skip is called during MOVE sub-step."""
        from game.transactions.rats.daylight import advance_relentless_skip

        self.advance.current_step = RatsAdvance.AdvanceStep.MOVE
        self.advance.save()

        with self.assertRaises(UnavailableActionError):
            advance_relentless_skip(self.player)


# ===========================================================================
# Auto-advance tests
# ===========================================================================


class RatsAdvanceAutoAdvanceTests(RatsAdvanceBaseTestCase):
    """Tests for automatic step advancement once all prowess cycles are used."""

    def test_step_advances_after_last_prowess(self):
        """Daylight step advances past ADVANCE after one full cycle (prowess_value=1).

        With 0 prowess items, prowess_value == 1.  Completing one cycle
        (advance_move then advance_battle_skip) should exhaust the budget and
        auto-advance daylight.step past ADVANCE.
        """
        from game.transactions.rats.daylight import advance_battle_skip, advance_move

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)

        # First half of cycle: move.
        advance_move(self.player, c5, 0)

        # Second half: skip battle → cycle complete → prowess_used == prowess_value.
        advance_battle_skip(self.player)

        self.daylight.refresh_from_db()
        self.assertNotEqual(
            self.daylight.step,
            RatsDaylight.Steps.ADVANCE,
            "Daylight step should advance past ADVANCE after the last prowess cycle",
        )
