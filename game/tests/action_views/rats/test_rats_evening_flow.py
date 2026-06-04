"""Integration tests for Rats Evening action views.

Tests cover:
  - RatsEveningInciteView  (/api/rats/evening/incite/)
  - RatsEveningDiscardView (/api/rats/evening/discard/)

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
4. RatsTurn.create_turn(player), then mark birdsong and daylight COMPLETED so
   get_phase() resolves to evening. Set evening.step = INCITE.
"""

from django.test import TestCase

from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.enums import Suit
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Card, Clearing, Faction, Game, HandEntry, Warrior
from game.models.rats.tokens import Mob
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsEvening, RatsTurn
from game.tests.client import RootGameClient
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


class RatsEveningInciteBaseTestCase(TestCase):
    """Creates a RATS + CATS game at the INCITE step of Evening."""

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

        # Create a turn; mark birdsong and daylight COMPLETED so get_phase() returns evening.
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

        # Set up HTTP client for the rats player.
        self.player.user.set_password("password")
        self.player.user.save()
        self.rats_client = RootGameClient(
            self.player.user.username, "password", self.game.id
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_card_to_hand(self, card_enum: CardsEP) -> HandEntry:
        """Create a card of the given type and add it to the player's hand."""
        card = Card.objects.create(game=self.game, card_type=card_enum.name)
        return HandEntry.objects.create(player=self.player, card=card)

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

    def _mob_in_clearing(self, clearing: Clearing) -> Mob:
        """Place one mob token from supply into *clearing*."""
        mob = Mob.objects.filter(player=self.player, clearing__isnull=True).first()
        self.assertIsNotNone(mob, "No mobs left in supply")
        mob.clearing = clearing
        mob.save()
        return mob


# ===========================================================================
# Incite view tests
# ===========================================================================


class RatsEveningInciteFlowTestCase(RatsEveningInciteBaseTestCase):
    """Tests for /api/rats/evening/incite/ (RatsEveningInciteView)."""

    def setUp(self):
        super().setUp()
        # Clear the 3 cards dealt during setup so tests start with a known empty hand.
        HandEntry.objects.filter(player=self.player).delete()

    def test_get_action_routes_to_incite(self):
        """get_action() should resolve to the incite route when step is INCITE."""
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/evening/incite/",
        )

    def test_get_returns_eligible_clearings(self):
        """GET should include clearings where player has a warrior but no mob.

        C1 (fox) gets a warrior → should appear.
        C6 (fox) has no warrior → must not appear.
        Skip option (value "") must always be present.
        """
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        self._warrior_in_clearing(c1)

        response = self.rats_client.get_action()
        data = response.json()

        self.assertIn("options", data)
        option_values = {opt["value"] for opt in data["options"]}

        # C1 has a warrior and no mob — should be eligible.
        self.assertIn(1, option_values)

        # C6 has no warrior — must not appear.
        self.assertNotIn(6, option_values)

        # Skip must always be present.
        self.assertIn("", option_values)

    def test_get_excludes_clearing_already_having_mob(self):
        """GET must not list a clearing that already has a Mob, even if it has a warrior."""
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        self._warrior_in_clearing(c1)
        self._mob_in_clearing(c1)

        response = self.rats_client.get_action()
        data = response.json()

        option_values = {opt["value"] for opt in data["options"]}
        self.assertNotIn(1, option_values)
        # Skip is still present.
        self.assertIn("", option_values)

    def test_get_no_mob_in_supply_returns_only_skip(self):
        """If all Mobs are placed (none in supply), GET should return only the Skip option."""
        # Place a warrior in C1 so it would normally be eligible.
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        self._warrior_in_clearing(c1)

        # Deplete the entire mob supply into various clearings.
        clearings = list(Clearing.objects.filter(game=self.game))
        for idx, mob in enumerate(
            Mob.objects.filter(player=self.player, clearing__isnull=True)
        ):
            mob.clearing = clearings[idx % len(clearings)]
            mob.save()

        response = self.rats_client.get_action()
        data = response.json()

        option_values = [opt["value"] for opt in data["options"]]
        self.assertEqual(
            option_values,
            [""],
            "Only Skip should be available when no mobs remain in supply",
        )

    def test_post_skip_advances_step(self):
        """POSTing clearing_number='' should advance step past INCITE."""
        self.rats_client.get_action()
        response = self.rats_client.submit_action({"clearing_number": ""})
        self.assertEqual(response.status_code, 200)

        self.evening.refresh_from_db()
        self.assertNotEqual(
            self.evening.step,
            RatsEvening.Steps.INCITE,
            "Evening step should have advanced past INCITE after Skip",
        )

    def test_post_clearing_returns_card_options(self):
        """POSTing a valid clearing_number should return a select_card step.

        The card options must include hand cards that match the clearing's suit.
        """
        # Place warrior in C1 (fox) and add a fox-suit card.
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        self._warrior_in_clearing(c1)
        self._add_card_to_hand(CardsEP.INFORMANTS)  # suit = RED/fox

        self.rats_client.get_action()
        response = self.rats_client.submit_action({"clearing_number": "1"})
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data.get("name"), "select_card")
        self.assertIn("options", data)
        card_option_values = {opt["value"] for opt in data["options"]}
        self.assertIn(CardsEP.INFORMANTS.name, card_option_values)

    def test_post_clearing_excludes_wrong_suit_cards(self):
        """Card options must not include cards whose suit does not match the clearing."""
        # C1 is fox; add only an orange-suit card — it should not appear.
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        self._warrior_in_clearing(c1)
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)  # suit = ORANGE, not fox

        self.rats_client.get_action()
        # No matching card → expect a 400 response from the view.
        response = self.rats_client.post_action({"clearing_number": "1"})
        self.assertEqual(
            response.status_code,
            400,
            "View should reject a clearing with no matching cards in hand",
        )

    def test_post_card_places_mob(self):
        """Completing the full clearing → card flow should place a Mob in the clearing."""
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        self._warrior_in_clearing(c1)
        self._add_card_to_hand(CardsEP.INFORMANTS)

        mob_count_before = Mob.objects.filter(player=self.player, clearing__isnull=False).count()

        # Step 1: GET, then POST clearing.
        self.rats_client.get_action()
        self.rats_client.submit_action({"clearing_number": "1"})

        # Step 2: POST card.
        response = self.rats_client.submit_action({"card": CardsEP.INFORMANTS.name})
        self.assertEqual(response.status_code, 200)

        self.assertTrue(
            Mob.objects.filter(player=self.player, clearing=c1).exists(),
            "A Mob should have been placed in clearing 1",
        )
        mob_count_after = Mob.objects.filter(player=self.player, clearing__isnull=False).count()
        self.assertEqual(mob_count_after, mob_count_before + 1)

    def test_post_card_discards_card(self):
        """After completing the incite flow, the spent card should no longer be in hand."""
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        self._warrior_in_clearing(c1)
        hand_entry = self._add_card_to_hand(CardsEP.INFORMANTS)

        self.rats_client.get_action()
        self.rats_client.submit_action({"clearing_number": "1"})
        self.rats_client.submit_action({"card": CardsEP.INFORMANTS.name})

        self.assertFalse(
            HandEntry.objects.filter(player=self.player, card=hand_entry.card).exists(),
            "The spent card should have been discarded from hand",
        )

    def test_warlord_clearing_is_eligible(self):
        """The warlord's clearing (C2, orange) should appear as an eligible incite target.

        The warlord was placed in C2 by pick_corner; no warrior or mob helper
        is needed — the warlord itself satisfies the Hundreds warrior requirement.
        """
        # Give the player an orange-suit card to match C2.
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)

        response = self.rats_client.get_action()
        data = response.json()
        option_values = {opt["value"] for opt in data["options"]}

        self.assertIn(
            2,
            option_values,
            "C2 (warlord's clearing) should be eligible for incite",
        )


