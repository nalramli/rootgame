"""Integration tests for Rats Daylight Advance action views.

Tests cover:
  - RatsDaylightAdvanceView  (/api/rats/daylight/advance/)
  - RatsAdvanceMoveView      (/api/rats/daylight/advance/move/)
  - RatsAdvanceBattleView    (/api/rats/daylight/advance/battle/)

Map reference (Autumn map, 1-indexed)
--------------------------------------
Fox (r):    1, 6, 8, 12
Rabbit (y): 3, 4, 5, 10
Mouse (o):  2, 7, 9, 11

Setup approach
--------------
1. GameSetupFactory(factions=[RATS, CATS])
2. Force game_setup.status = RATS_SETUP, pick corner 2 (mouse/orange), confirm.
3. Force game.current_turn to rats turn_order, status = SETUP_COMPLETED.
4. RatsTurn.create_turn(player), manually complete birdsong, set daylight step to ADVANCE.

After pick_corner(player, c2):
  - Warlord placed at C2 (mouse)
  - 4 warriors at C2
  - 1 Stronghold placed in C2's building slot

C2 adjacencies: C5 (rabbit), C6 (fox), C10 (rabbit)

Prowess value with 0 items on the track: _TRACK_VALUES[0] = 1 (one advance cycle per turn).
"""

from django.test import TestCase

from game.models.enums import Faction
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing, Game, Warrior
from game.models.rats.player import RatsPlayerState
from game.models.rats.tokens import Warlord
from game.models.rats.turn import RatsAdvance, RatsBirdsong, RatsDaylight, RatsTurn
from game.tests.client import RootGameClient
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ===========================================================================
# Shared base
# ===========================================================================


class RatsDaylightAdvanceBaseTestCase(TestCase):
    """Creates a RATS + CATS game, completes setup, and positions daylight at ADVANCE."""

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

        # Point game.current_turn at rats player and mark setup complete.
        self.game.refresh_from_db()
        self.game.current_turn = self.player.turn_order
        self.game.status = Game.GameStatus.SETUP_COMPLETED
        self.game.save()

        # Set up authenticated client for the rats player.
        self.player.user.set_password("password")
        self.player.user.save()
        self.rats_client = RootGameClient(
            self.player.user.username, "password", self.game.id
        )

        # Create turn with birdsong completed and daylight at ADVANCE.
        self.rats_turn = RatsTurn.create_turn(self.player)
        birdsong = self.rats_turn.birdsong.first()
        birdsong.step = RatsBirdsong.Steps.COMPLETED
        birdsong.save()
        daylight = self.rats_turn.daylight.first()
        daylight.step = RatsDaylight.Steps.ADVANCE
        daylight.save()
        self.daylight = daylight
        self.advance = daylight.advance
        self.warlord = Warlord.objects.get(player=self.player)
        # Warlord is already at C2 from rats_pick_corner.


# ===========================================================================
# Class 1 — Routing tests (MOVE sub-step is the default)
# ===========================================================================


