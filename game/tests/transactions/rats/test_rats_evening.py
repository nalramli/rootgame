"""Tests for the Rats Evening phase transactions.

14.6.1 Incite:
  Spend a card to place a Mob token in a matching clearing that has no mob
  but does have a Hundreds warrior (incl. Warlord).

14.6.2 Oppress:
  Score VPs for clearings the Rats rule that have no enemy pieces.
  1-2 → 1 VP, 3-4 → 2 VP, 5 → 3 VP, 6+ → 4 VP.

14.6.3 Draw and Discard:
  Draw 1 card (Rowdy: +1 normally, +2 if 3+ enemy pieces in Warlord's clearing).
  Discard down to 5.

Step flow: INCITE → OPPRESS → DRAW → DISCARD → BEFORE_END → COMPLETED

Map reference (Autumn map, 1-indexed):
  C2 (mouse/orange) ← Warlord setup corner
  C2 ↔ C5, C6, C10
  C3 is NOT adjacent to C2
"""

from django.test import TestCase

from game.errors import IllegalActionError, UnavailableActionError
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.enums import Faction
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing, Game, HandEntry, Warrior
from game.models.rats.player import RatsPlayerState
from game.models.rats.tokens import Mob, Warlord
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsEvening, RatsTurn
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------


class RatsEveningBaseTestCase(TestCase):
    """Game at the INCITE step of Evening."""

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

        self.warlord = Warlord.objects.get(player=self.player)

        # Clear any cards dealt to hand during setup so tests start with a clean hand.
        HandEntry.objects.filter(player=self.player).delete()

        # Use a neutral mood (GRANDIOSE doesn't affect evening mechanics)
        RatsPlayerState.objects.filter(player=self.player).update(
            mood_type=RatsPlayerState.MoodType.GRANDIOSE
        )

    def _set_mood(self, mood_type) -> None:
        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": mood_type},
        )

    def _set_step(self, step) -> None:
        self.evening.step = step
        self.evening.save()

    def _add_card_to_hand(self, card_enum: CardsEP) -> HandEntry:
        from game.models.game_models import Card
        card = Card.objects.create(game=self.game, card_type=card_enum.name)
        return HandEntry.objects.create(player=self.player, card=card)

    def _place_warrior(self, clearing: Clearing, player=None) -> Warrior:
        if player is None:
            player = self.player
        w = Warrior.objects.filter(player=player, clearing__isnull=True).first()
        self.assertIsNotNone(w, "No warriors left in supply")
        w.clearing = clearing
        w.save()
        return w

    def _place_mob(self, clearing: Clearing) -> Mob:
        mob = Mob.objects.filter(player=self.player, clearing__isnull=True).first()
        self.assertIsNotNone(mob, "No mobs in supply")
        mob.clearing = clearing
        mob.save()
        return mob


# ===========================================================================
# Incite
# ===========================================================================


