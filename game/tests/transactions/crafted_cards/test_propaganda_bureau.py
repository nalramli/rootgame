from django.test import TestCase
from game.errors import UnavailableActionError, IllegalActionError, InternalGameError
from django.contrib.auth.models import User
from game.models.game_models import (
    Game,
    Player,
    Faction,
    Card,
    CraftedCardEntry,
    Warrior,
    Clearing,
    Suit,
    HandEntry,
)
from game.models.birds.turn import BirdTurn, BirdBirdsong, BirdDaylight, BirdEvening
from game.models.events.setup import GameSimpleSetup
from game.models.rats.tokens import Warlord
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.transactions.crafted_cards.propaganda_bureau import use_propaganda_bureau
from game.transactions.rats_setup import pick_corner as rats_pick_corner, confirm_completed_setup as rats_confirm_setup

from game.tests.my_factories import (
    GameFactory,
    PlayerFactory,
    BirdTurnFactory,
    CardFactory,
    CraftedCardEntryFactory,
    HandEntryFactory,
    ClearingFactory,
    WarriorFactory,
    GameSetupFactory,
)


class TestPropagandaBureauTransaction(TestCase):
    def setUp(self):
        self.game = GameFactory()
        self.player = PlayerFactory(game=self.game, faction=Faction.BIRDS, turn_order=0)

        # Phase setup - Daylight for PB usage
        # BirdTurnFactory creates phases by default (via create_turn)
        self.bird_turn = BirdTurnFactory(player=self.player, turn_number=1)

        from game.models.birds.turn import BirdBirdsong, BirdDaylight

        birdsong = BirdBirdsong.objects.filter(turn=self.bird_turn).first()
        birdsong.step = BirdBirdsong.BirdBirdsongSteps.COMPLETED
        birdsong.save()
        self.daylight = BirdDaylight.objects.filter(turn=self.bird_turn).first()
        self.daylight.step = "1"  # Daylight active
        self.daylight.save()

        # Cards
        self.pb_card = CardFactory(
            game=self.game, card_type=CardsEP.PROPAGANDA_BUREAU.name
        )
        # Use a real card that has a suit, e.g. FOXFOLK_STEEL (Fox suit)
        self.fox_card = CardFactory(
            game=self.game, card_type=CardsEP.FOXFOLK_STEEL.name
        )

        # Crafted PB
        self.crafted_pb = CraftedCardEntryFactory(
            player=self.player,
            card=self.pb_card,
            used=CraftedCardEntry.UsedChoice.UNUSED,
        )

        # Hand
        self.hand_entry = HandEntryFactory(player=self.player, card=self.fox_card)

        # Board Setup
        self.clearing_fox = ClearingFactory(
            game=self.game, suit=Suit.RED, clearing_number=1
        )

        # Enemy (Cats)
        self.cat_player = PlayerFactory(
            game=self.game, faction=Faction.CATS, turn_order=1
        )
        self.cat_warrior = WarriorFactory(
            player=self.cat_player, clearing=self.clearing_fox
        )

        # Player Warrior (in supply)
        self.bird_warrior = WarriorFactory(player=self.player, clearing=None)

    def test_use_propaganda_bureau_success(self):
        card_ep = CardsEP.FOXFOLK_STEEL  # Matches fox clearing
        target_faction = Faction.CATS

        use_propaganda_bureau(self.player, card_ep, self.clearing_fox, target_faction)

        # Verify effects
        self.cat_warrior.refresh_from_db()
        self.bird_warrior.refresh_from_db()
        self.crafted_pb.refresh_from_db()

        self.assertIsNone(self.cat_warrior.clearing)  # Removed
        self.assertEqual(self.bird_warrior.clearing, self.clearing_fox)  # Added
        self.assertEqual(self.crafted_pb.used, CraftedCardEntry.UsedChoice.USED)  # Used
        self.assertFalse(
            HandEntry.objects.filter(player=self.player, card=self.fox_card).exists()
        )  # Discarded

    def test_use_propaganda_bureau_invalid_card_suit(self):
        # Create a mouse clearing
        clearing_mouse = Clearing.objects.create(
            game=self.game, suit=Suit.ORANGE, clearing_number=2
        )
        # Add cat warrior there
        Warrior.objects.create(player=self.cat_player, clearing=clearing_mouse)

        card_ep = CardsEP.FOXFOLK_STEEL  # Fox suit
        target_faction = Faction.CATS

        with self.assertRaises(IllegalActionError):
            use_propaganda_bureau(self.player, card_ep, clearing_mouse, target_faction)

    def test_use_propaganda_bureau_no_enemy(self):
        # Remove cat warrior
        self.cat_warrior.delete()

        card_ep = CardsEP.FOXFOLK_STEEL
        target_faction = Faction.CATS

        with self.assertRaises(IllegalActionError):
            use_propaganda_bureau(
                self.player, card_ep, self.clearing_fox, target_faction
            )

    def test_use_propaganda_bureau_already_used(self):
        self.crafted_pb.used = CraftedCardEntry.UsedChoice.USED
        self.crafted_pb.save()

        card_ep = CardsEP.FOXFOLK_STEEL
        target_faction = Faction.CATS

        with self.assertRaises(IllegalActionError):
            use_propaganda_bureau(
                self.player, card_ep, self.clearing_fox, target_faction
            )

    def test_use_propaganda_bureau_wrong_phase(self):
        # Move to evening
        self.daylight.step = BirdDaylight.BirdDaylightSteps.COMPLETED
        self.daylight.save()

        card_ep = CardsEP.FOXFOLK_STEEL
        target_faction = Faction.CATS

        with self.assertRaises(UnavailableActionError):
            use_propaganda_bureau(
                self.player, card_ep, self.clearing_fox, target_faction
            )


