from django.test import TestCase

from game.errors import UnavailableActionError, IllegalActionError
from game.models.game_models import Faction, Clearing, Warrior, BuildingSlot
from game.models.rats.buildings import Stronghold
from game.models.rats.tokens import Mob, Warlord
from game.models.rats.player import RatsPlayerState
from game.models.rats.setup import RatsSimpleSetup
from game.models.events.setup import GameSimpleSetup
from game.models.cats.tokens import CatKeep
from game.models.moles.tokens import Tunnel
from game.models.birds.buildings import BirdRoost
from game.queries.rats.pieces import get_warriors
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    start_simple_rats_setup,
    pick_corner,
    confirm_completed_setup,
)


class RatsSetupBaseTestCase(TestCase):
    def setUp(self):
        self.game = GameSetupFactory(
            factions=[Faction.RATS, Faction.CATS, Faction.BIRDS, Faction.MOLES]
        )
        self.player = self.game.players.get(faction=Faction.RATS)
        self.cats_player = self.game.players.get(faction=Faction.CATS)
        self.birds_player = self.game.players.get(faction=Faction.BIRDS)
        self.moles_player = self.game.players.get(faction=Faction.MOLES)

        self.game_setup = GameSimpleSetup.objects.get(game=self.game)
        self.game_setup.status = GameSimpleSetup.GameSetupStatus.RATS_SETUP
        self.game_setup.save()

        try:
            self.rats_setup = RatsSimpleSetup.objects.get(player=self.player)
        except RatsSimpleSetup.DoesNotExist:
            self.rats_setup = start_simple_rats_setup(self.player)

        # Block corners 2, 3, 4 with opposing faction pieces to test conflict detection
        c2 = Clearing.objects.get(game=self.game, clearing_number=2)
        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        c4 = Clearing.objects.get(game=self.game, clearing_number=4)

        # Corner 2: CatKeep token
        CatKeep(player=self.cats_player, clearing=c2).save()

        # Corner 3: Moles Tunnel token
        Tunnel(player=self.moles_player, clearing=c3).save()

        # Corner 4: BirdRoost building (needs a BuildingSlot)
        slot = BuildingSlot.objects.filter(clearing=c4).first()
        BirdRoost(player=self.birds_player, building_slot=slot).save()


class RatsInitialSetupTests(RatsSetupBaseTestCase):
    def test_initial_warrior_count(self):
        self.assertEqual(get_warriors(self.player).count(), 20)
        self.assertEqual(get_warriors(self.player).filter(clearing__isnull=True).count(), 20)
        self.assertEqual(Warlord.objects.filter(player=self.player).count(), 1)

    def test_initial_stronghold_count(self):
        self.assertEqual(
            Stronghold.objects.filter(player=self.player).count(), 6
        )
        self.assertEqual(
            Stronghold.objects.filter(player=self.player, building_slot__isnull=True).count(),
            6,
        )

    def test_initial_mob_count(self):
        self.assertEqual(
            Mob.objects.filter(player=self.player).count(), 5
        )
        self.assertEqual(
            Mob.objects.filter(player=self.player, clearing__isnull=True).count(),
            5,
        )

    def test_initial_mood_is_stubborn(self):
        mood = RatsPlayerState.objects.get(player=self.player)
        self.assertEqual(mood.mood_type, RatsPlayerState.MoodType.STUBBORN)


class RatsPickCornerTests(RatsSetupBaseTestCase):
    def test_pick_corner_places_pieces(self):
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        pick_corner(self.player, c1)

        warlord = Warlord.objects.get(player=self.player)
        self.assertEqual(warlord.clearing, c1)

        self.assertEqual(
            get_warriors(self.player).filter(clearing=c1).count(), 4
        )

        self.assertEqual(
            Stronghold.objects.filter(
                player=self.player, building_slot__clearing=c1
            ).count(),
            1,
        )

        self.rats_setup.refresh_from_db()
        self.assertEqual(
            self.rats_setup.step, RatsSimpleSetup.Steps.PENDING_CONFIRMATION
        )

    def test_pick_corner_non_corner_raises(self):
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        with self.assertRaises(IllegalActionError):
            pick_corner(self.player, c5)

    def test_pick_corner_wrong_step_raises(self):
        self.rats_setup.step = RatsSimpleSetup.Steps.PENDING_CONFIRMATION
        self.rats_setup.save()
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        with self.assertRaises(UnavailableActionError):
            pick_corner(self.player, c1)

    def test_pick_corner_wrong_game_status_raises(self):
        self.game_setup.status = GameSimpleSetup.GameSetupStatus.CATS_SETUP
        self.game_setup.save()
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        with self.assertRaises(UnavailableActionError):
            pick_corner(self.player, c1)

    def test_pick_corner_with_keep_raises(self):
        c2 = Clearing.objects.get(game=self.game, clearing_number=2)
        with self.assertRaises(IllegalActionError):
            pick_corner(self.player, c2)

    def test_pick_corner_with_tunnel_raises(self):
        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        with self.assertRaises(IllegalActionError):
            pick_corner(self.player, c3)

    def test_pick_corner_with_roost_raises(self):
        c4 = Clearing.objects.get(game=self.game, clearing_number=4)
        with self.assertRaises(IllegalActionError):
            pick_corner(self.player, c4)


class RatsConfirmSetupTests(RatsSetupBaseTestCase):
    def setUp(self):
        super().setUp()
        c1 = Clearing.objects.get(game=self.game, clearing_number=1)
        pick_corner(self.player, c1)
        self.rats_setup.refresh_from_db()

    def test_confirm_advances_setup(self):
        confirm_completed_setup(self.player)
        self.rats_setup.refresh_from_db()
        self.assertEqual(self.rats_setup.step, RatsSimpleSetup.Steps.COMPLETED)
        self.game_setup.refresh_from_db()
        self.assertNotEqual(
            self.game_setup.status, GameSimpleSetup.GameSetupStatus.RATS_SETUP
        )

    def test_confirm_wrong_step_raises(self):
        self.rats_setup.step = RatsSimpleSetup.Steps.PICKING_CORNER
        self.rats_setup.save()
        with self.assertRaises(UnavailableActionError):
            confirm_completed_setup(self.player)
