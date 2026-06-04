"""Integration tests for Rats Daylight action views.

Tests cover:
  - RatsDaylightCraftView  (/api/rats/daylight/craft/)
  - RatsDaylightCommandView (/api/rats/daylight/command/)
  - RatsCommandMoveView    (/api/rats/daylight/command/move/)
  - RatsCommandBuildView   (/api/rats/daylight/command/build/)

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
4. RatsTurn.create_turn(player), manually complete birdsong, set daylight step.

After pick_corner(player, c2):
  - Warlord placed at C2 (mouse)
  - 4 warriors at C2
  - 1 Stronghold placed in C2's building slot

C2 adjacencies: C5 (rabbit), C6 (fox), C10 (rabbit)
"""

from django.test import TestCase

from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.enums import Faction
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import (
    Building,
    BuildingSlot,
    Card,
    Clearing,
    Game,
    HandEntry,
    Warrior,
)
from game.models.rats.buildings import Stronghold
from game.models.rats.tokens import Warlord
from game.models.rats.player import RatsPlayerState
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsTurn
from game.tests.client import RootGameClient
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ===========================================================================
# Shared base
# ===========================================================================


class RatsDaylightBaseTestCase(TestCase):
    """Creates a RATS + CATS game and completes setup so a RatsTurn can be created."""

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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_card_to_hand(self, card_enum: CardsEP) -> HandEntry:
        """Create a card of the given type and put it in the player's hand."""
        card = Card.objects.create(game=self.game, card_type=card_enum.name)
        return HandEntry.objects.create(player=self.player, card=card)

    def _deploy_stronghold(self, clearing: Clearing) -> Stronghold:
        """Move one supply Stronghold onto *clearing* into an available slot."""
        occupied_slot_ids = Building.objects.filter(
            building_slot__clearing=clearing
        ).values_list("building_slot_id", flat=True)
        slot = (
            BuildingSlot.objects.filter(clearing=clearing)
            .exclude(id__in=occupied_slot_ids)
            .first()
        )
        self.assertIsNotNone(
            slot,
            f"No available building slot in clearing {clearing.clearing_number}",
        )
        sh = Stronghold.objects.filter(
            player=self.player, building_slot__isnull=True
        ).first()
        self.assertIsNotNone(sh, "No Strongholds left in supply")
        sh.building_slot = slot
        sh.save()
        return sh

    def _place_warrior(self, clearing: Clearing, player=None) -> Warrior:
        """Move one supply warrior for *player* (default: self.player) into *clearing*."""
        if player is None:
            player = self.player
        w = Warrior.objects.filter(player=player, clearing__isnull=True).first()
        self.assertIsNotNone(w, "No warriors left in supply")
        w.clearing = clearing
        w.save()
        return w

    def _create_turn_at_craft(self):
        """Create a RatsTurn with birdsong COMPLETED and daylight at CRAFT."""
        self.rats_turn = RatsTurn.create_turn(self.player)
        birdsong = self.rats_turn.birdsong.first()
        birdsong.step = RatsBirdsong.Steps.COMPLETED
        birdsong.save()
        self.daylight = self.rats_turn.daylight.first()
        self.daylight.step = RatsDaylight.Steps.CRAFT
        self.daylight.save()

    def _create_turn_at_command(self):
        """Create a RatsTurn with birdsong COMPLETED and daylight at COMMAND."""
        self.rats_turn = RatsTurn.create_turn(self.player)
        birdsong = self.rats_turn.birdsong.first()
        birdsong.step = RatsBirdsong.Steps.COMPLETED
        birdsong.save()
        self.daylight = self.rats_turn.daylight.first()
        self.daylight.step = RatsDaylight.Steps.COMMAND
        self.daylight.save()


# ===========================================================================
# Craft view tests
# ===========================================================================