class RatsDaylightAdvanceRoutingTestCase(RatsDaylightAdvanceBaseTestCase):
    """Tests for /api/rats/daylight/advance/ at the MOVE sub-step."""

    def test_advance_get_routes_to_advance(self):
        """get_action() should resolve to the advance route."""
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/daylight/advance/",
        )

    def test_advance_get_shows_move_options(self):
        """GET response must include 'move', 'skip_move', and 'end' options."""
        response = self.rats_client.get_action()
        data = response.json()
        self.assertIn("options", data)
        option_values = {opt["value"] for opt in data["options"]}
        self.assertIn("move", option_values)
        self.assertIn("skip_move", option_values)
        self.assertIn("end", option_values)

    def test_advance_end_advances_step(self):
        """POST action='end' should advance the daylight step past ADVANCE."""
        self.rats_client.get_action()
        # Manually set step to match the advance view's 'select' endpoint.
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        response = self.rats_client.post_action({"action": "end"})
        self.assertEqual(response.status_code, 200)

        self.daylight.refresh_from_db()
        self.assertNotEqual(
            self.daylight.step,
            RatsDaylight.Steps.ADVANCE,
            "Daylight step should have advanced past ADVANCE after end",
        )

    def test_advance_skip_move_to_battle_substep(self):
        """POST action='skip_move' should move advance.current_step to BATTLE."""
        self.rats_client.get_action()
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        response = self.rats_client.post_action({"action": "skip_move"})
        self.assertEqual(response.status_code, 200)

        self.advance.refresh_from_db()
        self.assertEqual(
            self.advance.current_step,
            RatsAdvance.AdvanceStep.BATTLE,
            "advance.current_step should be BATTLE after skip_move",
        )

    def test_advance_move_redirect(self):
        """POST action='move' should redirect to the advance-move sub-view."""
        self.rats_client.get_action()
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        response = self.rats_client.post_action({"action": "move"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/daylight/advance/move/",
        )

    def test_advance_battle_redirect_after_skip_move(self):
        """Skip move first (to reach BATTLE sub-step), then POST action='battle' → redirect.

        A Cat warrior must be present in C2 so the advance-battle GET succeeds
        when the client follows the redirect.
        """
        # Place a Cat warrior in C2 so validate_enemy_pieces_in_clearing passes.
        cat_warrior = Warrior.objects.filter(
            player=self.cats_player, clearing__isnull=True
        ).first()
        self.assertIsNotNone(cat_warrior, "Need at least one Cat warrior in supply")
        cat_warrior.clearing = self.c2
        cat_warrior.save()

        # First skip the move to advance to BATTLE sub-step.
        self.rats_client.get_action()
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        self.rats_client.post_action({"action": "skip_move"})

        # Now we should be at the advance view again but in BATTLE sub-step.
        self.rats_client.get_action()
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        response = self.rats_client.post_action({"action": "battle"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/daylight/advance/battle/",
        )


# ===========================================================================
# Class 2 — Advance Move full flow
# ===========================================================================


class RatsDaylightAdvanceMoveFlowTestCase(RatsDaylightAdvanceBaseTestCase):
    """Tests for /api/rats/daylight/advance/move/ full flow."""

    def test_advance_move_full_flow(self):
        """GET advance-move → POST destination C5 → POST count=0 → Warlord in C5, advance at BATTLE."""
        # C5 is adjacent to C2 (rabbit clearing).
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)

        self.rats_client.get_action()

        # Select 'move' to redirect to the advance-move sub-view.
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        response = self.rats_client.post_action({"action": "move"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rats_client.base_route, "/api/rats/daylight/advance/move/")

        # POST destination C5.
        response = self.rats_client.submit_action({"clearing_number": 5})
        self.assertEqual(response.status_code, 200)

        # POST count=0 (Warlord moves alone).
        response = self.rats_client.submit_action({"number": 0})
        self.assertEqual(response.status_code, 200)

        # Warlord should now be in C5.
        self.warlord.refresh_from_db()
        self.assertEqual(
            self.warlord.clearing,
            c5,
            "Warlord should have moved to C5",
        )

        # advance.current_step should now be BATTLE.
        self.advance.refresh_from_db()
        self.assertEqual(
            self.advance.current_step,
            RatsAdvance.AdvanceStep.BATTLE,
            "advance.current_step should be BATTLE after move",
        )


# ===========================================================================
# Class 3 — Advance Battle flow (skip move first to reach BATTLE sub-step)
# ===========================================================================


class RatsDaylightAdvanceBattleFlowTestCase(RatsDaylightAdvanceBaseTestCase):
    """Tests for /api/rats/daylight/advance/battle/ — requires enemies in Warlord's clearing."""

    def _place_cat_warrior_in_c2(self) -> Warrior:
        """Place one Cat warrior from supply into C2 (Warlord's clearing)."""
        w = Warrior.objects.filter(
            player=self.cats_player, clearing__isnull=True
        ).first()
        self.assertIsNotNone(w, "No Cat warriors left in supply")
        w.clearing = self.c2
        w.save()
        return w

    def _skip_move_to_battle_substep(self):
        """Helper: skip the move sub-step so advance reaches BATTLE."""
        self.rats_client.get_action()
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        self.rats_client.post_action({"action": "skip_move"})

    def test_advance_battle_get_shows_factions(self):
        """After placing a Cat warrior in C2, GET advance-battle shows CATS as an option."""
        self._place_cat_warrior_in_c2()
        self._skip_move_to_battle_substep()

        # Navigate to the battle sub-view.
        self.rats_client.get_action()
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        response = self.rats_client.post_action({"action": "battle"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rats_client.base_route, "/api/rats/daylight/advance/battle/")

        data = response.json()
        self.assertIn("options", data)
        option_values = {opt["value"] for opt in data["options"]}
        self.assertIn(
            Faction.CATS.value,
            option_values,
            "CATS should appear as a battle target in C2",
        )

    def test_advance_battle_full_flow(self):
        """Place Cat warrior in C2, skip move, POST faction=CATS → battle starts."""
        self._place_cat_warrior_in_c2()
        self._skip_move_to_battle_substep()

        # Navigate to the battle sub-view.
        self.rats_client.get_action()
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        response = self.rats_client.post_action({"action": "battle"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rats_client.base_route, "/api/rats/daylight/advance/battle/")

        # POST defender faction = CATS.
        response = self.rats_client.submit_action({"faction": Faction.CATS.value})
        self.assertEqual(response.status_code, 200)

        # After a successful battle submission the advance cycle should complete
        # (prowess_used reaches prowess_value=1 with 0 items on track).
        self.advance.refresh_from_db()
        self.daylight.refresh_from_db()
        # Either the advance cycled (reset back to MOVE and prowess_used incremented)
        # or the daylight step advanced past ADVANCE (if prowess was exhausted).
        advance_cycled = self.advance.current_step == RatsAdvance.AdvanceStep.MOVE
        step_advanced = self.daylight.step != RatsDaylight.Steps.ADVANCE
        self.assertTrue(
            advance_cycled or step_advanced,
            "After battle: advance should have cycled or daylight should have advanced past ADVANCE",
        )
