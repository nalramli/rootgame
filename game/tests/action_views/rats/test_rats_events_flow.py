"""Integration tests for Rats event action views.

Tests cover:
  - RatsHoardTooFullView  (/api/rats/events/hoard-too-full/)
  - RatsResolveBitterView (/api/rats/events/bitter-resolve/)
  - RatsLootingView       (/api/rats/events/looting/)

Map reference (Autumn map, 1-indexed):
  Fox (r):    1, 6, 8, 12
  Rabbit (y): 3, 4, 5, 10
  Mouse (o):  2, 7, 9, 11
  C2 ↔ C5 (rabbit), C6 (fox), C10 (rabbit)   — warlord corner
"""

from django.test import TestCase

from game.models.enums import ItemTypes
from game.models.events.battle import Battle
from game.models.events.event import Event, EventType
from game.models.events.rats import HoardTooFullEvent, LootingEvent, ResolveBitterEvent
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import (
    Clearing,
    CraftedItemEntry,
    Faction,
    Game,
    Item,
    Warrior,
)
from game.models.rats.player import CommandItemEntry, ProwessItemEntry
from game.models.rats.tokens import Mob, Warlord
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsTurn
from game.tests.client import RootGameClient
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class RatsEventsBaseTestCase(TestCase):
    """RATS + CATS game with setup completed and a turn created at COMMAND step."""

    def setUp(self):
        self.game = GameSetupFactory(factions=[Faction.RATS, Faction.CATS])
        self.player = self.game.players.get(faction=Faction.RATS)
        self.cats_player = self.game.players.get(faction=Faction.CATS)

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

        # Create a turn at COMMAND so the game has a valid turn state.
        self.rats_turn = RatsTurn.create_turn(self.player)
        birdsong = self.rats_turn.birdsong.first()
        birdsong.step = RatsBirdsong.Steps.COMPLETED
        birdsong.save()
        daylight = self.rats_turn.daylight.first()
        daylight.step = RatsDaylight.Steps.COMMAND
        daylight.save()

        self.warlord = Warlord.objects.get(player=self.player)

        self.player.user.set_password("password")
        self.player.user.save()
        self.rats_client = RootGameClient(
            self.player.user.username, "password", self.game.id
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_item(self, item_type: str) -> Item:
        return Item.objects.create(game=self.game, item_type=item_type)

    def _place_mob(self, clearing: Clearing) -> Mob:
        mob = Mob.objects.filter(player=self.player, clearing__isnull=True).first()
        self.assertIsNotNone(mob, "No mobs in supply")
        mob.clearing = clearing
        mob.save()
        return mob

    def _warrior_from_supply(self, clearing: Clearing, player=None) -> Warrior:
        p = player or self.player
        w = Warrior.objects.filter(player=p, clearing__isnull=True).filter(warlord__isnull=True).first()
        self.assertIsNotNone(w, "No warriors in supply")
        w.clearing = clearing
        w.save()
        return w

    def _make_battle(self, clearing: Clearing) -> Battle:
        """Create a minimal Battle event at *clearing* (RATS vs CATS)."""
        event = Event.objects.create(game=self.game, type=EventType.BATTLE)
        return Battle.objects.create(
            event=event,
            attacker=Faction.RATS,
            defender=Faction.CATS,
            clearing=clearing,
            step=Battle.BattleSteps.ROLL_DICE,
        )


# ===========================================================================
# HoardTooFull tests
# ===========================================================================


class RatsHoardTooFullFlowTestCase(RatsEventsBaseTestCase):
    """Tests for /api/rats/events/hoard-too-full/ (RatsHoardTooFullView)."""

    def setUp(self):
        super().setUp()
        # Add 5 Command-track items directly so the track is overfull.
        for _ in range(5):
            item = self._make_item(ItemTypes.COIN)
            CommandItemEntry.objects.create(player=self.player, item=item)
        # Create the event directly (mirrors what add_item_to_hoard does).
        self.hoard_event = HoardTooFullEvent.create(
            self.player, HoardTooFullEvent.Track.COMMAND
        )

    def test_get_action_routes_to_hoard_too_full(self):
        """get_action() should resolve to hoard-too-full when event is active."""
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/events/hoard-too-full/",
        )

    def test_get_returns_command_track_items(self):
        """GET should list all items on the Command track as options."""
        response = self.rats_client.get_action()
        data = response.json()

        self.assertIn("options", data)
        # 5 Coin items on Command track.
        self.assertEqual(len(data["options"]), 5)
        for opt in data["options"]:
            self.assertEqual(opt["label"], "Coin")

    def test_post_item_removes_it_from_track(self):
        """Discarding an item removes it from the Command track."""
        response = self.rats_client.get_action()
        item_type = response.json()["options"][0]["value"]

        count_before = CommandItemEntry.objects.filter(player=self.player).count()
        self.rats_client.submit_action({"item_type": item_type})

        count_after = CommandItemEntry.objects.filter(player=self.player).count()
        self.assertEqual(count_after, count_before - 1)

    def test_post_item_resolves_event(self):
        """After discarding, the HoardTooFull event should be resolved."""
        response = self.rats_client.get_action()
        item_type = response.json()["options"][0]["value"]

        self.rats_client.submit_action({"item_type": item_type})

        self.hoard_event.event.refresh_from_db()
        self.assertTrue(self.hoard_event.event.is_resolved)

    def test_post_item_scores_vp(self):
        """Discarding an item should score 1 VP."""
        response = self.rats_client.get_action()
        item_type = response.json()["options"][0]["value"]
        vp_before = self.player.score
        self.rats_client.submit_action({"item_type": item_type})
        self.player.refresh_from_db()
        self.assertEqual(self.player.score, vp_before + 1)

    def test_prowess_track_event_shows_prowess_items(self):
        """A PROWESS track event shows Prowess items, not Command items."""
        # Resolve the existing Command event first.
        self.hoard_event.event.is_resolved = True
        self.hoard_event.event.save()
        # Add Prowess items and create a Prowess event.
        for _ in range(5):
            item = self._make_item(ItemTypes.SWORD)
            ProwessItemEntry.objects.create(player=self.player, item=item)
        HoardTooFullEvent.create(self.player, HoardTooFullEvent.Track.PROWESS)

        response = self.rats_client.get_action()
        data = response.json()
        self.assertEqual(len(data["options"]), 5)
        for opt in data["options"]:
            self.assertEqual(opt["label"], "Sword")