class InciteTests(RatsEveningBaseTestCase):

    def test_incite_places_mob_in_clearing(self):
        """incite places a Mob token in the target clearing."""
        from game.transactions.rats.evening import incite

        # C2 has Warlord (a Warrior) from setup; use a matching card
        hand_entry = self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)

        incite(self.player, self.c2, CardsEP.ROOT_TEA_ORANGE)

        self.assertTrue(Mob.objects.filter(player=self.player, clearing=self.c2).exists())

    def test_incite_discards_card(self):
        """incite discards the spent card from hand."""
        from game.transactions.rats.evening import incite

        hand_entry = self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        incite(self.player, self.c2, CardsEP.ROOT_TEA_ORANGE)

        self.assertFalse(
            HandEntry.objects.filter(player=self.player, card=hand_entry.card).exists()
        )

    def test_incite_raises_wrong_step(self):
        """incite raises if not at INCITE step."""
        from game.transactions.rats.evening import incite

        self._set_step(RatsEvening.Steps.OPPRESS)
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)

        with self.assertRaises(UnavailableActionError):
            incite(self.player, self.c2, CardsEP.ROOT_TEA_ORANGE)

    def test_incite_raises_card_not_in_hand(self):
        """incite raises if card is not in hand."""
        from game.transactions.rats.evening import incite

        HandEntry.objects.filter(
            player=self.player, card__card_type=CardsEP.ROOT_TEA_ORANGE.name
        ).delete()
        with self.assertRaises(IllegalActionError):
            incite(self.player, self.c2, CardsEP.ROOT_TEA_ORANGE)

    def test_incite_raises_wrong_suit(self):
        """incite raises if card suit doesn't match clearing."""
        from game.transactions.rats.evening import incite

        # FOX_PARTISANS is suit FOX; C2 is ORANGE — mismatch
        self._add_card_to_hand(CardsEP.FOX_PARTISANS)
        with self.assertRaises(IllegalActionError):
            incite(self.player, self.c2, CardsEP.FOX_PARTISANS)

    def test_incite_raises_no_warrior_in_clearing(self):
        """incite raises if no Hundreds warrior is in the clearing."""
        from game.transactions.rats.evening import incite

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        # C5 is Rabbit suit; add matching card but no Rats warrior there
        self._add_card_to_hand(CardsEP.RABBIT_PARTISANS)
        with self.assertRaises(IllegalActionError):
            incite(self.player, c5, CardsEP.RABBIT_PARTISANS)

    def test_incite_raises_mob_already_present(self):
        """incite raises if clearing already has a Mob token."""
        from game.transactions.rats.evening import incite

        self._place_mob(self.c2)
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        with self.assertRaises(IllegalActionError):
            incite(self.player, self.c2, CardsEP.ROOT_TEA_ORANGE)

    def test_incite_raises_no_mob_in_supply(self):
        """incite raises if all Mob tokens are already on the board."""
        from game.transactions.rats.evening import incite

        # Place all supply mobs into clearings other than C2 so supply is empty
        # and C2 itself has no mob (otherwise the "already has mob" check fires first).
        non_c2 = list(
            Clearing.objects.filter(game=self.game).exclude(pk=self.c2.pk)
        )
        for idx, mob in enumerate(Mob.objects.filter(player=self.player, clearing__isnull=True)):
            mob.clearing = non_c2[idx % len(non_c2)]
            mob.save()

        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)

        with self.assertRaises(IllegalActionError):
            incite(self.player, self.c2, CardsEP.ROOT_TEA_ORANGE)

    def test_incite_warlord_counts_as_warrior(self):
        """Warlord in clearing satisfies the 'Hundreds warrior' requirement."""
        from game.transactions.rats.evening import incite

        # Warlord is in C2 after setup; no regular warriors needed
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        incite(self.player, self.c2, CardsEP.ROOT_TEA_ORANGE)
        self.assertTrue(Mob.objects.filter(player=self.player, clearing=self.c2).exists())

    def test_end_incite_step_advances(self):
        """end_incite_step moves step to OPPRESS."""
        from game.transactions.rats.evening import end_incite_step

        # Oppress fires automatically via step_effect — just check step isn't INCITE
        end_incite_step(self.player)

        # After OPPRESS fires automatically, we should be past it
        self.evening.refresh_from_db()
        self.assertNotEqual(self.evening.step, RatsEvening.Steps.INCITE)

    def test_end_incite_step_raises_wrong_step(self):
        """end_incite_step raises if not at INCITE step."""
        from game.transactions.rats.evening import end_incite_step

        self._set_step(RatsEvening.Steps.DISCARD)
        with self.assertRaises(UnavailableActionError):
            end_incite_step(self.player)


# ===========================================================================
# Oppress query
# ===========================================================================


