"""Integration tests for Rats Birdsong action views.

Tests cover:
  - RatsBirdsongSpreadMobView  (/api/rats/birdsong/spread-mob/)
  - RatsBirdsongChooseMoodView (/api/rats/birdsong/choose-mood/)

Map reference (Autumn map, 1-indexed)
--------------------------------------
Fox (r):    1, 6, 8, 12
Rabbit (y): 3, 4, 5, 10
Mouse (o):  2, 7, 9, 11

Key adjacencies used here:
  C9  (mouse) ↔ C1(fox), C4(rabbit), C12(fox)
  C11 (mouse) ↔ C3(rabbit), C6(fox), C12(fox)
  → Mobs at C9 + C11 with RED (fox) die: targets C1, C6, C12 (multiple).

Setup approach
--------------
1. GameSetupFactory(factions=[RATS, CATS])
2. Force game_setup.status = RATS_SETUP, pick corner 2, confirm.
3. Force game.current_turn to rats turn_order, status = SETUP_COMPLETED.
4. RatsTurn.create_turn(player) then manually set birdsong.step.
"""

from django.test import TestCase

from game.models.enums import Suit
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing, Faction, Game
from game.models.rats.player import RatsPlayerState
from game.models.rats.tokens import Mob, Warlord
from game.models.rats.turn import RatsBirdsong, RatsTurn
from game.tests.client import RootGameClient
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


class RatsBirdsongBaseTestCase(TestCase):
    """Creates a RATS + CATS game and completes setup so RatsTurn can be created."""

    def setUp(self):
        self.game = GameSetupFactory(factions=[Faction.RATS, Faction.CATS])
        self.player = self.game.players.get(faction=Faction.RATS)
        self.cats_player = self.game.players.get(faction=Faction.CATS)

        # Complete rats setup: force status, pick corner 2 (mouse/orange), confirm.
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

        # Set up client for the rats player.
        self.player.user.set_password("password")
        self.player.user.save()
        self.rats_client = RootGameClient(
            self.player.user.username, "password", self.game.id
        )

    def _mob_in_clearing(self, clearing: Clearing) -> Mob:
        """Place one mob token from supply into *clearing*."""
        mob = Mob.objects.filter(player=self.player, clearing__isnull=True).first()
        self.assertIsNotNone(mob, "No mobs left in supply")
        mob.clearing = clearing
        mob.save()
        return mob


# ===========================================================================
# SpreadMob view tests
# ===========================================================================


class RatsBirdsongSpreadMobFlowTestCase(RatsBirdsongBaseTestCase):
    """Tests for /api/rats/birdsong/spread-mob/ (RatsBirdsongSpreadMobView).

    Scenario: mobs at C9 + C11, die rolled RED (fox).
    Adjacent fox clearings: C1, C6, C12 — three targets, so player must choose.
    """

    def setUp(self):
        super().setUp()

        # Create a turn and set birdsong to SPREAD_MOB.
        self.rats_turn = RatsTurn.create_turn(self.player)
        self.birdsong = self.rats_turn.birdsong.first()
        self.birdsong.step = RatsBirdsong.Steps.SPREAD_MOB

        # Place mobs at C9 and C11 so there are multiple RED (fox) adjacent targets.
        c9 = Clearing.objects.get(game=self.game, clearing_number=9)
        c11 = Clearing.objects.get(game=self.game, clearing_number=11)
        self._mob_in_clearing(c9)
        self._mob_in_clearing(c11)

        # Set mob_die_suit to RED (fox): targets will be C1, C6, C12.
        self.birdsong.mob_die_suit = Suit.RED
        self.birdsong.save()

    def test_get_action_routes_to_spread_mob(self):
        """get_action() should resolve to the spread-mob route."""
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/birdsong/spread-mob/",
        )

    def test_get_returns_valid_clearing_options(self):
        """GET response should list the fox clearings adjacent to the mobs."""
        response = self.rats_client.get_action()
        data = response.json()

        self.assertIn("options", data)
        # Values are integers (preserved by _PassThroughField)
        option_values = {opt["value"] for opt in data["options"]}
        # C1, C6, C12 are fox clearings adjacent to C9/C11 and not already holding a mob.
        self.assertIn(1, option_values)
        self.assertIn(6, option_values)
        self.assertIn(12, option_values)
        # C9 and C11 already have mobs — must not appear as targets.
        self.assertNotIn(9, option_values)
        self.assertNotIn(11, option_values)

    def test_post_valid_clearing_places_mob(self):
        """Submitting a valid clearing should place a mob there."""
        self.rats_client.get_action()
        mob_count_before = Mob.objects.filter(player=self.player, clearing__isnull=False).count()

        response = self.rats_client.submit_action({"clearing_number": 1})
        self.assertEqual(response.status_code, 200)

        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        self.assertTrue(
            Mob.objects.filter(player=self.player, clearing=c1).exists(),
            "A mob should have been placed in clearing 1",
        )
        mob_count_after = Mob.objects.filter(player=self.player, clearing__isnull=False).count()
        self.assertEqual(mob_count_after, mob_count_before + 1)

    def test_post_valid_clearing_advances_step(self):
        """After choosing a clearing, birdsong step should advance past SPREAD_MOB."""
        self.rats_client.get_action()
        self.rats_client.submit_action({"clearing_number": 6})

        self.birdsong.refresh_from_db()
        self.assertNotEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.SPREAD_MOB,
            "Birdsong step should have advanced past SPREAD_MOB",
        )
        self.assertIsNone(
            self.birdsong.mob_die_suit,
            "mob_die_suit should be cleared after placement",
        )