class RatsDaylightCraftRoutingTestCase(RatsDaylightBaseTestCase):
    """Tests for /api/rats/daylight/craft/ — routing and Done path."""

    def setUp(self):
        super().setUp()
        self._create_turn_at_craft()

    def test_craft_get_routes_to_craft(self):
        """get_action() should resolve to the craft route."""
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/daylight/craft/",
        )

    def test_craft_done_advances_step(self):
        """Posting card_to_craft='' (Done) should advance the daylight step past CRAFT."""
        self.rats_client.get_action()
        response = self.rats_client.submit_action({"card": ""})
        self.assertEqual(response.status_code, 200)

        self.daylight.refresh_from_db()
        self.assertNotEqual(
            self.daylight.step,
            RatsDaylight.Steps.CRAFT,
            "Daylight step should have advanced past CRAFT after Done Crafting",
        )

    def test_craft_get_returns_done_option(self):
        """GET response must include the 'Done Crafting' option (value='')."""
        response = self.rats_client.get_action()
        data = response.json()
        self.assertIn("options", data)
        option_values = [opt["value"] for opt in data["options"]]
        self.assertIn("", option_values, "Done Crafting option must appear in options")


# ===========================================================================
# Craft — single-stronghold card test
# ===========================================================================


class RatsDaylightCraftSingleCardTestCase(RatsDaylightBaseTestCase):
    """Tests that a single-orange-cost card can be crafted using the C2 Stronghold."""

    def setUp(self):
        super().setUp()
        self._create_turn_at_craft()
        # Give the player a Mouse-in-a-Sack (cost: 1 orange/mouse) — crafted using C2 stronghold.
        self._add_card_to_hand(CardsEP.MOUSE_IN_A_SACK)
        # Ensure BAG is in the craftable pool.
        from game.models.game_models import CraftableItemEntry, Item
        from game.models.enums import ItemTypes
        if not CraftableItemEntry.objects.filter(
            game=self.game, item__item_type=ItemTypes.BAG.value
        ).exists():
            item = Item.objects.create(game=self.game, item_type=ItemTypes.BAG.value)
            CraftableItemEntry.objects.create(game=self.game, item=item)

    def test_craft_single_stronghold_card(self):
        """Crafting a 1-orange item card (MOUSE_IN_A_SACK) using the C2 stronghold should succeed.

        Flow: card → hoard_choice (add to hoard) → clearing.
        """
        # Verify the C2 stronghold is placed and not yet used.
        stronghold = Stronghold.objects.filter(
            player=self.player,
            building_slot__clearing=self.c2,
            crafted_with=False,
        ).first()
        self.assertIsNotNone(stronghold, "C2 Stronghold should exist and be unused")

        self.rats_client.get_action()

        # Step 1: pick the card — should now show hoard_choice (MOUSE_IN_A_SACK has item=BAG).
        response = self.rats_client.submit_action({"card": CardsEP.MOUSE_IN_A_SACK.name})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("name"), "hoard_choice", "Item card should show hoard_choice step")

        # Step 2: choose to add to hoard.
        response = self.rats_client.submit_action({"choice": True})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should now be at the clearing-selection step.
        self.assertIn("endpoint", data)
        self.assertEqual(data["endpoint"], "clearing")

        # Step 3: pick clearing 2 (the C2 orange stronghold).
        response = self.rats_client.submit_action({"clearing_number": 2})
        self.assertEqual(response.status_code, 200)

        # Card should be gone from hand.
        self.assertFalse(
            HandEntry.objects.filter(
                player=self.player, card__card_type=CardsEP.MOUSE_IN_A_SACK.name
            ).exists(),
            "Card should have been removed from hand after crafting",
        )

        # Stronghold should now be marked as crafted_with=True.
        stronghold.refresh_from_db()
        self.assertTrue(
            stronghold.crafted_with,
            "Stronghold should be marked crafted_with=True after use",
        )


# ===========================================================================
# Command view tests
# ===========================================================================


class RatsDaylightCommandRoutingTestCase(RatsDaylightBaseTestCase):
    """Tests for /api/rats/daylight/command/ — routing and Done path."""

    def setUp(self):
        super().setUp()
        self._create_turn_at_command()

    def test_command_get_routes_to_command(self):
        """get_action() should resolve to the command route."""
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/daylight/command/",
        )

    def test_command_done_advances_step(self):
        """Posting action='' (Done) should advance the daylight step past COMMAND."""
        self.rats_client.get_action()
        response = self.rats_client.submit_action({"action_type": ""})
        self.assertEqual(response.status_code, 200)

        self.daylight.refresh_from_db()
        self.assertNotEqual(
            self.daylight.step,
            RatsDaylight.Steps.COMMAND,
            "Daylight step should have advanced past COMMAND after Done",
        )

    def test_command_get_returns_expected_options(self):
        """GET response should include Move, Battle, Build, and Done options."""
        response = self.rats_client.get_action()
        data = response.json()
        self.assertIn("options", data)
        option_values = {opt["value"] for opt in data["options"]}
        self.assertIn("move", option_values)
        self.assertIn("battle", option_values)
        self.assertIn("build", option_values)
        self.assertIn("", option_values)  # Done