class OppressQueryTests(RatsEveningBaseTestCase):

    def test_zero_oppressed_when_enemies_present(self):
        """No clearing qualifies when enemies have pieces in all Rats-ruled clearings."""
        from game.queries.rats.evening import get_oppressed_clearing_count

        # Place a Cats warrior in C2 (so enemies are present)
        self._place_warrior(self.c2, player=self.cats_player)

        count = get_oppressed_clearing_count(self.player)
        self.assertEqual(count, 0)

    def test_counts_clearings_with_no_enemies(self):
        """Clearings where Rats rule and no enemies are present are counted."""
        from game.queries.rats.evening import get_oppressed_clearing_count

        # C2 has the Warlord (a warrior) → Rats rule; no Cats there by default
        count = get_oppressed_clearing_count(self.player)
        self.assertGreaterEqual(count, 1)

    def test_enemy_piece_excludes_clearing(self):
        """A clearing with even one enemy piece does not count."""
        from game.queries.rats.evening import get_oppressed_clearing_count

        baseline = get_oppressed_clearing_count(self.player)
        self._place_warrior(self.c2, player=self.cats_player)
        after = get_oppressed_clearing_count(self.player)
        self.assertEqual(after, baseline - 1)


# ===========================================================================
# Oppress scoring
# ===========================================================================


class OppressScoringTests(RatsEveningBaseTestCase):

    def setUp(self):
        super().setUp()
        self._set_step(RatsEvening.Steps.OPPRESS)

    def _set_oppressed_count(self, target: int) -> None:
        """Patch get_oppressed_clearing_count to return *target*."""
        from unittest.mock import patch
        self._oppress_patcher = patch(
            "game.transactions.rats.evening.get_oppressed_clearing_count",
            return_value=target,
        )
        self._oppress_patcher.start()
        self.addCleanup(self._oppress_patcher.stop)

    def test_score_0_for_zero_clearings(self):
        self._set_oppressed_count(0)
        from game.transactions.rats.evening import resolve_oppress
        initial = self.player.score
        resolve_oppress(self.player)
        self.player.refresh_from_db()
        self.assertEqual(self.player.score, initial)

    def test_score_1_for_one_clearing(self):
        self._set_oppressed_count(1)
        from game.transactions.rats.evening import resolve_oppress
        initial = self.player.score
        resolve_oppress(self.player)
        self.player.refresh_from_db()
        self.assertEqual(self.player.score, initial + 1)

    def test_score_1_for_two_clearings(self):
        self._set_oppressed_count(2)
        from game.transactions.rats.evening import resolve_oppress
        initial = self.player.score
        resolve_oppress(self.player)
        self.player.refresh_from_db()
        self.assertEqual(self.player.score, initial + 1)

    def test_score_2_for_three_clearings(self):
        self._set_oppressed_count(3)
        from game.transactions.rats.evening import resolve_oppress
        initial = self.player.score
        resolve_oppress(self.player)
        self.player.refresh_from_db()
        self.assertEqual(self.player.score, initial + 2)

    def test_score_2_for_four_clearings(self):
        self._set_oppressed_count(4)
        from game.transactions.rats.evening import resolve_oppress
        initial = self.player.score
        resolve_oppress(self.player)
        self.player.refresh_from_db()
        self.assertEqual(self.player.score, initial + 2)

    def test_score_3_for_five_clearings(self):
        self._set_oppressed_count(5)
        from game.transactions.rats.evening import resolve_oppress
        initial = self.player.score
        resolve_oppress(self.player)
        self.player.refresh_from_db()
        self.assertEqual(self.player.score, initial + 3)

    def test_score_4_for_six_clearings(self):
        self._set_oppressed_count(6)
        from game.transactions.rats.evening import resolve_oppress
        initial = self.player.score
        resolve_oppress(self.player)
        self.player.refresh_from_db()
        self.assertEqual(self.player.score, initial + 4)

    def test_score_4_for_more_than_six_clearings(self):
        self._set_oppressed_count(9)
        from game.transactions.rats.evening import resolve_oppress
        initial = self.player.score
        resolve_oppress(self.player)
        self.player.refresh_from_db()
        self.assertEqual(self.player.score, initial + 4)

    def test_resolve_oppress_advances_step(self):
        """resolve_oppress advances past the OPPRESS step."""
        self._set_oppressed_count(0)
        from game.transactions.rats.evening import resolve_oppress
        resolve_oppress(self.player)
        self.evening.refresh_from_db()
        self.assertNotEqual(self.evening.step, RatsEvening.Steps.OPPRESS)

    def test_resolve_oppress_raises_wrong_step(self):
        """resolve_oppress raises if not at OPPRESS step."""
        from game.transactions.rats.evening import resolve_oppress
        self._set_step(RatsEvening.Steps.INCITE)
        with self.assertRaises(UnavailableActionError):
            resolve_oppress(self.player)


