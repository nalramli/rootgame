"""Tests for Warlord protection rules (14.2.2).

The Warlord cannot be removed outside of battle.
In battle, the Warlord is always the last warrior removed.

Scenarios covered:
- player_removes_warriors outside battle skips the Warlord (bomb / revolt behaviour)
- player_removes_warriors outside battle is a no-op when only the Warlord is present
- player_removes_warriors on a clearing without a Warlord is unaffected
- In battle: regular warriors absorb hits first; Warlord taken only when regulars exhausted
- In battle with enough regular warriors: Warlord is untouched
- Propaganda Bureau raises IllegalActionError when only the Warlord is in the clearing
- Propaganda Bureau removes a regular warrior (not the Warlord) when both present

Map reference (Autumn map, 1-indexed):
  Fox (r):    1, 6, 8, 12
  Rabbit (y): 3, 4, 5, 10
  Mouse (o):  2, 7, 9, 11

Setup: RATS + CATS.  Rats pick corner C2 (mouse/orange).
After pick_corner(c2): Warlord at C2, 4 warriors at C2, 1 Stronghold at C2.
"""

from django.test import TestCase

from game.errors import IllegalActionError
from game.models.events.event import Event, EventType
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import (
    Card,
    CraftedCardEntry,
    Clearing,
    Faction,
    Game,
    HandEntry,
    Warrior,
)
from game.models.rats.tokens import Warlord
from game.tests.my_factories import GameSetupFactory
from game.transactions.removal import player_removes_warriors
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class WarlordProtectionBaseTestCase(TestCase):
    """RATS + CATS game, setup complete."""

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

        self.warlord = Warlord.objects.get(player=self.player)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _total_warrior_count(self, clearing=None):
        clearing = clearing or self.c2
        return Warrior.objects.filter(player=self.player, clearing=clearing).count()

    def _regular_warrior_count(self, clearing=None):
        clearing = clearing or self.c2
        return Warrior.objects.filter(
            player=self.player, clearing=clearing, warlord__isnull=True
        ).count()

    def _warlord_in(self, clearing=None):
        clearing = clearing or self.c2
        return Warlord.objects.filter(player=self.player, clearing=clearing).exists()

    def _make_active_battle(self):
        """Create an unresolved Battle event so player_removes_warriors sees in_battle=True."""
        from game.models.events.battle import Battle

        event = Event.objects.create(game=self.game, type=EventType.BATTLE)
        return Battle.objects.create(
            event=event,
            attacker=Faction.CATS,
            defender=Faction.RATS,
            clearing=self.c2,
            step=Battle.BattleSteps.ROLL_DICE,
        )


# ===========================================================================
# Outside-battle: Warlord is immune
# ===========================================================================


class WarlordImmunityOutsideBattleTestCase(WarlordProtectionBaseTestCase):
    """player_removes_warriors should never remove the Warlord when no battle is active."""

    def test_warlord_skipped_when_removing_all_warriors(self):
        """Removing the full warrior count (incl. warlord) outside battle leaves the Warlord."""
        regular_before = self._regular_warrior_count()
        total_before = self._total_warrior_count()
        self.assertGreater(regular_before, 0)
        self.assertTrue(self._warlord_in())

        # Pass total count (includes warlord) — outside battle the warlord slot is subtracted.
        player_removes_warriors(self.c2, self.cats_player, self.player, total_before)

        self.assertEqual(self._regular_warrior_count(), 0, "All regular warriors should be removed")
        self.assertTrue(self._warlord_in(), "Warlord must NOT be removed outside battle")

    def test_only_warlord_present_outside_battle_is_noop(self):
        """If only the Warlord is in the clearing, a removal request is a complete no-op."""
        Warrior.objects.filter(
            player=self.player, clearing=self.c2, warlord__isnull=True
        ).update(clearing=None)
        self.assertEqual(self._regular_warrior_count(), 0)
        self.assertTrue(self._warlord_in())

        player_removes_warriors(self.c2, self.cats_player, self.player, 1)

        self.assertTrue(self._warlord_in(), "Warlord must survive a removal attempt outside battle")

    def test_no_warlord_in_clearing_removes_normally(self):
        """A clearing without the Warlord is unaffected by the Rats-specific logic."""
        c6 = Clearing.objects.get(game=self.game, clearing_number=6)
        w = Warrior.objects.filter(
            player=self.player, clearing=self.c2, warlord__isnull=True
        ).first()
        self.assertIsNotNone(w)
        w.clearing = c6
        w.save()

        player_removes_warriors(c6, self.cats_player, self.player, 1)

        self.assertFalse(
            Warrior.objects.filter(player=self.player, clearing=c6).exists(),
            "Regular warrior without Warlord in the clearing should be removed normally",
        )

    def test_partial_removal_outside_battle_skips_warlord(self):
        """Removing N warriors outside battle removes exactly N regular warriors.

        Regular warriors sort first (is_warlord=0); the Warlord sorts last (is_warlord=1)
        and is only reached when count equals the total warrior count. Passing a count
        less than the total never touches the Warlord.
        """
        regular_before = self._regular_warrior_count()
        self.assertGreater(regular_before, 1)

        count = regular_before - 1
        player_removes_warriors(self.c2, self.cats_player, self.player, count)

        self.assertEqual(self._regular_warrior_count(), regular_before - count)  # = 1
        self.assertTrue(self._warlord_in(), "Warlord must be untouched")


