"""Integration tests for RatsLavishView (/api/rats/events/lavish/).

Lavish mood: at the end of Birdsong, the player may remove any number of items
from their Hoard permanently. For each item removed, 2 warriors are placed in
the Warlord's clearing. The event is created at the BEFORE_END step and resolves
when the player clicks End or the Hoard empties.
"""

from django.test import TestCase

from game.models.enums import ItemTypes
from game.models.events.rats import LavishEvent
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing, Faction, Game, Item, Warrior
from game.models.rats.player import CommandItemEntry, RatsPlayerState, ProwessItemEntry
from game.models.rats.tokens import Warlord
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


class RatsLavishFlowBaseTestCase(TestCase):
    """RATS + CATS game with an active LavishEvent.

    The event is created directly in setUp rather than going through the birdsong
    hook, so the view tests are isolated from the hook logic.
    """

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
        # Keep birdsong at BEFORE_END so end_lavish_step can advance it
        self.birdsong = self.rats_turn.birdsong.first()
        self.birdsong.step = RatsBirdsong.Steps.BEFORE_END
        self.birdsong.save()
        daylight = self.rats_turn.daylight.first()
        daylight.step = RatsDaylight.Steps.COMPLETED
        daylight.save()

        self.warlord = Warlord.objects.get(player=self.player)

        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": RatsPlayerState.MoodType.LAVISH},
        )

        # Create the LavishEvent directly
        self.evt = LavishEvent.create(self.player)

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

    def _add_command_item(self, item_type: str = ItemTypes.BOOTS) -> Item:
        item = self._make_item(item_type)
        CommandItemEntry.objects.create(player=self.player, item=item)
        return item

    def _add_prowess_item(self, item_type: str = ItemTypes.HAMMER) -> Item:
        item = self._make_item(item_type)
        ProwessItemEntry.objects.create(player=self.player, item=item)
        return item

    def _warrior_count_in_clearing(self, clearing: Clearing) -> int:
        return Warrior.objects.filter(
            player=self.player, clearing=clearing, warlord__isnull=True
        ).count()


# ===========================================================================
# Routing
# ===========================================================================


class LavishFlowRoutingTests(RatsLavishFlowBaseTestCase):

    def test_get_action_routes_to_lavish(self):
        """get_action() should resolve to rats-lavish when event is active."""
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route,
            "/api/rats/events/lavish/",
        )


# ===========================================================================
# GET behaviour
# ===========================================================================


class LavishFlowGetTests(RatsLavishFlowBaseTestCase):

    def test_get_shows_hoard_items(self):
        """GET returns both command and prowess items as options."""
        cmd_item = self._add_command_item(ItemTypes.BOOTS)
        prw_item = self._add_prowess_item(ItemTypes.HAMMER)

        response = self.rats_client.get_action()
        data = response.json()

        self.assertIn("options", data)
        option_values = {opt["value"] for opt in data["options"]}
        self.assertIn(cmd_item.item_type, option_values)
        self.assertIn(prw_item.item_type, option_values)

    def test_get_includes_end_option(self):
        """GET always includes an End option with empty value."""
        self._add_command_item()

        response = self.rats_client.get_action()
        data = response.json()

        option_values = [opt["value"] for opt in data["options"]]
        self.assertIn("", option_values)


# ===========================================================================
# POST select
# ===========================================================================


class LavishFlowSelectTests(RatsLavishFlowBaseTestCase):

    def test_post_end_resolves_event(self):
        """Posting empty item_id (End) resolves the event."""
        self._add_command_item()
        self.rats_client.get_action()
        self.rats_client.submit_action({"item_type": ""})

        self.evt.event.refresh_from_db()
        self.assertTrue(self.evt.event.is_resolved)

    def test_post_end_returns_completed_step(self):
        """Posting End returns a completed step response."""
        self._add_command_item()
        self.rats_client.get_action()
        response = self.rats_client.submit_action({"item_type": ""})
        data = response.json()
        self.assertEqual(data.get("name"), "completed")

    def test_post_valid_item_removes_item_and_places_warriors(self):
        """Posting a valid item_id removes the item and places 2 warriors."""
        item = self._add_command_item()
        before = self._warrior_count_in_clearing(self.c2)

        self.rats_client.get_action()
        self.rats_client.submit_action({"item_type": item.item_type})

        self.assertFalse(Item.objects.filter(id=item.id).exists())
        after = self._warrior_count_in_clearing(self.c2)
        self.assertEqual(after - before, 2)

    def test_post_valid_item_rerenders_if_items_remain(self):
        """After liquidating with items remaining, response re-renders the step (not completed)."""
        self._add_command_item(ItemTypes.BOOTS)
        item2 = self._add_command_item(ItemTypes.BAG)

        self.rats_client.get_action()
        response = self.rats_client.submit_action({"item_type": item2.item_type})
        data = response.json()

        self.assertNotEqual(data.get("name"), "completed")
        self.assertIn("options", data)

    def test_post_last_item_auto_resolves_event(self):
        """Liquidating the last item auto-resolves the event and returns completed."""
        item = self._add_command_item()  # only item

        self.rats_client.get_action()
        response = self.rats_client.submit_action({"item_type": item.item_type})

        self.evt.event.refresh_from_db()
        self.assertTrue(self.evt.event.is_resolved)
        data = response.json()
        self.assertEqual(data.get("name"), "completed")