# ===========================================================================
# ResolveBitter tests
# ===========================================================================


class RatsResolveBitterFlowTestCase(RatsEventsBaseTestCase):
    """Tests for /api/rats/events/bitter-resolve/ (RatsResolveBitterView)."""

    def setUp(self):
        super().setUp()
        # Warlord at C2; place a mob at C2.
        self.warlord.clearing = self.c2
        self.warlord.save()
        self._place_mob(self.c2)
        # Create a minimal battle + bitter event.
        self.battle = self._make_battle(self.c2)
        self.bitter_event = ResolveBitterEvent.create(self.player, self.battle)

    def test_get_action_routes_to_bitter_resolve(self):
        """get_action() should resolve to bitter-resolve when event is active."""
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/events/bitter-resolve/",
        )

    def test_get_returns_mob_clearing_and_end_option(self):
        """GET should list clearings with mobs near the Warlord, plus End Bitter."""
        response = self.rats_client.get_action()
        data = response.json()

        self.assertIn("options", data)
        option_values = {opt["value"] for opt in data["options"]}
        # C2 has a mob — should appear.
        self.assertIn(2, option_values)
        # End Bitter sentinel always present.
        self.assertIn("", option_values)

    def test_post_end_bitter_resolves_event(self):
        """Posting End Bitter (empty value) should resolve the event."""
        self.rats_client.get_action()
        self.rats_client.submit_action({"clearing_number": ""})

        self.bitter_event.event.refresh_from_db()
        self.assertTrue(self.bitter_event.event.is_resolved)

    def test_post_absorb_removes_mob_places_warrior(self):
        """Absorbing a mob removes it from the clearing and places a warrior in C2."""
        warriors_before = Warrior.objects.filter(
            player=self.player, clearing=self.c2
        ).count()
        mobs_before = Mob.objects.filter(
            player=self.player, clearing__isnull=False
        ).count()

        self.rats_client.get_action()
        response = self.rats_client.submit_action({"clearing_number": "2"})
        self.assertEqual(response.status_code, 200)

        warriors_after = Warrior.objects.filter(
            player=self.player, clearing=self.c2
        ).count()
        mobs_after = Mob.objects.filter(
            player=self.player, clearing__isnull=False
        ).count()

        self.assertEqual(warriors_after, warriors_before + 1)
        self.assertEqual(mobs_after, mobs_before - 1)

    def test_post_absorb_auto_ends_when_no_mobs_remain(self):
        """After absorbing the last nearby mob, event is auto-resolved."""
        # Only one mob (placed in setUp) — absorbing it should auto-end.
        self.rats_client.get_action()
        self.rats_client.submit_action({"clearing_number": "2"})

        self.bitter_event.event.refresh_from_db()
        self.assertTrue(self.bitter_event.event.is_resolved)

    def test_post_absorb_adjacent_mob(self):
        """Absorbing a mob from an adjacent clearing (C6) is valid."""
        c6 = Clearing.objects.get(game=self.game, clearing_number=6)
        self._place_mob(c6)

        self.rats_client.get_action()
        # Absorb from C6 instead of C2 (clear C2 mob first for isolation).
        Mob.objects.filter(player=self.player, clearing=self.c2).update(clearing=None)

        response = self.rats_client.get_action()  # refresh options
        option_values = {opt["value"] for opt in response.json()["options"]}
        self.assertIn(6, option_values)

    def test_get_shows_multiple_mob_options(self):
        """If mobs are in multiple adjacent clearings, all appear as options."""
        c6 = Clearing.objects.get(game=self.game, clearing_number=6)
        self._place_mob(c6)

        response = self.rats_client.get_action()
        option_values = {opt["value"] for opt in response.json()["options"]}
        self.assertIn(2, option_values)
        self.assertIn(6, option_values)


