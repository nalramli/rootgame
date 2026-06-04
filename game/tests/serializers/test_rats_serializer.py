"""
Tests for RatsSerializer output within GameStateSerializer.

setUp creates a RATS + CATS game, places pieces for both factions (without
running the full confirm-setup flow to avoid cascading side-effects), then
serializes the game state and asserts the rats faction_state is correct.
"""

from django.test import TestCase

from game.models.game_models import (
    Clearing,
    Faction,
    FactionChoiceEntry,
    Game,
    Player,
    Warrior,
)
from game.models.events.setup import GameSimpleSetup
from game.models.rats.buildings import Stronghold
from game.models.rats.player import RatsPlayerState
from game.models.rats.tokens import Warlord
from game.serializers.game_state_serializer import GameStateSerializer
from game.tests.my_factories import UserFactory
from game.transactions.cats_setup import (
    pick_corner as cats_pick_corner,
    place_initial_building,
    start_simple_cats_setup,
)
from game.transactions.game_setup import (
    add_new_player_to_game,
    construct_deck,
    create_craftable_item_supply,
    create_game_setup,
    create_new_game,
    deal_starting_cards,
    map_setup,
    player_picks_faction,
)
from game.transactions.rats_setup import (
    pick_corner as rats_pick_corner,
    start_simple_rats_setup,
)
from game.transactions.setup_util import next_player_setup
from game.models.cats.buildings import CatBuildingTypes


def _make_rats_cats_game():
    """
    Build a RATS + CATS game with both factions' pieces fully placed,
    ready for serialization tests.

    We replicate the relevant parts of start_game manually to avoid the
    KeyError that ``begin_faction_setup`` raises when it encounters RATS
    (RATS is not yet wired into that helper).  We also stop short of calling
    ``confirm_completed_setup`` for either faction so that
    ``next_player_setup`` is never invoked and no CatTurn/RatsTurn rows are
    created unexpectedly.

    Returns (game, rats_player, cats_player).
    """
    owner = UserFactory()
    rats_user = UserFactory()

    game = create_new_game(owner, Game.BoardMaps.AUTUMN, [Faction.CATS, Faction.RATS])

    # Add cats player (turn_order 0) and rats player (turn_order 1)
    cats_player = add_new_player_to_game(game, owner)
    cats_choice = FactionChoiceEntry.objects.get(game=game, faction=Faction.CATS)
    player_picks_faction(cats_player, cats_choice)
    cats_player.turn_order = 0
    cats_player.save()

    rats_player = add_new_player_to_game(game, rats_user)
    rats_choice = FactionChoiceEntry.objects.get(game=game, faction=Faction.RATS)
    player_picks_faction(rats_player, rats_choice)
    rats_player.turn_order = 1
    rats_player.save()

    # Infrastructure (deck, map, items) — matches start_game minus begin_faction_setup
    create_game_setup(game)
    map_setup(game)
    construct_deck(game)
    create_craftable_item_supply(game)
    deal_starting_cards(game)

    # Advance setup status to CATS_SETUP so cats transactions validate correctly
    next_player_setup(game)  # INITIAL_SETUP → CATS_SETUP

    # Initialise faction pieces for cats (start_simple_rats_setup called separately below)
    start_simple_cats_setup(cats_player)

    game.status = Game.GameStatus.STARTED
    game.save()

    # ── Place cats pieces (pick corner + three initial buildings) ────────────
    # We do NOT call cats_confirm so next_player_setup is never triggered.
    c1 = Clearing.objects.get(game=game, clearing_number=1)
    c5 = Clearing.objects.get(game=game, clearing_number=5)
    c9 = Clearing.objects.get(game=game, clearing_number=9)

    cats_pick_corner(cats_player, c1)
    place_initial_building(cats_player, c1, CatBuildingTypes.SAWMILL)
    place_initial_building(cats_player, c5, CatBuildingTypes.WORKSHOP)
    place_initial_building(cats_player, c9, CatBuildingTypes.RECRUITER)

    # ── Place rats pieces (start setup + pick corner) ────────────────────────
    # Force status to RATS_SETUP so pick_corner validation passes.
    game_setup = GameSimpleSetup.objects.get(game=game)
    game_setup.status = GameSimpleSetup.GameSetupStatus.RATS_SETUP
    game_setup.save()

    start_simple_rats_setup(rats_player)

    # Clearing 1 is occupied by the cats keep — use clearing 2.
    c2 = Clearing.objects.get(game=game, clearing_number=2)
    rats_pick_corner(rats_player, c2)
    # We intentionally omit rats_confirm to avoid the second next_player_setup call.

    return game, rats_player, cats_player