# ===========================================================================
# Draw
# ===========================================================================


class DrawTests(RatsEveningBaseTestCase):

    def setUp(self):
        super().setUp()
        self._set_step(RatsEvening.Steps.DRAW)
        # Clear the player's hand so card counts are predictable
        HandEntry.objects.filter(player=self.player).delete()

    def test_base_draw_one_card(self):
        """With non-Rowdy mood, exactly 1 card is drawn."""
        from game.transactions.rats.evening import draw_cards

        draw_cards(self.player)

        self.assertEqual(HandEntry.objects.filter(player=self.player).count(), 1)

    def test_rowdy_draws_two_cards(self):
        """Rowdy mood with fewer than 3 enemy pieces → 2 cards drawn."""
        from game.transactions.rats.evening import draw_cards

        self._set_mood(RatsPlayerState.MoodType.ROWDY)
        # No enemies in Warlord's clearing → < 3 enemies
        draw_cards(self.player)

        self.assertEqual(HandEntry.objects.filter(player=self.player).count(), 2)

    def test_rowdy_draws_three_cards_with_enemy_presence(self):
        """Rowdy mood with 3+ enemy pieces in Warlord's clearing → 3 cards drawn."""
        from game.transactions.rats.evening import draw_cards

        self._set_mood(RatsPlayerState.MoodType.ROWDY)
        # Place 3 Cats warriors in C2 (Warlord's clearing)
        for _ in range(3):
            self._place_warrior(self.c2, player=self.cats_player)

        draw_cards(self.player)

        self.assertEqual(HandEntry.objects.filter(player=self.player).count(), 3)

    def test_draw_advances_to_discard(self):
        """draw_cards advances to DISCARD (or BEFORE_END if hand ≤ 5)."""
        from game.transactions.rats.evening import draw_cards

        draw_cards(self.player)

        self.evening.refresh_from_db()
        self.assertNotEqual(self.evening.step, RatsEvening.Steps.DRAW)

    def test_draw_raises_wrong_step(self):
        """draw_cards raises if not at DRAW step."""
        from game.transactions.rats.evening import draw_cards

        self._set_step(RatsEvening.Steps.INCITE)
        with self.assertRaises(UnavailableActionError):
            draw_cards(self.player)


# ===========================================================================
# Discard
# ===========================================================================