# ===========================================================================
# ChooseMood view tests
# ===========================================================================


class RatsBirdsongChooseMoodFlowTestCase(RatsBirdsongBaseTestCase):
    """Tests for /api/rats/birdsong/choose-mood/ (RatsBirdsongChooseMoodView).

    Starting mood is STUBBORN (set by create_rats_mood during setup).
    With an empty hoard, all 7 other moods should be available.
    """

    def setUp(self):
        super().setUp()

        # Create a turn and set birdsong to CHOOSE_MOOD.
        self.rats_turn = RatsTurn.create_turn(self.player)
        self.birdsong = self.rats_turn.birdsong.first()
        self.birdsong.step = RatsBirdsong.Steps.CHOOSE_MOOD
        self.birdsong.save()

    def test_get_action_routes_to_choose_mood(self):
        """get_action() should resolve to the choose-mood route."""
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/birdsong/choose-mood/",
        )

    def test_get_returns_all_moods_except_current(self):
        """GET response should list all moods except the current one (STUBBORN)."""
        response = self.rats_client.get_action()
        data = response.json()

        self.assertIn("options", data)
        option_values = {opt["value"] for opt in data["options"]}

        # STUBBORN is the current mood — must not appear.
        self.assertNotIn(RatsPlayerState.MoodType.STUBBORN, option_values)
        # All other moods should be present (hoard is empty so none are blocked).
        expected_moods = {
            RatsPlayerState.MoodType.BITTER,
            RatsPlayerState.MoodType.GRANDIOSE,
            RatsPlayerState.MoodType.JUBILANT,
            RatsPlayerState.MoodType.LAVISH,
            RatsPlayerState.MoodType.RELENTLESS,
            RatsPlayerState.MoodType.ROWDY,
            RatsPlayerState.MoodType.WRATHFUL,
        }
        self.assertEqual(option_values, expected_moods)

    def test_post_valid_mood_updates_current_mood(self):
        """Submitting a valid mood should update the player's RatsPlayerState record."""
        self.rats_client.get_action()
        response = self.rats_client.submit_action({"mood": RatsPlayerState.MoodType.GRANDIOSE})
        self.assertEqual(response.status_code, 200)

        mood = RatsPlayerState.objects.get(player=self.player)
        self.assertEqual(mood.mood_type, RatsPlayerState.MoodType.GRANDIOSE)

    def test_post_valid_mood_advances_step(self):
        """After choosing a mood, birdsong step should advance past CHOOSE_MOOD."""
        self.rats_client.get_action()
        self.rats_client.submit_action({"mood": RatsPlayerState.MoodType.ROWDY})

        self.birdsong.refresh_from_db()
        self.assertNotEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.CHOOSE_MOOD,
            "Birdsong step should have advanced past CHOOSE_MOOD",
        )

    def test_post_current_mood_is_rejected(self):
        """Submitting the current mood (STUBBORN) should return a 400 error."""
        self.rats_client.get_action()
        # Use post_action directly to bypass submit_action's payload_details mapping
        # and send the disallowed value directly.
        self.rats_client.step = {
            "endpoint": "mood",
            "payload_details": [{"type": "mood", "name": "mood_type"}],
        }
        response = self.rats_client.post_action(
            {"mood_type": RatsPlayerState.MoodType.STUBBORN}
        )
        self.assertEqual(response.status_code, 400)
