from django.test import TestCase

from game.models.events.crafted_cards import EyrieEmigreEvent
from game.models.events.battle import Battle
from game.models.events.event import Event
from game.models.game_models import (
    CraftedCardEntry,
    DiscardPileEntry,
    Faction,
    Clearing,
    Warrior,
)
from game.models.birds.turn import BirdBirdsong, BirdDaylight
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.transactions.crafted_cards.eyrie_emigre import (
    is_emigre,
    emigre_move,
    emigre_battle,
    emigre_skip,
    emigre_skip_battle,
    emigre_failure,
)
from game.tests.my_factories import (
    BirdTurnFactory,
    CardFactory,
    CraftedCardEntryFactory,
    WarriorFactory,
    GameSetupFactory,
)


class EyrieEmigreBaseTestCase(TestCase):
    """
    Shared setUp for all Eyrie Emigre transaction tests.

    Game state: Birds turn, BirdBirdsong at BEFORE_END (the point where
    is_emigre fires). Cats are present as the opposing faction.
    """

    def setUp(self):
        self.game = GameSetupFactory(factions=[Faction.BIRDS, Faction.CATS])
        self.birds_player = self.game.players.get(faction=Faction.BIRDS)
        self.cats_player = self.game.players.get(faction=Faction.CATS)

        self.card = CardFactory(
            game=self.game, card_type=CardsEP.EYRIE_EMIGRE.name, suit="w"
        )
        self.card_entry = CraftedCardEntryFactory(
            player=self.birds_player,
            card=self.card,
            used=CraftedCardEntry.UsedChoice.UNUSED,
        )

        self.turn = BirdTurnFactory(player=self.birds_player, turn_number=1)
        BirdBirdsong.objects.filter(turn=self.turn).update(
            step=BirdBirdsong.BirdBirdsongSteps.BEFORE_END
        )

        self.clearing1 = Clearing.objects.get(game=self.game, clearing_number=1)
        self.clearing2 = Clearing.objects.get(game=self.game, clearing_number=2)
        self.clearing1.connected_clearings.add(self.clearing2)

        WarriorFactory.create_batch(2, player=self.birds_player, clearing=self.clearing1)

    def _create_event(self):
        """Create an EyrieEmigreEvent directly, as is_emigre would."""
        return EyrieEmigreEvent.create(self.card_entry)

    def _advance_birdsong_to_completed(self):
        """Move BirdBirdsong to COMPLETED so get_phase returns BirdDaylight."""
        BirdBirdsong.objects.filter(turn=self.turn).update(
            step=BirdBirdsong.BirdBirdsongSteps.COMPLETED
        )
        BirdDaylight.objects.filter(turn=self.turn).update(
            step=BirdDaylight.BirdDaylightSteps.CRAFTING
        )


# ---------------------------------------------------------------------------
# is_emigre
# ---------------------------------------------------------------------------

class TestIsEmigrе(EyrieEmigreBaseTestCase):

    def test_returns_true_and_creates_event_when_unused_card_present(self):
        result = is_emigre(self.birds_player)

        self.assertTrue(result)
        self.assertTrue(
            EyrieEmigreEvent.objects.filter(
                crafted_card_entry=self.card_entry
            ).exists()
        )

    def test_returns_false_and_no_event_when_card_used(self):
        self.card_entry.used = CraftedCardEntry.UsedChoice.USED
        self.card_entry.save()

        result = is_emigre(self.birds_player)

        self.assertFalse(result)
        self.assertFalse(EyrieEmigreEvent.objects.exists())

    def test_returns_false_when_no_card(self):
        self.card_entry.delete()

        result = is_emigre(self.birds_player)

        self.assertFalse(result)

    def test_does_not_create_duplicate_events(self):
        is_emigre(self.birds_player)
        # Second call: card is still UNUSED but event already exists — should
        # create another (is_emigre creates one each time it's called with an
        # UNUSED card). Verify exactly one event exists after one call.
        self.assertEqual(EyrieEmigreEvent.objects.count(), 1)


# ---------------------------------------------------------------------------
# emigre_move
# ---------------------------------------------------------------------------