# ===========================================================================
# In-battle: Warlord removed last
# ===========================================================================


class WarlordBattleOrderingTestCase(WarlordProtectionBaseTestCase):
    """During an active battle, the Warlord is the last warrior removed."""

    def test_regular_warriors_removed_before_warlord_in_battle(self):
        """With an active battle, hits come off regular warriors first."""
        self._make_active_battle()

        regular_before = self._regular_warrior_count()
        self.assertGreater(regular_before, 1, "Need at least 2 regular warriors")

        hits = regular_before - 1
        player_removes_warriors(self.c2, self.cats_player, self.player, hits)

        self.assertEqual(self._regular_warrior_count(), regular_before - hits)
        self.assertTrue(self._warlord_in(), "Warlord must still be on the board")

    def test_warlord_removed_only_after_regulars_exhausted_in_battle(self):
        """Warlord is removed only when hit count exceeds regular warrior supply."""
        self._make_active_battle()

        total_before = self._total_warrior_count()
        self.assertGreater(self._regular_warrior_count(), 0)

        player_removes_warriors(self.c2, self.cats_player, self.player, total_before)

        self.assertEqual(self._regular_warrior_count(), 0)
        self.assertFalse(
            self._warlord_in(), "Warlord should be removed when all warriors are taken in battle"
        )

    def test_exact_regular_count_leaves_warlord_in_battle(self):
        """Removing exactly the regular warrior count in battle leaves the Warlord untouched."""
        self._make_active_battle()

        regular_before = self._regular_warrior_count()
        self.assertGreater(regular_before, 0)

        player_removes_warriors(self.c2, self.cats_player, self.player, regular_before)

        self.assertEqual(self._regular_warrior_count(), 0)
        self.assertTrue(self._warlord_in(), "Warlord must survive when hits == regular count")


# ===========================================================================
# Propaganda Bureau
# ===========================================================================


class WarlordPropagandaBureauTestCase(WarlordProtectionBaseTestCase):
    """Propaganda Bureau cannot target the Warlord."""

    def setUp(self):
        super().setUp()
        # Prop bureau calls can_use_card which requires the Cats turn to be in Daylight.
        from game.models.cats.turn import CatBirdsong
        from game.transactions.cats import create_cats_turn

        self.game.current_turn = self.cats_player.turn_order
        self.game.save()
        create_cats_turn(self.cats_player)
        # Advance past Birdsong so get_phase returns CatDaylight.
        from game.queries.cats.turn import get_turn as get_cats_turn
        cat_turn = get_cats_turn(self.cats_player)
        birdsong = cat_turn.birdsong
        birdsong.step = CatBirdsong.CatBirdsongSteps.COMPLETED
        birdsong.save()

    def _give_propaganda_bureau(self):
        from game.game_data.cards.exiles_and_partisans import CardsEP

        card = Card.objects.filter(
            game=self.game, card_type=CardsEP.PROPAGANDA_BUREAU.name
        ).first()
        if card is None:
            card = Card.objects.create(
                game=self.game, card_type=CardsEP.PROPAGANDA_BUREAU.name
            )
        CraftedCardEntry.objects.get_or_create(player=self.cats_player, card=card)

    def _give_matching_hand_card(self):
        """Give cats player a card matching C2's suit (orange/mouse → ROOT_TEA_ORANGE)."""
        from game.game_data.cards.exiles_and_partisans import CardsEP

        card = Card.objects.create(
            game=self.game, card_type=CardsEP.ROOT_TEA_ORANGE.name
        )
        return HandEntry.objects.create(player=self.cats_player, card=card)

    def test_prop_bureau_raises_when_only_warlord_in_clearing(self):
        """Propaganda Bureau raises IllegalActionError if only the Warlord is in the clearing."""
        Warrior.objects.filter(
            player=self.player, clearing=self.c2, warlord__isnull=True
        ).update(clearing=None)
        self.assertEqual(self._regular_warrior_count(), 0)
        self.assertTrue(self._warlord_in())

        self._give_propaganda_bureau()
        self._give_matching_hand_card()

        from game.game_data.cards.exiles_and_partisans import CardsEP
        from game.transactions.crafted_cards.propaganda_bureau import use_propaganda_bureau

        with self.assertRaises(IllegalActionError):
            use_propaganda_bureau(
                self.cats_player,
                CardsEP.ROOT_TEA_ORANGE,
                self.c2,
                Faction.RATS,
            )

    def test_prop_bureau_removes_regular_warrior_not_warlord(self):
        """Propaganda Bureau removes a regular warrior when both regular warriors and Warlord are present."""
        regular_before = self._regular_warrior_count()
        self.assertGreater(regular_before, 0)
        self.assertTrue(self._warlord_in())

        self._give_propaganda_bureau()
        self._give_matching_hand_card()

        from game.game_data.cards.exiles_and_partisans import CardsEP
        from game.transactions.crafted_cards.propaganda_bureau import use_propaganda_bureau

        use_propaganda_bureau(
            self.cats_player,
            CardsEP.ROOT_TEA_ORANGE,
            self.c2,
            Faction.RATS,
        )

        self.assertEqual(
            self._regular_warrior_count(),
            regular_before - 1,
            "One regular warrior should have been removed",
        )
        self.assertTrue(self._warlord_in(), "Warlord must NOT be removed by Propaganda Bureau")