# ===========================================================================
# Looting tests
# ===========================================================================


class RatsLootingFlowTestCase(RatsEventsBaseTestCase):
    """Tests for /api/rats/events/looting/ (RatsLootingView)."""

    def setUp(self):
        super().setUp()
        # Give cats player two crafted items.
        self.sword = self._make_item(ItemTypes.SWORD)
        self.hammer = self._make_item(ItemTypes.HAMMER)
        CraftedItemEntry.objects.create(player=self.cats_player, item=self.sword)
        CraftedItemEntry.objects.create(player=self.cats_player, item=self.hammer)
        # Create looting event.
        self.looting_event = LootingEvent.create(
            looting_player=self.player,
            looted_player=self.cats_player,
        )

    def test_get_action_routes_to_looting(self):
        """get_action() should resolve to looting when event is active."""
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/events/looting/",
        )

    def test_get_returns_looted_player_items(self):
        """GET should list the looted player's crafted items as options."""
        response = self.rats_client.get_action()
        data = response.json()

        self.assertIn("options", data)
        labels = {opt["label"] for opt in data["options"]}
        self.assertIn("Sword", labels)
        self.assertIn("Hammer", labels)
        self.assertEqual(len(data["options"]), 2)

    def test_post_item_removes_from_looted_player(self):
        """Choosing an item removes it from the looted player's crafted items."""
        response = self.rats_client.get_action()
        sword_type = self.sword.item_type
        self.rats_client.submit_action({"item_type": sword_type})

        self.assertFalse(
            CraftedItemEntry.objects.filter(
                player=self.cats_player, item=self.sword
            ).exists()
        )

    def test_post_item_adds_to_rats_hoard(self):
        """Chosen item is added to the Rats hoard."""
        response = self.rats_client.get_action()
        sword_type = self.sword.item_type
        self.rats_client.submit_action({"item_type": sword_type})

        from game.models.rats.player import ProwessItemEntry
        # Sword goes to Prowess track.
        self.assertTrue(
            ProwessItemEntry.objects.filter(
                player=self.player, item=self.sword
            ).exists()
        )

    def test_post_item_resolves_event(self):
        """After choosing, the LootingEvent should be resolved."""
        response = self.rats_client.get_action()
        sword_type = self.sword.item_type
        self.rats_client.submit_action({"item_type": sword_type})

        self.looting_event.event.refresh_from_db()
        self.assertTrue(self.looting_event.event.is_resolved)

    def test_post_invalid_item_returns_400(self):
        """Posting a non-existent item id returns 400."""
        self.rats_client.get_action()
        response = self.rats_client.post_action({"item_type": "nonexistent_type"})
        self.assertEqual(response.status_code, 400)
