"""Integration tests for RatsJubilantMobSpreadView (/api/rats/events/jubilant-mob-spread/).

Jubilant mood: after Incite in the Warlord's clearing, the player may roll the mob die
up to 4 times and place mobs in matching clearings adjacent to existing mobs.

Map reference (Autumn map, 1-indexed):
  Fox (r):    1, 6, 8, 12
  Rabbit (y): 3, 4, 5, 10
  Mouse (o):  2, 7, 9, 11

  C2 (mouse) — Warlord setup corner
  C2 ↔ C5 (rabbit), C6 (fox), C10 (rabbit)
  C6 ↔ C2 (mouse), C3 (rabbit), C11 (mouse)
  C10 ↔ C1 (fox), C2 (mouse), C12 (fox)
"""

from unittest.mock import patch

from django.test import TestCase

from game.models.enums import Suit
from game.models.events.event import EventType
from game.models.events.rats import JubilantMobSpreadEvent
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing, Faction, Game, Warrior
from game.models.rats.player import RatsPlayerState
from game.models.rats.tokens import Mob, Warlord
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsTurn
from game.tests.client import RootGameClient
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------


class RatsJubilantFlowBaseTestCase(TestCase):
    """RATS + CATS game at COMMAND step with Jubilant mood and an active
    JubilantMobSpreadEvent."""

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
        daylight.step = RatsBirdsong.Steps.COMPLETED
        daylight.save()

        self.warlord = Warlord.objects.get(player=self.player)

        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": RatsPlayerState.MoodType.JUBILANT},
        )

        # Create a JubilantMobSpreadEvent with 4 rolls remaining
        self.evt = JubilantMobSpreadEvent.create(self.player)

        self.player.user.set_password("password")
        self.player.user.save()
        self.rats_client = RootGameClient(
            self.player.user.username, "password", self.game.id
        )

    def _place_mob(self, clearing: Clearing) -> Mob:
        mob = Mob.objects.filter(player=self.player, clearing__isnull=True).first()
        self.assertIsNotNone(mob, "No mobs in supply")
        mob.clearing = clearing
        mob.save()
        return mob

    def _clearing(self, n: int) -> Clearing:
        return Clearing.objects.get(game=self.game, clearing_number=n)

    def _set_rolls_remaining(self, n: int):
        self.evt.rolls_remaining = n
        self.evt.save()

    def _set_current_roll(self, suit: Suit | None):
        self.evt.current_roll = suit
        self.evt.save()


# ===========================================================================
# Routing
# ===========================================================================


class JubilantFlowRoutingTests(RatsJubilantFlowBaseTestCase):

    def test_get_action_routes_to_jubilant_mob_spread(self):
        """get_action() should resolve to jubilant-mob-spread when event is active."""
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/events/jubilant-mob-spread/",
        )


# ===========================================================================
# GET behaviour
# ===========================================================================


class JubilantFlowGetTests(RatsJubilantFlowBaseTestCase):

    def test_get_roll_or_end_when_no_pending_roll(self):
        """GET returns roll/end options when current_roll is None."""
        response = self.rats_client.get_action()
        data = response.json()

        self.assertIn("options", data)
        option_values = {opt["value"] for opt in data["options"]}
        self.assertIn("roll", option_values)
        self.assertIn("end", option_values)

    def test_get_includes_rolls_remaining_in_prompt(self):
        """GET prompt mentions how many rolls remain."""
        response = self.rats_client.get_action()
        data = response.json()
        self.assertIn("4", data["prompt"])

    def test_get_clearing_picker_when_roll_pending(self):
        """GET returns clearing options when current_roll is set."""
        self._place_mob(self.c2)
        c5 = self._clearing(5)
        c10 = self._clearing(10)
        self._set_current_roll(Suit.YELLOW)

        with patch(
            "game.views.action_views.rats.events.get_mob_spread_targets",
            return_value={c5, c10},
        ):
            response = self.rats_client.get_action()

        data = response.json()
        self.assertIn("options", data)
        option_values = {opt["value"] for opt in data["options"]}
        self.assertIn("5", option_values)
        self.assertIn("10", option_values)


# ===========================================================================
# POST roll
# ===========================================================================


