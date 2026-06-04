from django.test import TestCase
from game.tests.client import RootGameClient
from game.models.game_models import Faction, Player, CraftedCardEntry, Clearing, Warrior
from game.tests.my_factories import GameSetupWithFactionsFactory, CardFactory, CraftedCardEntryFactory
from game.game_data.cards.exiles_and_partisans import CardsEP

class EyrieEmigreViewTestCase(TestCase):
    def setUp(self):
        # Create game with Cats and Birds
        self.game = GameSetupWithFactionsFactory(factions=[Faction.CATS, Faction.BIRDS])
        self.birds_player = self.game.players.get(faction=Faction.BIRDS)
        self.cats_player = self.game.players.get(faction=Faction.CATS)
        
        # Setup passwords for client login
        self.birds_player.user.set_password("password")
        self.birds_player.user.save()
        
        self.birds_client = RootGameClient(self.birds_player.user.username, "password", self.game.id)
        
        # Give Birds Eyrie Emigre card
        self.emigre_card = CardFactory(game=self.game, card_type=CardsEP.EYRIE_EMIGRE.name)
        self.emigre_entry = CraftedCardEntryFactory(player=self.birds_player, card=self.emigre_card, used=CraftedCardEntry.UsedChoice.UNUSED)

        # Place some warriors for move
        self.clearing1 = Clearing.objects.get(game=self.game, clearing_number=1)
        self.clearing2 = Clearing.objects.get(game=self.game, clearing_number=2)
        
        # Clear any existing warriors from setup
        Warrior.objects.filter(clearing__in=[self.clearing1, self.clearing2]).delete()
        
        Warrior.objects.create(player=self.birds_player, clearing=self.clearing1)
        # Add enemy to destination so battle is possible
        Warrior.objects.create(player=self.cats_player, clearing=self.clearing2)
        self.cats_player.refresh_from_db()
        
        # Ensure they are adjacent (should be in Autumn map)
        if self.clearing2 not in self.clearing1.connected_clearings.all():
            self.clearing1.connected_clearings.add(self.clearing2)

        # Set Birds turn and phase to the very end of Birdsong
        from game.models.birds.turn import BirdTurn, BirdBirdsong, BirdDaylight
        self.game.current_turn = 1
        self.game.save()
        if not BirdTurn.objects.filter(player=self.birds_player).exists():
            BirdTurn.create_turn(self.birds_player)
            
        turn = BirdTurn.objects.filter(player=self.birds_player).order_by("-turn_number").first()
        birdsong = BirdBirdsong.objects.get(turn=turn)
        birdsong.step = BirdBirdsong.BirdBirdsongSteps.COMPLETED
        birdsong.save()
        
        # Start daylight but stay at NOT_STARTED for now, get_action should handle it or we advance it
        daylight = BirdDaylight.objects.get(turn=turn)
        daylight.step = BirdDaylight.BirdDaylightSteps.CRAFTING # Move to first real step
        daylight.save()
        
        # Create Eyrie Emigre Event
        from game.models.events.crafted_cards import EyrieEmigreEvent
        self.emigre_event = EyrieEmigreEvent.create(self.emigre_entry)

    def test_eyrie_emigre_move_flow(self):
        """Test Eyrie Emigre move flow."""
        self.birds_client.base_route = "/api/action/card/eyrie-emigre/"
        
        # 1. Initial GET -> use-or-skip
        response = self.birds_client.get(f"{self.birds_client.base_route}?game_id={self.game.id}")
        self.assertEqual(response.status_code, 200)
        self.birds_client.step = response.data
        self.assertEqual(response.data["name"], "use_or_skip")
        
        # 2. SUBMIT "use" -> origin
        response = self.birds_client.submit_action({"choice": "use"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "origin")
        
        # 3. SUBMIT origin -> destination
        response = self.birds_client.submit_action({"clearing_number": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "destination")
        
        # 4. SUBMIT destination -> count
        response = self.birds_client.submit_action({"clearing_number": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "count")
        
        # 5. SUBMIT count -> completed (move executes), then auto-GET -> battle_choice
        response = self.birds_client.submit_action({"number": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "completed")
        self.assertEqual(self.birds_client.step["name"], "battle_choice")
        
        # 6. SUBMIT battle choice -> battle
        response = self.birds_client.submit_action({"choice": "battle"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "battle")

        # 7. SUBMIT battle opponent -> completed
        response = self.birds_client.submit_action({"faction": "ca"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "completed")
        
        # Verify warrior moved
        self.assertEqual(Warrior.objects.filter(player=self.birds_player, clearing=self.clearing2).count(), 1)
        # Verify card marked as used
        self.emigre_entry.refresh_from_db()
        self.assertEqual(self.emigre_entry.used, CraftedCardEntry.UsedChoice.USED)

    def test_eyrie_emigre_skip(self):
        """Test skipping Eyrie Emigre."""
        self.birds_client.base_route = "/api/action/card/eyrie-emigre/"
        
        response = self.birds_client.get(f"{self.birds_client.base_route}?game_id={self.game.id}")
        self.birds_client.step = response.data
        response = self.birds_client.submit_action({"choice": "skip"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "completed")
        
        # Verify card marked as used
        self.emigre_entry.refresh_from_db()
        self.assertEqual(self.emigre_entry.used, CraftedCardEntry.UsedChoice.USED)