# ===========================================================================
# Command — Move redirect test
# ===========================================================================


class RatsDaylightCommandMoveTestCase(RatsDaylightBaseTestCase):
    """Tests for the Move sub-command path."""

    def setUp(self):
        super().setUp()
        self._create_turn_at_command()

    def test_command_move_redirect(self):
        """Posting action='move' should redirect to the move sub-view."""
        self.rats_client.get_action()
        # post_action sends the raw value without submit_action's payload mapping.
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        response = self.rats_client.post_action({"action": "move"})
        # post_action follows the redirect automatically and returns the GET of the new view.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/daylight/command/move/",
        )

    def test_command_move_full_flow(self):
        """A full Move from C2 → C5 (adjacent) should move warriors and complete."""
        # C2 already has 4 warriors from setup. C5 is adjacent to C2.
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        warriors_in_c2_before = Warrior.objects.filter(
            player=self.player, clearing=self.c2
        ).count()
        self.assertGreater(warriors_in_c2_before, 0, "C2 should have Rats warriors")

        self.rats_client.get_action()

        # Select move action.
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        response = self.rats_client.post_action({"action": "move"})
        self.assertEqual(response.status_code, 200)
        # Now at move sub-view — pick origin C2.
        response = self.rats_client.submit_action({"clearing_number": 2})
        self.assertEqual(response.status_code, 200)
        # Pick destination C5.
        response = self.rats_client.submit_action({"clearing_number": 5})
        self.assertEqual(response.status_code, 200)
        # Pick count = 1.
        response = self.rats_client.submit_action({"number": 1})
        self.assertEqual(response.status_code, 200)
        # Warlord is in C2 (the origin), so the interceptor asks whether to bring
        # the Warlord along. Choose False — leave the Warlord behind.
        response = self.rats_client.submit_action({"option": False})
        self.assertEqual(response.status_code, 200)

        # Warrior count should have shifted.
        warriors_in_c2_after = Warrior.objects.filter(
            player=self.player, clearing=self.c2
        ).count()
        warriors_in_c5_after = Warrior.objects.filter(
            player=self.player, clearing=c5
        ).count()
        self.assertEqual(warriors_in_c2_after, warriors_in_c2_before - 1)
        self.assertEqual(warriors_in_c5_after, 1)

        # commands_used should have incremented.
        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.commands_used, 1)


# ===========================================================================
# Command — Build redirect test
# ===========================================================================


