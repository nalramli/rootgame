from django.test import TestCase
from game.tests.client import RootGameClient
from game.models.game_models import Faction
from game.models.rats.setup import RatsSimpleSetup
from game.models.rats.tokens import Warlord
from game.models.events.setup import GameSimpleSetup
from game.tests.my_factories import GameSetupFactory
from game.transactions.cats_setup import pick_corner as cats_pick_corner, confirm_completed_setup as cats_confirm


class RatsSetupFlowTestCase(TestCase):
    def setUp(self):
        # Create a game with Rats and Cats
        self.game = GameSetupFactory(
            factions=[Faction.RATS, Faction.CATS],
        )

        # Identify players
        self.cats_player = self.game.players.get(faction=Faction.CATS)
        self.rats_player = self.game.players.get(faction=Faction.RATS)

        # Set up client for Rats player
        self.rats_player.user.set_password("password")
        self.rats_player.user.save()
        self.rats_client = RootGameClient(
            self.rats_player.user.username, "password", self.game.id
        )

        # Complete Cats setup (Cats take corner 1)
        cats_pick_corner(self.cats_player, self.game.clearing_set.get(clearing_number=1))
        from game.models.cats.buildings import CatBuildingTypes
        for building_type, clearing_num in [
            (CatBuildingTypes.RECRUITER, 1),
            (CatBuildingTypes.SAWMILL, 5),
            (CatBuildingTypes.WORKSHOP, 9),
        ]:
            from game.transactions.cats_setup import place_initial_building
            place_initial_building(
                self.cats_player,
                self.game.clearing_set.get(clearing_number=clearing_num),
                building_type,
            )
        cats_confirm(self.cats_player)

        # Advance to Rats setup
        game_setup = GameSimpleSetup.objects.get(game=self.game)
        game_setup.status = GameSimpleSetup.GameSetupStatus.RATS_SETUP
        game_setup.save()

    def test_rats_pick_corner_flow(self):
        """Test that Rats can pick a corner and advance setup step."""
        # Get initial action — should route to pick-corner
        self.rats_client.get_action()
        self.assertEqual(self.rats_client.base_route, "/api/rats/setup/pick-corner/")

        # Pick corner 3 (cats took corner 1)
        response = self.rats_client.submit_action({"clearing_number": 3})
        self.assertEqual(response.status_code, 200)

        # Verify step advanced to PENDING_CONFIRMATION
        rats_setup = RatsSimpleSetup.objects.get(player=self.rats_player)
        self.assertEqual(rats_setup.step, RatsSimpleSetup.Steps.PENDING_CONFIRMATION)

        # Verify Warlord is in clearing 3
        clearing_3 = self.game.clearing_set.get(clearing_number=3)
        warlord = Warlord.objects.get(player=self.rats_player)
        self.assertEqual(warlord.clearing, clearing_3)

    def test_rats_confirm_setup_flow(self):
        """Test that Rats can confirm setup completion after picking a corner."""
        # First pick a corner
        self.rats_client.get_action()
        self.rats_client.submit_action({"clearing_number": 3})

        # Get confirm action — should route to confirm-completed-setup
        self.rats_client.get_action()
        self.assertEqual(
            self.rats_client.base_route, "/api/rats/setup/confirm-completed-setup/"
        )

        # Submit confirmation
        response = self.rats_client.submit_action({"confirm": True})
        self.assertEqual(response.status_code, 200)

        # Verify step advanced to COMPLETED
        rats_setup = RatsSimpleSetup.objects.get(player=self.rats_player)
        self.assertEqual(rats_setup.step, RatsSimpleSetup.Steps.COMPLETED)

        # Verify game setup status advanced past RATS_SETUP
        game_setup = GameSimpleSetup.objects.get(game=self.game)
        self.assertNotEqual(
            game_setup.status, GameSimpleSetup.GameSetupStatus.RATS_SETUP
        )