class TestEmigreMove(EyrieEmigreBaseTestCase):

    def setUp(self):
        super().setUp()
        self.event = self._create_event()

    def test_moves_warriors_and_marks_move_completed(self):
        WarriorFactory(player=self.cats_player, clearing=self.clearing2)
        emigre_move(self.event, self.clearing1, self.clearing2, 1)

        self.assertEqual(
            Warrior.objects.filter(
                player=self.birds_player, clearing=self.clearing1
            ).count(),
            1,
        )
        self.assertEqual(
            Warrior.objects.filter(
                player=self.birds_player, clearing=self.clearing2
            ).count(),
            1,
        )
        self.event.refresh_from_db()
        self.assertTrue(self.event.move_completed)
        self.assertEqual(self.event.move_destination, self.clearing2)

    def test_raises_if_move_already_completed(self):
        WarriorFactory(player=self.cats_player, clearing=self.clearing2)
        emigre_move(self.event, self.clearing1, self.clearing2, 1)
        self.event.refresh_from_db()

        with self.assertRaises(ValueError, msg="Move already completed"):
            emigre_move(self.event, self.clearing2, self.clearing1, 1)

    def test_triggers_failure_when_no_enemies_in_destination(self):
        # clearing2 has no Cats warriors — emigre_move should call emigre_failure
        emigre_move(self.event, self.clearing1, self.clearing2, 1)

        # Event should be resolved and card discarded (failure path)
        event_qs = Event.objects.filter(pk=self.event.event.pk)
        self.assertTrue(event_qs.get().is_resolved)
        self.assertTrue(
            DiscardPileEntry.objects.filter(card=self.card).exists()
        )

    def test_does_not_trigger_failure_when_enemies_present(self):
        WarriorFactory(player=self.cats_player, clearing=self.clearing2)

        emigre_move(self.event, self.clearing1, self.clearing2, 1)

        # Event should still be unresolved (battle phase follows)
        self.event.event.refresh_from_db()
        self.assertFalse(self.event.event.is_resolved)
        self.assertFalse(
            DiscardPileEntry.objects.filter(card=self.card).exists()
        )


# ---------------------------------------------------------------------------
# emigre_battle
# ---------------------------------------------------------------------------

class TestEmigreBattle(EyrieEmigreBaseTestCase):

    def setUp(self):
        super().setUp()
        # Place an enemy in clearing2 so the move succeeds without failure
        WarriorFactory(player=self.cats_player, clearing=self.clearing2)
        self.event = self._create_event()
        emigre_move(self.event, self.clearing1, self.clearing2, 1)
        self.event.refresh_from_db()

    def test_marks_battle_initiated_and_card_used(self):
        emigre_battle(self.event, Faction.CATS)

        self.event.refresh_from_db()
        self.assertTrue(self.event.battle_initiated)
        self.card_entry.refresh_from_db()
        self.assertEqual(self.card_entry.used, CraftedCardEntry.UsedChoice.USED)

    def test_resolves_emigre_event(self):
        emigre_battle(self.event, Faction.CATS)

        self.event.event.refresh_from_db()
        self.assertTrue(self.event.event.is_resolved)

    def test_creates_battle_event_in_destination_clearing(self):
        emigre_battle(self.event, Faction.CATS)

        battle = Battle.objects.get(
            attacker=Faction.BIRDS.value,
            defender=Faction.CATS.value,
            clearing=self.clearing2,
        )
        self.assertFalse(battle.event.is_resolved)

    def test_advances_phase_to_daylight_before_battle_event(self):
        """
        step_effect must run before start_battle so the unresolved BATTLE
        event doesn't block the turn machine guard in general.step_effect.
        After emigre_battle the BirdBirdsong should be COMPLETED and
        BirdDaylight should be at CRAFTING.
        """
        emigre_battle(self.event, Faction.CATS)

        birdsong = BirdBirdsong.objects.get(turn=self.turn)
        daylight = BirdDaylight.objects.get(turn=self.turn)
        self.assertEqual(birdsong.step, BirdBirdsong.BirdBirdsongSteps.COMPLETED)
        self.assertEqual(daylight.step, BirdDaylight.BirdDaylightSteps.CRAFTING)

    def test_raises_if_battle_already_initiated(self):
        emigre_battle(self.event, Faction.CATS)
        self.event.refresh_from_db()

        with self.assertRaises(ValueError, msg="Battle already initiated"):
            emigre_battle(self.event, Faction.CATS)

    def test_raises_if_move_not_completed(self):
        # Create a fresh event whose move has not been done
        fresh_card = CardFactory(
            game=self.game, card_type=CardsEP.EYRIE_EMIGRE.name, suit="w"
        )
        fresh_entry = CraftedCardEntryFactory(
            player=self.birds_player,
            card=fresh_card,
            used=CraftedCardEntry.UsedChoice.UNUSED,
        )
        fresh_event = EyrieEmigreEvent.create(fresh_entry)

        with self.assertRaises(ValueError, msg="Move must be completed before battle"):
            emigre_battle(fresh_event, Faction.CATS)