class RatsDaylightCommandBuildTestCase(RatsDaylightBaseTestCase):
    """Tests for the Build sub-command path.

    Build requires:
      - A card in hand matching the suit of the target clearing.
      - Rats rule the clearing.
      - A free building slot in that clearing.
      - A Stronghold in supply.

    C2 (orange/mouse) already has a Stronghold from setup. We use a different
    clearing (C7, also orange/mouse) that the Rats may not rule yet. Instead, we
    deploy a warrior in C6 (fox) so Rats rule it (no other pieces), add a fox
    card to hand, and build there — C6 has free building slots and is adjacent
    to C2 for ruling purposes.

    Actually, simpler: after setup Rats rule C2. C2 already has one Stronghold
    which may consume the only building slot. Check if a free slot exists in C2;
    if not, use a clearing the Rats rule by placing a warrior (no other pieces).
    We'll use C5 (rabbit) — place a warrior there (Rats become ruler of C5 with
    no enemies), and spend a rabbit card to build.
    """

    def setUp(self):
        super().setUp()
        self._create_turn_at_command()

    def test_command_build_redirect(self):
        """Posting action='build' should redirect to the build sub-view."""
        self.rats_client.get_action()
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        response = self.rats_client.post_action({"action": "build"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/daylight/command/build/",
        )

    def test_command_build_full_flow(self):
        """Full Build: place a Stronghold in C5 (rabbit) using a rabbit card.

        Setup: place a Rats warrior in C5 so Rats rule it.
        Hand: add a rabbit-suit card to hand.
        Execute: build → select card → select clearing C5.
        """
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)

        # Place a Rats warrior in C5 so Rats rule it (no enemies, Rats have a piece).
        self._place_warrior(c5)

        # Add a rabbit (yellow) card to hand. RABBIT_PARTISANS is suit=YELLOW.
        # card_matches_clearing checks card.value.suit, not cost, so any yellow card works.
        self._add_card_to_hand(CardsEP.RABBIT_PARTISANS)

        strongholds_in_supply_before = Stronghold.objects.filter(
            player=self.player, building_slot__isnull=True
        ).count()
        self.assertGreater(strongholds_in_supply_before, 0, "Need Strongholds in supply")

        self.rats_client.get_action()

        # Select build action.
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        response = self.rats_client.post_action({"action": "build"})
        self.assertEqual(response.status_code, 200)

        # Now at build sub-view — pick card.
        response = self.rats_client.submit_action({"card": CardsEP.RABBIT_PARTISANS.name})
        self.assertEqual(response.status_code, 200)

        # Pick clearing C5.
        response = self.rats_client.submit_action({"clearing_number": 5})
        self.assertEqual(response.status_code, 200)

        # Stronghold should now be in C5.
        self.assertTrue(
            Stronghold.objects.filter(
                player=self.player, building_slot__clearing=c5
            ).exists(),
            "A Stronghold should have been placed in C5",
        )

        # Card should be gone from hand.
        self.assertFalse(
            HandEntry.objects.filter(
                player=self.player, card__card_type=CardsEP.RABBIT_PARTISANS.name
            ).exists(),
            "Card should have been discarded after building",
        )

        # commands_used should have incremented.
        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.commands_used, 1)


# ===========================================================================
# Craft — Contempt for Trade (hoard choice) tests
# ===========================================================================