class JubilantFlowRollTests(RatsJubilantFlowBaseTestCase):

    def test_post_end_resolves_event(self):
        """Posting action=end should resolve the event."""
        self.rats_client.get_action()
        self.rats_client.submit_action({"action": "end"})

        self.evt.event.refresh_from_db()
        self.assertTrue(self.evt.event.is_resolved)

    def test_post_end_returns_completed_step(self):
        """Posting end returns a completed_step response."""
        self.rats_client.get_action()
        response = self.rats_client.submit_action({"action": "end"})
        data = response.json()
        self.assertEqual(data.get("name"), "completed")

    def test_post_roll_with_no_targets_decrements_rolls(self):
        """Rolling with no valid targets decrements rolls_remaining."""
        self._place_mob(self.c2)
        self.rats_client.get_action()

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value=set(),
        ):
            self.rats_client.submit_action({"action": "roll"})

        self.evt.refresh_from_db()
        self.assertEqual(self.evt.rolls_remaining, 3)

    def test_post_roll_with_one_target_auto_places_mob(self):
        """Rolling with exactly one target auto-places a mob."""
        self._place_mob(self.c2)
        c6 = self._clearing(6)

        self.rats_client.get_action()
        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c6},
        ):
            self.rats_client.submit_action({"action": "roll"})

        self.assertTrue(Mob.objects.filter(player=self.player, clearing=c6).exists())

    def test_post_roll_with_multiple_targets_sets_pending_choice(self):
        """Rolling with multiple targets stores current_roll and re-renders clearing picker."""
        self._place_mob(self.c2)
        c5 = self._clearing(5)
        c10 = self._clearing(10)

        self.rats_client.get_action()

        with patch("game.transactions.rats.jubilant.random.choice", return_value=Suit.YELLOW):
            with patch(
                "game.transactions.rats.jubilant.get_mob_spread_targets",
                return_value={c5, c10},
            ):
                response = self.rats_client.submit_action({"action": "roll"})

        self.evt.refresh_from_db()
        self.assertEqual(self.evt.current_roll, Suit.YELLOW)

        data = response.json()
        option_values = {opt["value"] for opt in data.get("options", [])}
        self.assertIn("5", option_values)
        self.assertIn("10", option_values)

    def test_post_roll_last_roll_resolves_event(self):
        """After the last roll (with no targets), the event resolves."""
        self._place_mob(self.c2)
        self._set_rolls_remaining(1)

        self.rats_client.get_action()
        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value=set(),
        ):
            response = self.rats_client.submit_action({"action": "roll"})

        self.evt.event.refresh_from_db()
        self.assertTrue(self.evt.event.is_resolved)
        data = response.json()
        self.assertEqual(data.get("name"), "completed")


# ===========================================================================
# POST choose
# ===========================================================================


class JubilantFlowChooseTests(RatsJubilantFlowBaseTestCase):

    def test_post_choose_places_mob_in_clearing(self):
        """Choosing a clearing places a mob there."""
        self._place_mob(self.c2)
        c5 = self._clearing(5)
        c10 = self._clearing(10)
        self._set_current_roll(Suit.YELLOW)

        mobs_before = Mob.objects.filter(player=self.player, clearing__isnull=False).count()
        self.rats_client.get_action()

        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c5, c10},
        ):
            self.rats_client.submit_action({"clearing_number": "5"})

        mobs_after = Mob.objects.filter(player=self.player, clearing__isnull=False).count()
        self.assertEqual(mobs_after, mobs_before + 1)
        self.assertTrue(Mob.objects.filter(player=self.player, clearing=c5).exists())

    def test_post_choose_clears_pending_roll(self):
        """After a valid choice, current_roll is cleared."""
        self._place_mob(self.c2)
        c5 = self._clearing(5)
        c10 = self._clearing(10)
        self._set_current_roll(Suit.YELLOW)

        self.rats_client.get_action()
        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c5, c10},
        ):
            self.rats_client.submit_action({"clearing_number": "5"})

        self.evt.refresh_from_db()
        self.assertIsNone(self.evt.current_roll)

    def test_post_choose_last_roll_resolves_event(self):
        """Choosing on the last roll resolves the event."""
        self._place_mob(self.c2)
        c5 = self._clearing(5)
        self._set_current_roll(Suit.YELLOW)
        self._set_rolls_remaining(0)

        self.rats_client.get_action()
        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c5},
        ):
            response = self.rats_client.submit_action({"clearing_number": "5"})

        self.evt.event.refresh_from_db()
        self.assertTrue(self.evt.event.is_resolved)
        data = response.json()
        self.assertEqual(data.get("name"), "completed")

    def test_post_choose_with_rolls_remaining_continues(self):
        """Choosing with rolls remaining does not resolve the event."""
        self._place_mob(self.c2)
        c5 = self._clearing(5)
        c10 = self._clearing(10)
        self._set_current_roll(Suit.YELLOW)

        self.rats_client.get_action()
        with patch(
            "game.transactions.rats.jubilant.get_mob_spread_targets",
            return_value={c5, c10},
        ):
            response = self.rats_client.submit_action({"clearing_number": "5"})

        self.evt.event.refresh_from_db()
        self.assertFalse(self.evt.event.is_resolved)

        # Response should be roll_or_end step (not completed)
        data = response.json()
        self.assertNotEqual(data.get("name"), "completed")