class TestPropagandaBureauRatsTarget(TestCase):
    """Propaganda Bureau used against the Rats faction.

    The Warlord is immune to PB — it must never be converted.
    """

    def setUp(self):
        # Full game setup so Rats get their Warlord and RatsPlayerState.
        self.game = GameSetupFactory(factions=[Faction.BIRDS, Faction.RATS])
        self.birds_player = self.game.players.get(faction=Faction.BIRDS)
        self.rats_player = self.game.players.get(faction=Faction.RATS)

        # Complete Rats setup so the Warlord is placed on the board.
        game_setup = GameSimpleSetup.objects.get(game=self.game)
        game_setup.status = GameSimpleSetup.GameSetupStatus.RATS_SETUP
        game_setup.save()

        self.corner = Clearing.objects.get(game=self.game, clearing_number=2)
        rats_pick_corner(self.rats_player, self.corner)
        rats_confirm_setup(self.rats_player)

        self.warlord = Warlord.objects.get(player=self.rats_player)

        # Put Birds in Daylight so PB is usable.
        from game.models.birds.turn import BirdBirdsong, BirdDaylight
        bird_turn = BirdTurn.create_turn(self.birds_player)
        birdsong = BirdBirdsong.objects.filter(turn=bird_turn).first()
        birdsong.step = BirdBirdsong.BirdBirdsongSteps.COMPLETED
        birdsong.save()
        daylight = BirdDaylight.objects.filter(turn=bird_turn).first()
        daylight.step = "1"
        daylight.save()

        # Give Birds a PB card and a Fox card to spend.
        pb_card = CardFactory(game=self.game, card_type=CardsEP.PROPAGANDA_BUREAU.name)
        self.fox_card = CardFactory(game=self.game, card_type=CardsEP.FOXFOLK_STEEL.name)
        self.crafted_pb = CraftedCardEntryFactory(
            player=self.birds_player,
            card=pb_card,
            used=CraftedCardEntry.UsedChoice.UNUSED,
        )
        HandEntryFactory(player=self.birds_player, card=self.fox_card)

        # Fox clearing for the action.
        self.clearing = Clearing.objects.filter(game=self.game, suit=Suit.RED).first()
        if self.clearing is None:
            self.clearing = ClearingFactory(game=self.game, suit=Suit.RED, clearing_number=7)

    def _place_warlord_in_clearing(self):
        self.warlord.clearing = self.clearing
        self.warlord.save()

    def test_only_warlord_present_raises(self):
        """PB targeting a clearing with only the Warlord must fail — Warlord is immune."""
        self._place_warlord_in_clearing()

        with self.assertRaises(IllegalActionError):
            use_propaganda_bureau(
                self.birds_player, CardsEP.FOXFOLK_STEEL, self.clearing, Faction.RATS
            )

        # Warlord must remain in the clearing.
        self.warlord.refresh_from_db()
        self.assertEqual(self.warlord.clearing, self.clearing)

    def test_warlord_plus_regular_warrior_converts_regular(self):
        """PB with Warlord + regular warrior must remove the regular warrior, not the Warlord."""
        self._place_warlord_in_clearing()
        regular = WarriorFactory(player=self.rats_player, clearing=self.clearing)

        use_propaganda_bureau(
            self.birds_player, CardsEP.FOXFOLK_STEEL, self.clearing, Faction.RATS
        )

        # Regular warrior removed from board.
        regular.refresh_from_db()
        self.assertIsNone(regular.clearing)

        # Warlord untouched.
        self.warlord.refresh_from_db()
        self.assertEqual(self.warlord.clearing, self.clearing)

        # A Birds warrior was placed in the clearing.
        self.assertTrue(
            Warrior.objects.filter(player=self.birds_player, clearing=self.clearing).exists()
        )