class RatsDaylightCraftContemptForTradeTestCase(RatsDaylightBaseTestCase):
    """Tests for the Contempt for Trade hoard-vs-score choice in the craft flow.

    ROOT_TEA_ORANGE: orange suit, cost=[ORANGE], item=TEA → goes to prowess track.
    MOUSE_IN_A_SACK: orange suit, cost=[ORANGE], item=BAG → goes to command track.
    A non-item craftable card (MURINE_BROKERS) should skip the hoard-choice step.
    """

    def setUp(self):
        super().setUp()
        self._create_turn_at_craft()
        # Ensure the craftable pool has what we need.
        from game.models.game_models import CraftableItemEntry, Item
        from game.models.enums import ItemTypes

        def _ensure_pool(item_type):
            if not CraftableItemEntry.objects.filter(
                game=self.game, item__item_type=item_type.value
            ).exists():
                item = Item.objects.create(game=self.game, item_type=item_type.value)
                CraftableItemEntry.objects.create(game=self.game, item=item)

        _ensure_pool(ItemTypes.TEA)
        _ensure_pool(ItemTypes.BAG)

    def test_item_card_shows_hoard_choice_step(self):
        """Selecting an item card (ROOT_TEA_ORANGE) should show the hoard-choice step."""
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        self.rats_client.get_action()

        response = self.rats_client.submit_action({"card": CardsEP.ROOT_TEA_ORANGE.name})
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should be at hoard_choice step, not clearing selection yet.
        self.assertEqual(data.get("name"), "hoard_choice")
        self.assertIn("options", data)
        option_values = {opt["value"] for opt in data["options"]}
        self.assertIn(True, option_values)
        self.assertIn(False, option_values)

    def test_non_item_card_skips_hoard_choice(self):
        """Selecting a non-item card should go straight to clearing selection."""
        # MURINE_BROKERS is a non-item craftable card (suit=ORANGE, cost=[ORANGE]).
        self._add_card_to_hand(CardsEP.MURINE_BROKERS)
        self.rats_client.get_action()

        response = self.rats_client.submit_action({"card": CardsEP.MURINE_BROKERS.name})
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should jump straight to clearing selection.
        self.assertEqual(data.get("endpoint"), "clearing")

    def test_hoard_choice_add_to_hoard_places_item_on_track(self):
        """Full flow with add_to_hoard=true places item on prowess track (0 VP)."""
        from game.models.rats.player import ProwessItemEntry

        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        score_before = self.player.score
        self.rats_client.get_action()

        # Step 1: pick card → hoard choice step.
        self.rats_client.submit_action({"card": CardsEP.ROOT_TEA_ORANGE.name})
        # Step 2: choose hoard.
        self.rats_client.submit_action({"choice": True})
        # Step 3: pick clearing 2 (C2 has the orange stronghold).
        response = self.rats_client.submit_action({"clearing_number": 2})
        self.assertEqual(response.status_code, 200)

        # Item should be on prowess track.
        self.assertTrue(
            ProwessItemEntry.objects.filter(player=self.player).exists(),
            "Item should be on prowess track after hoard craft",
        )
        # No VP scored.
        self.player.refresh_from_db()
        self.assertEqual(
            self.player.score, score_before, "No VP scored when adding to hoard"
        )

    def test_hoard_choice_score_removes_item_and_scores_vp(self):
        """Full flow with add_to_hoard=false scores VP and permanently removes the item.

        Rule 14.2.3 — Contempt for Trade: the Hundreds may remove the item permanently
        to score the listed VP. The specific item consumed is deleted from the game; it
        does NOT appear in CraftedItemEntry and is NOT added to a hoard track.
        Note: the game starts with 2 Tea items in the pool, so 1 remains after crafting.
        """
        from game.models.enums import ItemTypes
        from game.models.game_models import CraftedItemEntry, Item
        from game.models.rats.player import ProwessItemEntry

        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        score_before = self.player.score

        # Capture which specific Tea item will be consumed by the craft.
        tea_item_id = Item.objects.filter(
            game=self.game, item_type=ItemTypes.TEA
        ).values_list("id", flat=True).first()
        tea_count_before = Item.objects.filter(game=self.game, item_type=ItemTypes.TEA).count()

        self.rats_client.get_action()

        # Step 1: pick card → hoard choice step.
        self.rats_client.submit_action({"card": CardsEP.ROOT_TEA_ORANGE.name})
        # Step 2: choose score (not hoard).
        self.rats_client.submit_action({"choice": False})
        # Step 3: pick clearing 2.
        response = self.rats_client.submit_action({"clearing_number": 2})
        self.assertEqual(response.status_code, 200)

        # VP should have increased.
        self.player.refresh_from_db()
        self.assertGreater(
            self.player.score, score_before, "VP should be scored when not adding to hoard"
        )
        # The consumed item is permanently deleted from the game.
        self.assertFalse(
            Item.objects.filter(id=tea_item_id).exists(),
            "The crafted Tea item should be deleted from the game",
        )
        self.assertEqual(
            Item.objects.filter(game=self.game, item_type=ItemTypes.TEA).count(),
            tea_count_before - 1,
            "Exactly one Tea item should have been removed",
        )
        # Item is NOT on hoard track and NOT in CraftedItemEntry.
        self.assertFalse(
            ProwessItemEntry.objects.filter(player=self.player).exists(),
            "Item should NOT be on prowess track when scoring VP",
        )
        self.assertFalse(
            CraftedItemEntry.objects.filter(player=self.player).exists(),
            "Item should NOT appear in CraftedItemEntry — it is removed permanently",
        )


# ===========================================================================
# WarlordMoveInterceptor tests
# ===========================================================================