class RatsGameStateSerializerTests(TestCase):
    """Verify that GameStateSerializer includes correct rats faction_state."""

    def setUp(self):
        self.game, self.rats_player, self.cats_player = _make_rats_cats_game()
        serializer = GameStateSerializer(self.game)
        data = serializer.data

        # Locate rats and cats payloads in the players list
        self.rats_payload = next(
            p for p in data["players"] if p["id"] == self.rats_player.id
        )
        self.cats_payload = next(
            p for p in data["players"] if p["id"] == self.cats_player.id
        )
        self.rats_state = self.rats_payload["faction_state"]

    # ── Presence ────────────────────────────────────────────────────────────

    def test_rats_state_present(self):
        """faction_state is serialized for the rats player."""
        self.assertIn("faction_state", self.rats_payload)
        self.assertIsNotNone(self.rats_state)

    def test_rats_faction_field(self):
        """Player record reports faction as RATS."""
        self.assertEqual(self.rats_payload["faction"], Faction.RATS)

    # ── Warriors ────────────────────────────────────────────────────────────

    def test_rats_warriors_count(self):
        """
        Rats start with 20 warriors total (4 placed in corner, 16 in supply).
        get_warriors excludes the warlord, so all 20 Warrior rows appear.
        """
        warriors = self.rats_state["warriors"]
        self.assertEqual(len(warriors), 20)

    def test_rats_warriors_placed_count(self):
        """Exactly 4 warriors are placed in the corner clearing after setup."""
        warriors = self.rats_state["warriors"]
        placed = [w for w in warriors if w["clearing_number"] is not None]
        self.assertEqual(len(placed), 4)

    # ── Warlord ─────────────────────────────────────────────────────────────

    def test_rats_warlord_present(self):
        """Warlord is serialized and is not None."""
        self.assertIn("warlord", self.rats_state)
        self.assertIsNotNone(self.rats_state["warlord"])

    def test_rats_warlord_placed(self):
        """Warlord has a clearing_number (was placed during pick_corner)."""
        warlord = self.rats_state["warlord"]
        self.assertIsNotNone(warlord["clearing_number"])

    # ── Strongholds ─────────────────────────────────────────────────────────

    def test_rats_strongholds_count(self):
        """
        Rats have 6 strongholds total (1 placed in corner, 5 still in supply).
        """
        strongholds = self.rats_state["buildings"]["strongholds"]
        self.assertEqual(len(strongholds), 6)

    def test_rats_strongholds_placed_count(self):
        """Exactly 1 stronghold is placed on the board after setup."""
        strongholds = self.rats_state["buildings"]["strongholds"]
        placed = [
            s for s in strongholds
            if s["building"]["clearing_number"] is not None
        ]
        self.assertEqual(len(placed), 1)

    # ── Mood ────────────────────────────────────────────────────────────────

    def test_rats_mood_is_stubborn(self):
        """Initial mood is STUBBORN."""
        mood = self.rats_state["mood"]
        self.assertEqual(mood["mood_type"], RatsPlayerState.MoodType.STUBBORN)

    # ── Cross-player visibility ─────────────────────────────────────────────

    def test_cats_player_sees_rats_faction_state(self):
        """
        All faction states are public; the game-state payload exposes rats
        faction_state for all players.
        """
        self.assertIn("faction_state", self.cats_payload)
        self.assertIsNotNone(self.cats_payload["faction_state"])
        # Rats state is always included regardless of whose perspective this is
        self.assertIsNotNone(self.rats_state)