# ===========================================================================
# Discard view tests
# ===========================================================================


class RatsEveningDiscardFlowTestCase(RatsEveningInciteBaseTestCase):
    """Tests for /api/rats/evening/discard/ (RatsEveningDiscardView)."""

    def setUp(self):
        super().setUp()
        # Switch evening step to DISCARD.
        self.evening.step = RatsEvening.Steps.DISCARD
        self.evening.save()
        # Start with a known hand: clear setup cards, then add 6 controlled cards.
        HandEntry.objects.filter(player=self.player).delete()
        for _ in range(6):
            self._add_card_to_hand(CardsEP.INFORMANTS)

    def test_get_action_routes_to_discard(self):
        """get_action() should resolve to the discard route when step is DISCARD."""
        self.rats_client.get_action()
        self.assertEqual(self.rats_client.base_route, "/api/rats/evening/discard/")

    def test_get_returns_card_options(self):
        """GET should list all cards in hand as options."""
        response = self.rats_client.get_action()
        data = response.json()

        self.assertIn("options", data)
        # 6 cards in hand → 6 options
        self.assertEqual(len(data["options"]), 6)

    def test_get_prompt_reflects_excess(self):
        """GET prompt should state how many cards need to be discarded (6 - 5 = 1)."""
        response = self.rats_client.get_action()
        data = response.json()
        self.assertIn("1", data["prompt"])

    def test_post_discard_one_of_six_stays_in_discard(self):
        """Discarding one card when hand=6 → hand=5, returns completed (transaction auto-advances)."""
        response = self.rats_client.get_action()
        options = response.json()["options"]
        entry_id = options[0]["value"]

        response = self.rats_client.submit_action({"card": entry_id})
        self.assertEqual(response.status_code, 200)

        hand_size = HandEntry.objects.filter(player=self.player).count()
        self.assertEqual(hand_size, 5)

    def test_post_discard_advances_step_when_hand_reaches_five(self):
        """After discarding down to 5, step should have advanced past DISCARD."""
        response = self.rats_client.get_action()
        options = response.json()["options"]
        entry_id = options[0]["value"]

        self.rats_client.submit_action({"card": entry_id})

        self.evening.refresh_from_db()
        self.assertNotEqual(
            self.evening.step,
            RatsEvening.Steps.DISCARD,
            "Step should have advanced past DISCARD once hand reached 5",
        )

    def test_post_discard_two_of_seven_stays_in_discard(self):
        """With hand=7, first discard → hand=6 → still needs one more, second → completed."""
        # Add a 7th card.
        self._add_card_to_hand(CardsEP.INFORMANTS)
        self.assertEqual(HandEntry.objects.filter(player=self.player).count(), 7)

        # First discard: expect another select_card step (still 6 cards).
        response = self.rats_client.get_action()
        options = response.json()["options"]
        first_id = options[0]["value"]

        response = self.rats_client.submit_action({"card": first_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(HandEntry.objects.filter(player=self.player).count(), 6)
        # Still in discard step, another card prompt returned
        self.assertEqual(response.json()["name"], "select_card")

        # Second discard: expect completed.
        options = response.json()["options"]
        second_id = options[0]["value"]
        response = self.rats_client.submit_action({"card": second_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(HandEntry.objects.filter(player=self.player).count(), 5)

    def test_post_invalid_entry_id_returns_400(self):
        """Submitting a non-existent HandEntry id returns 400."""
        self.rats_client.get_action()
        # Manually post a bad id directly.
        response = self.rats_client.post_action({"card_entry_id": "999999"})
        self.assertEqual(response.status_code, 400)