class RatsDaylightMoveInterceptorTestCase(RatsDaylightBaseTestCase):
    """Tests for WarlordMoveInterceptorView injected into RatsCommandMoveView.

    Two scenarios:
      A) Warlord IS in the origin clearing  → interceptor fires, warlord_choice step shown.
      B) Warlord is NOT in the origin clearing → interceptor silent, move executes directly.

    After setup the Warlord starts in C2.
    C2 adjacencies: C5 (rabbit), C6 (fox), C10 (rabbit).
    """

    def setUp(self):
        super().setUp()
        self._create_turn_at_command()
        self.c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        self.c6 = Clearing.objects.get(game=self.game, clearing_number=6)

    # ------------------------------------------------------------------
    # Navigation helper
    # ------------------------------------------------------------------

    def _navigate_to_move_view(self):
        """Drive the client from the command view to the move sub-view."""
        self.rats_client.get_action()
        self.rats_client.step = {
            "endpoint": "select",
            "payload_details": [{"type": "action_type", "name": "action"}],
        }
        self.rats_client.post_action({"action": "move"})
        # Client has now followed the redirect; self.rats_client.step is the origin step.

    # ------------------------------------------------------------------
    # Scenario A: warlord in origin clearing
    # ------------------------------------------------------------------

    def test_interceptor_fires_when_warlord_in_origin(self):
        """Submitting count when the Warlord is in the origin clearing should
        return the warlord_choice step (not completed)."""
        # Warlord is in C2 from setup.
        self._navigate_to_move_view()
        self.rats_client.submit_action({"clearing_number": 2})  # origin = C2
        self.rats_client.submit_action({"clearing_number": 5})  # dest  = C5

        response = self.rats_client.submit_action({"number": 1})  # count → interceptor fires
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["name"], "move_warlord_choice",
                         "Interceptor should inject the warlord choice step")
        self.assertEqual(data["endpoint"], "warlord")

        option_values = {opt["value"] for opt in data["options"]}
        self.assertIn(True, option_values)
        self.assertIn(False, option_values)

    def test_move_warlord_yes_moves_warlord_to_destination(self):
        """Choosing True (yes) after the interceptor fires should move the Warlord."""
        warlord = Warlord.objects.get(player=self.player)
        self.assertEqual(warlord.clearing, self.c2, "Warlord should start in C2")

        self._navigate_to_move_view()
        self.rats_client.submit_action({"clearing_number": 2})  # origin
        self.rats_client.submit_action({"clearing_number": 5})  # dest
        self.rats_client.submit_action({"number": 1})           # count → interceptor fires
        response = self.rats_client.submit_action({"option": True})  # move warlord
        self.assertEqual(response.status_code, 200)

        warlord.refresh_from_db()
        self.assertEqual(warlord.clearing, self.c5,
                         "Warlord should have moved to C5 after yes")

    def test_move_warlord_no_leaves_warlord_in_origin(self):
        """Choosing False (no) after the interceptor fires should leave the Warlord behind."""
        warlord = Warlord.objects.get(player=self.player)
        self.assertEqual(warlord.clearing, self.c2, "Warlord should start in C2")

        self._navigate_to_move_view()
        self.rats_client.submit_action({"clearing_number": 2})  # origin
        self.rats_client.submit_action({"clearing_number": 5})  # dest
        self.rats_client.submit_action({"number": 1})           # count → interceptor fires
        response = self.rats_client.submit_action({"option": False})  # leave warlord
        self.assertEqual(response.status_code, 200)

        warlord.refresh_from_db()
        self.assertEqual(warlord.clearing, self.c2,
                         "Warlord should remain in C2 after no")

        # The warrior should still have moved to C5.
        self.assertEqual(
            Warrior.objects.filter(player=self.player, clearing=self.c5).count(), 1,
            "One warrior should have moved to C5",
        )

    # ------------------------------------------------------------------
    # Scenario B: warlord NOT in origin clearing
    # ------------------------------------------------------------------

    def test_interceptor_silent_when_warlord_not_in_origin(self):
        """When the Warlord is absent from the origin clearing, count submission
        should execute immediately and return completed without a warlord step."""
        # Move Warlord to C5 so it is not in the origin (C2 → C6 move).
        warlord = Warlord.objects.get(player=self.player)
        warlord.clearing = self.c5
        warlord.save()

        # Move 1 warrior from C2 to C6 (warlord is in C5, not C2).
        warriors_before = Warrior.objects.filter(
            player=self.player, clearing=self.c2
        ).count()

        self._navigate_to_move_view()
        self.rats_client.submit_action({"clearing_number": 2})  # origin = C2 (no warlord)
        self.rats_client.submit_action({"clearing_number": 6})  # dest  = C6
        response = self.rats_client.submit_action({"number": 1})  # count → no interceptor

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "completed",
                         "Move should complete immediately when warlord not in origin")

        # One warrior should have moved to C6.
        self.assertEqual(
            Warrior.objects.filter(player=self.player, clearing=self.c6).count(), 1,
        )
        self.assertEqual(
            Warrior.objects.filter(player=self.player, clearing=self.c2).count(),
            warriors_before - 1,
        )
