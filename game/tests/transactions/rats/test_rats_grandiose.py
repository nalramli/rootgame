"""Tests for the Rats GRANDIOSE mood mechanic.

Grandiose (tea): perform Advance the Warlord *before* Command the Hundreds.

Normal Daylight order:  CRAFT → COMMAND → ADVANCE → BEFORE_END
Grandiose order:        CRAFT → ADVANCE → COMMAND → BEFORE_END

Scenarios covered:

next_step / _next_daylight_step:
- CRAFT → ADVANCE  (not COMMAND) when GRANDIOSE
- ADVANCE → COMMAND  (not BEFORE_END) when GRANDIOSE
- COMMAND → BEFORE_END  (not ADVANCE) when GRANDIOSE
- Normal order is preserved for non-GRANDIOSE moods

Integration via end_crafting / end_advance / end_command:
- end_crafting while GRANDIOSE → step becomes ADVANCE
- end_advance while GRANDIOSE → step becomes COMMAND
- end_command while GRANDIOSE → step becomes BEFORE_END (turn proceeds)

step_effect is called after each next_step so the new step is entered
correctly (ADVANCE and COMMAND are passthrough steps that just wait for
player input — no auto-advance side effect to worry about).
"""

from django.test import TestCase

from game.models.enums import Faction
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing, Game
from game.models.rats.player import RatsPlayerState
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsTurn
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------


class RatsGrandioseBaseTestCase(TestCase):
    """Game at CRAFT step of Daylight with the Rats in GRANDIOSE mood."""

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
        self.daylight = self.rats_turn.daylight.first()
        self.daylight.step = RatsDaylight.Steps.CRAFT
        self.daylight.save()

        # Default: GRANDIOSE mood
        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": RatsPlayerState.MoodType.GRANDIOSE},
        )

    def _set_mood(self, mood_type) -> None:
        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": mood_type},
        )

    def _set_step(self, step) -> None:
        self.daylight.step = step
        self.daylight.save()


# ===========================================================================
# Unit tests for _next_daylight_step routing
# ===========================================================================


class NextDaylightStepGrandioseTests(RatsGrandioseBaseTestCase):
    """Verify _next_daylight_step returns the right value for each step."""

    def _call(self, step: str) -> str:
        from game.transactions.rats.turn import _next_daylight_step
        return _next_daylight_step(self.player, step)

    def test_craft_goes_to_advance(self):
        self.assertEqual(self._call(RatsDaylight.Steps.CRAFT), RatsDaylight.Steps.ADVANCE)

    def test_advance_goes_to_command(self):
        self.assertEqual(self._call(RatsDaylight.Steps.ADVANCE), RatsDaylight.Steps.COMMAND)

    def test_command_goes_to_before_end(self):
        self.assertEqual(self._call(RatsDaylight.Steps.COMMAND), RatsDaylight.Steps.BEFORE_END)

    def test_not_started_unaffected(self):
        """NOT_STARTED still advances normally (to CRAFT)."""
        self.assertEqual(
            self._call(RatsDaylight.Steps.NOT_STARTED), RatsDaylight.Steps.CRAFT
        )

    def test_before_end_unaffected(self):
        """BEFORE_END still advances to COMPLETED regardless of mood."""
        self.assertEqual(
            self._call(RatsDaylight.Steps.BEFORE_END), RatsDaylight.Steps.COMPLETED
        )


class NextDaylightStepNormalMoodTests(RatsGrandioseBaseTestCase):
    """With a non-GRANDIOSE mood, step order must be the standard enum order."""

    def setUp(self):
        super().setUp()
        self._set_mood(RatsPlayerState.MoodType.STUBBORN)

    def _call(self, step: str) -> str:
        from game.transactions.rats.turn import _next_daylight_step
        return _next_daylight_step(self.player, step)

    def test_craft_goes_to_command(self):
        self.assertEqual(self._call(RatsDaylight.Steps.CRAFT), RatsDaylight.Steps.COMMAND)

    def test_command_goes_to_advance(self):
        self.assertEqual(self._call(RatsDaylight.Steps.COMMAND), RatsDaylight.Steps.ADVANCE)

    def test_advance_goes_to_before_end(self):
        self.assertEqual(self._call(RatsDaylight.Steps.ADVANCE), RatsDaylight.Steps.BEFORE_END)


# ===========================================================================
# Integration tests via end_crafting / end_advance / end_command
# ===========================================================================


class GrandioseIntegrationTests(RatsGrandioseBaseTestCase):

    def test_end_crafting_goes_to_advance(self):
        """end_crafting while GRANDIOSE should move step to ADVANCE."""
        from game.transactions.rats.daylight import end_crafting

        end_crafting(self.player)

        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.step, RatsDaylight.Steps.ADVANCE)

    def test_end_advance_goes_to_command(self):
        """end_advance while GRANDIOSE should move step to COMMAND."""
        from game.transactions.rats.daylight import end_advance

        self._set_step(RatsDaylight.Steps.ADVANCE)
        end_advance(self.player)

        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.step, RatsDaylight.Steps.COMMAND)

    def test_end_command_goes_to_before_end_then_completes(self):
        """end_command while GRANDIOSE: next_step sets BEFORE_END, step_effect
        immediately advances to COMPLETED, so step ends up as COMPLETED."""
        from game.transactions.rats.daylight import end_command

        self._set_step(RatsDaylight.Steps.COMMAND)
        end_command(self.player)

        self.daylight.refresh_from_db()
        # BEFORE_END has no pause — step_effect advances straight to COMPLETED
        self.assertEqual(self.daylight.step, RatsDaylight.Steps.COMPLETED)

    def test_full_grandiose_day_order(self):
        """Simulate a full Grandiose day: CRAFT → ADVANCE → COMMAND → done."""
        from game.transactions.rats.daylight import end_crafting, end_advance, end_command

        # Start at CRAFT
        self.assertEqual(self.daylight.step, RatsDaylight.Steps.CRAFT)

        # End crafting → should land on ADVANCE
        end_crafting(self.player)
        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.step, RatsDaylight.Steps.ADVANCE)

        # End advance → should land on COMMAND
        end_advance(self.player)
        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.step, RatsDaylight.Steps.COMMAND)

        # End command → BEFORE_END → COMPLETED (step_effect fires)
        end_command(self.player)
        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.step, RatsDaylight.Steps.COMPLETED)

    def test_normal_mood_full_day_order(self):
        """With a normal mood, the step order is CRAFT → COMMAND → ADVANCE → done."""
        from game.transactions.rats.daylight import end_crafting, end_advance, end_command

        self._set_mood(RatsPlayerState.MoodType.STUBBORN)

        # Start at CRAFT
        end_crafting(self.player)
        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.step, RatsDaylight.Steps.COMMAND)

        end_command(self.player)
        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.step, RatsDaylight.Steps.ADVANCE)

        end_advance(self.player)
        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.step, RatsDaylight.Steps.COMPLETED)