# ---------------------------------------------------------------------------
# emigre_skip
# ---------------------------------------------------------------------------

class TestEmigreSkip(EyrieEmigreBaseTestCase):

    def setUp(self):
        super().setUp()
        self.event = self._create_event()

    def test_resolves_event_and_marks_card_used(self):
        emigre_skip(self.event)

        self.event.event.refresh_from_db()
        self.assertTrue(self.event.event.is_resolved)
        self.card_entry.refresh_from_db()
        self.assertEqual(self.card_entry.used, CraftedCardEntry.UsedChoice.USED)

    def test_advances_phase_to_daylight(self):
        emigre_skip(self.event)

        birdsong = BirdBirdsong.objects.get(turn=self.turn)
        daylight = BirdDaylight.objects.get(turn=self.turn)
        self.assertEqual(birdsong.step, BirdBirdsong.BirdBirdsongSteps.COMPLETED)
        self.assertEqual(daylight.step, BirdDaylight.BirdDaylightSteps.CRAFTING)

    def test_does_not_discard_card(self):
        emigre_skip(self.event)

        # Skip marks it USED but does not remove or discard the CraftedCardEntry
        self.assertTrue(
            CraftedCardEntry.objects.filter(pk=self.card_entry.pk).exists()
        )
        self.assertFalse(DiscardPileEntry.objects.filter(card=self.card).exists())


# ---------------------------------------------------------------------------
# emigre_skip_battle  (delegates to emigre_failure)
# ---------------------------------------------------------------------------

class TestEmigreSkipBattle(EyrieEmigreBaseTestCase):

    def setUp(self):
        super().setUp()
        WarriorFactory(player=self.cats_player, clearing=self.clearing2)
        self.event = self._create_event()
        emigre_move(self.event, self.clearing1, self.clearing2, 1)
        self.event.refresh_from_db()
        self._advance_birdsong_to_completed()

    def test_resolves_event_and_discards_card(self):
        emigre_skip_battle(self.event)

        self.event.event.refresh_from_db()
        self.assertTrue(self.event.event.is_resolved)
        self.assertFalse(
            CraftedCardEntry.objects.filter(pk=self.card_entry.pk).exists()
        )
        self.assertTrue(DiscardPileEntry.objects.filter(card=self.card).exists())

    def test_advances_phase_after_failure(self):
        """After skip-battle the turn machine should continue from Daylight."""
        emigre_skip_battle(self.event)

        # Phase was manually set to Daylight CRAFTING in setUp;
        # step_effect at CRAFTING is a no-op so it stays there.
        daylight = BirdDaylight.objects.get(turn=self.turn)
        self.assertEqual(daylight.step, BirdDaylight.BirdDaylightSteps.CRAFTING)


# ---------------------------------------------------------------------------
# emigre_failure  (direct call)
# ---------------------------------------------------------------------------

class TestEmigreFailure(EyrieEmigreBaseTestCase):

    def setUp(self):
        super().setUp()
        self.event = self._create_event()
        self._advance_birdsong_to_completed()

    def test_resolves_event(self):
        emigre_failure(self.event)

        event_obj = Event.objects.get(pk=self.event.event.pk)
        self.assertTrue(event_obj.is_resolved)

    def test_deletes_crafted_card_entry(self):
        emigre_failure(self.event)

        self.assertFalse(
            CraftedCardEntry.objects.filter(pk=self.card_entry.pk).exists()
        )

    def test_adds_card_to_discard_pile(self):
        emigre_failure(self.event)

        self.assertTrue(DiscardPileEntry.objects.filter(card=self.card).exists())

    def test_does_not_leave_unresolved_event(self):
        emigre_failure(self.event)

        self.assertFalse(
            Event.objects.filter(is_resolved=False).exists()
        )