class DiscardTests(RatsEveningBaseTestCase):

    def setUp(self):
        super().setUp()
        self._set_step(RatsEvening.Steps.DISCARD)
        # Clear hand for predictable state, then add 7 cards
        HandEntry.objects.filter(player=self.player).delete()
        from game.models.game_models import Card
        for i in range(7):
            card = Card.objects.create(game=self.game, card_type=CardsEP.ROOT_TEA_ORANGE.name)
            HandEntry.objects.create(player=self.player, card=card)

    def _get_any_hand_entry(self) -> HandEntry:
        return HandEntry.objects.filter(player=self.player).first()

    def test_discard_removes_card_from_hand(self):
        """discard_card removes one card from the player's hand."""
        from game.transactions.rats.evening import discard_card

        entry = self._get_any_hand_entry()
        discard_card(self.player, entry)

        self.assertFalse(HandEntry.objects.filter(pk=entry.pk).exists())

    def test_discard_auto_advances_when_at_five(self):
        """discard_card advances the step when hand drops to exactly 5."""
        from game.transactions.rats.evening import discard_card

        # Discard 2 cards to go from 7 → 5 (second discard triggers advance)
        entry1 = self._get_any_hand_entry()
        discard_card(self.player, entry1)  # 6 cards — no advance
        self.evening.refresh_from_db()
        self.assertEqual(self.evening.step, RatsEvening.Steps.DISCARD)

        entry2 = HandEntry.objects.filter(player=self.player).first()
        discard_card(self.player, entry2)  # 5 cards — advance
        self.evening.refresh_from_db()
        self.assertNotEqual(self.evening.step, RatsEvening.Steps.DISCARD)

    def test_discard_raises_when_already_at_five(self):
        """discard_card raises if hand is already 5 or fewer."""
        from game.transactions.rats.evening import discard_card

        HandEntry.objects.filter(player=self.player).delete()
        from game.models.game_models import Card
        for _ in range(5):
            card = Card.objects.create(game=self.game, card_type=CardsEP.ROOT_TEA_ORANGE.name)
            HandEntry.objects.create(player=self.player, card=card)

        entry = self._get_any_hand_entry()
        with self.assertRaises(UnavailableActionError):
            from game.transactions.rats.evening import discard_card
            discard_card(self.player, entry)

    def test_discard_raises_wrong_player(self):
        """discard_card raises if card belongs to a different player."""
        from game.transactions.rats.evening import discard_card
        from game.models.game_models import Card

        cats_card = Card.objects.create(game=self.game, card_type=CardsEP.ROOT_TEA_ORANGE.name)
        cats_entry = HandEntry.objects.create(player=self.cats_player, card=cats_card)

        with self.assertRaises(IllegalActionError):
            discard_card(self.player, cats_entry)

    def test_end_discard_advances_when_at_five(self):
        """end_discard advances the step when hand is ≤ 5."""
        from game.transactions.rats.evening import end_discard

        HandEntry.objects.filter(player=self.player).delete()
        from game.models.game_models import Card
        for _ in range(5):
            card = Card.objects.create(game=self.game, card_type=CardsEP.ROOT_TEA_ORANGE.name)
            HandEntry.objects.create(player=self.player, card=card)

        end_discard(self.player)

        self.evening.refresh_from_db()
        self.assertNotEqual(self.evening.step, RatsEvening.Steps.DISCARD)

    def test_end_discard_raises_when_over_five(self):
        """end_discard raises if hand still has more than 5 cards."""
        from game.transactions.rats.evening import end_discard

        with self.assertRaises(UnavailableActionError):
            end_discard(self.player)

    def test_end_discard_raises_wrong_step(self):
        """end_discard raises if not at DISCARD step."""
        from game.transactions.rats.evening import end_discard

        self._set_step(RatsEvening.Steps.INCITE)
        with self.assertRaises(UnavailableActionError):
            end_discard(self.player)


# ===========================================================================
# Rowdy draw count query
# ===========================================================================


class RowdyDrawCountTests(RatsEveningBaseTestCase):

    def test_non_rowdy_returns_one(self):
        from game.queries.rats.evening import get_rowdy_draw_count
        self.assertEqual(get_rowdy_draw_count(self.player), 1)

    def test_rowdy_no_enemies_returns_two(self):
        from game.queries.rats.evening import get_rowdy_draw_count
        self._set_mood(RatsPlayerState.MoodType.ROWDY)
        self.assertEqual(get_rowdy_draw_count(self.player), 2)

    def test_rowdy_two_enemies_returns_two(self):
        from game.queries.rats.evening import get_rowdy_draw_count
        self._set_mood(RatsPlayerState.MoodType.ROWDY)
        self._place_warrior(self.c2, player=self.cats_player)
        self._place_warrior(self.c2, player=self.cats_player)
        self.assertEqual(get_rowdy_draw_count(self.player), 2)

    def test_rowdy_three_enemies_returns_three(self):
        from game.queries.rats.evening import get_rowdy_draw_count
        self._set_mood(RatsPlayerState.MoodType.ROWDY)
        for _ in range(3):
            self._place_warrior(self.c2, player=self.cats_player)
        self.assertEqual(get_rowdy_draw_count(self.player), 3)

    def test_rowdy_warlord_not_deployed_returns_two(self):
        """Warlord not deployed → enemy count can't be checked → +1 (minimum Rowdy bonus)."""
        from game.queries.rats.evening import get_rowdy_draw_count
        self._set_mood(RatsPlayerState.MoodType.ROWDY)
        self.warlord.clearing = None
        self.warlord.save()
        self.assertEqual(get_rowdy_draw_count(self.player), 2)
