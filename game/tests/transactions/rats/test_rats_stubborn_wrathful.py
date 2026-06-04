"""Tests for the Rats STUBBORN and WRATHFUL mood battle mechanics.

14.7.7 Stubborn (crossbow):
  In battle in your warlord's clearing, you ignore the first hit you take.
  (Does not combine with other first-hit-ignore abilities.)

14.7.8 Wrathful (sword):
  As attacker in battle in your warlord's clearing, you deal an extra hit.

Key design notes:
- Wrathful is added in roll_dice alongside Birds commander / Crows agents.
- Stubborn is applied at the top of apply_dice_hits (covers rolled + partisan hits).
- Both require: Warlord present in the battle clearing.
- Neither fires outside the Warlord's clearing.

Map reference (Autumn map, 1-indexed):
  C2 (mouse/orange) ← warlord setup corner
  C2 ↔ C5, C6, C10
"""

from unittest.mock import patch

from django.test import TestCase

from game.models.enums import Faction
from game.models.events.battle import Battle
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing, Game, Warrior
from game.models.rats.player import RatsPlayerState
from game.models.rats.tokens import Warlord
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsTurn
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------


class RatsMoodBattleBaseTestCase(TestCase):
    """Game at COMMAND step of Daylight; mood set per subclass."""

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
        self.daylight = self.rats_turn.daylight.first()
        self.daylight.step = RatsDaylight.Steps.COMMAND
        self.daylight.save()

        self.warlord = Warlord.objects.get(player=self.player)

    def _set_mood(self, mood_type) -> None:
        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": mood_type},
        )

    def _place_warrior(self, clearing: Clearing, player=None) -> Warrior:
        if player is None:
            player = self.player
        w = Warrior.objects.filter(player=player, clearing__isnull=True).first()
        self.assertIsNotNone(w, "No warriors left in supply")
        w.clearing = clearing
        w.save()
        return w

    def _start_battle_at_c2(self) -> Battle:
        from game.transactions.battle import start_battle
        self._place_warrior(self.c2, player=self.cats_player)
        return start_battle(
            self.game,
            attacker=Faction.RATS,
            defender=Faction.CATS,
            clearing=self.c2,
        )

    def _start_battle_cats_attacking(self) -> Battle:
        """Cats attack Rats at C2 — Rats are the defender."""
        from game.transactions.battle import start_battle
        self._place_warrior(self.c2, player=self.cats_player)
        return start_battle(
            self.game,
            attacker=Faction.CATS,
            defender=Faction.RATS,
            clearing=self.c2,
        )

    def _skip_defender_ambush(self, battle: Battle) -> None:
        from game.transactions.battle import defender_ambush_choice
        defender_ambush_choice(self.game, battle, None)

    def _roll_dice_patched(self, battle: Battle, die1: int, die2: int) -> None:
        """Manually set step to ROLL_DICE and call roll_dice with fixed dice."""
        from game.transactions.battle import roll_dice
        battle.step = Battle.BattleSteps.ROLL_DICE
        battle.save()
        with patch("game.transactions.battle.randint", side_effect=[die1, die2]):
            roll_dice(self.game, battle)


# ===========================================================================
# Wrathful tests
# ===========================================================================


class WrathfulTests(RatsMoodBattleBaseTestCase):

    def setUp(self):
        super().setUp()
        self._set_mood(RatsPlayerState.MoodType.WRATHFUL)

    def test_wrathful_adds_extra_hit_to_defender(self):
        """Wrathful: Rats attacker in Warlord's clearing → defender takes +1 hit."""
        battle = self._start_battle_at_c2()
        battle.step = Battle.BattleSteps.ROLL_DICE
        battle.save()

        # Dice both 0 → 0 rolled hits, but Wrathful should add 1
        with patch("game.transactions.battle.randint", return_value=0):
            from game.transactions.battle import roll_dice
            roll_dice(self.game, battle)

        battle.refresh_from_db()
        self.assertEqual(battle.defender_hits_taken, 1)

    def test_wrathful_does_not_fire_outside_warlord_clearing(self):
        """Wrathful does not fire when battle is not in the Warlord's clearing."""
        # Move warlord away from C2
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        self.warlord.clearing = c5
        self.warlord.save()

        battle = self._start_battle_at_c2()
        battle.step = Battle.BattleSteps.ROLL_DICE
        battle.save()

        with patch("game.transactions.battle.randint", return_value=0):
            from game.transactions.battle import roll_dice
            roll_dice(self.game, battle)

        battle.refresh_from_db()
        # No rolled hits, no warlord bonus — 0 hits on defender (unless undefended)
        # Cats have 1 warrior in C2, so not undefended
        self.assertEqual(battle.defender_hits_taken, 0)

    def test_wrathful_does_not_fire_when_rats_are_defender(self):
        """Wrathful only applies when Rats are the attacker."""
        battle = self._start_battle_cats_attacking()
        battle.step = Battle.BattleSteps.ROLL_DICE
        battle.save()

        # Even if dice give Cats 0 hits, check Wrathful didn't add a hit
        # for Rats (who are the defender here)
        with patch("game.transactions.battle.randint", return_value=0):
            from game.transactions.battle import roll_dice
            roll_dice(self.game, battle)

        battle.refresh_from_db()
        # defender = Rats; Wrathful only fires for attacker, so no bonus
        self.assertEqual(battle.defender_hits_taken, 0)

    def test_non_wrathful_mood_no_extra_hit(self):
        """Non-WRATHFUL mood → no extra hit."""
        self._set_mood(RatsPlayerState.MoodType.STUBBORN)
        battle = self._start_battle_at_c2()
        battle.step = Battle.BattleSteps.ROLL_DICE
        battle.save()

        with patch("game.transactions.battle.randint", return_value=0):
            from game.transactions.battle import roll_dice
            roll_dice(self.game, battle)

        battle.refresh_from_db()
        self.assertEqual(battle.defender_hits_taken, 0)

    def test_wrathful_stacks_with_rolled_hits(self):
        """Wrathful adds on top of rolled hits (die roll = 2 → total 3 hits on defender)."""
        battle = self._start_battle_at_c2()
        battle.step = Battle.BattleSteps.ROLL_DICE
        battle.save()

        # Place enough Cats warriors so the 2-hit roll isn't capped
        for _ in range(3):
            self._place_warrior(self.c2, player=self.cats_player)

        # die1=2, die2=1 → hi=2 (attacker hits defender), lo=1 (defender hits attacker)
        # Wrathful adds 1 → defender_hits_taken = 3
        with patch("game.transactions.battle.randint", side_effect=[2, 1]):
            from game.transactions.battle import roll_dice
            roll_dice(self.game, battle)

        battle.refresh_from_db()
        self.assertEqual(battle.defender_hits_taken, 3)


# ===========================================================================
# Stubborn tests
# ===========================================================================


class StubbornTests(RatsMoodBattleBaseTestCase):

    def setUp(self):
        super().setUp()
        self._set_mood(RatsPlayerState.MoodType.STUBBORN)

    # --- Rats as attacker ---

    def test_stubborn_attacker_reduces_hits_taken_by_1(self):
        """Stubborn (attacker): Rats take 1 fewer hit in Warlord's clearing."""
        # Place enough Cats warriors for the dice to apply 2 hits to Rats
        for _ in range(3):
            self._place_warrior(self.c2, player=self.cats_player)

        battle = self._start_battle_at_c2()
        # Set hits manually so we control the exact scenario
        battle.step = Battle.BattleSteps.ROLL_DICE
        battle.save()

        # die1=3, die2=2 → hi=3 (Rats deal 3), lo=2 (Cats deal 2 to Rats)
        # Stubborn reduces Rats' hits_taken from 2 to 1
        # Rats have enough warriors to absorb without going to choice step
        with patch("game.transactions.battle.randint", side_effect=[3, 2]):
            from game.transactions.battle import roll_dice
            roll_dice(self.game, battle)

        battle.refresh_from_db()
        self.assertEqual(battle.attacker_hits_taken, 1)  # 2 - 1 = 1

    def test_stubborn_attacker_cannot_go_below_zero(self):
        """Stubborn (attacker): hits_taken cannot go below 0."""
        battle = self._start_battle_at_c2()
        battle.step = Battle.BattleSteps.ROLL_DICE
        battle.save()

        # dice both 0 → 0 hits on Rats; Stubborn reduction capped at 0
        with patch("game.transactions.battle.randint", return_value=0):
            from game.transactions.battle import roll_dice
            roll_dice(self.game, battle)

        battle.refresh_from_db()
        self.assertEqual(battle.attacker_hits_taken, 0)

    # --- Rats as defender ---

    def test_stubborn_defender_reduces_hits_taken_by_1(self):
        """Stubborn (defender): Rats take 1 fewer hit when defending in Warlord's clearing."""
        # Place enough Rats warriors so the dice roll matters
        for _ in range(3):
            self._place_warrior(self.c2)
        # Place enough Cats warriors so hi=3 isn't capped (need ≥3 attacker warriors)
        for _ in range(3):
            self._place_warrior(self.c2, player=self.cats_player)

        battle = self._start_battle_cats_attacking()
        battle.step = Battle.BattleSteps.ROLL_DICE
        battle.save()

        # die1=3, die2=2 → hi=3 (Cats deal 3 to Rats), lo=2 (Rats deal 2 to Cats)
        # Stubborn: Rats' defender_hits_taken reduced from 3 to 2
        with patch("game.transactions.battle.randint", side_effect=[3, 2]):
            from game.transactions.battle import roll_dice
            roll_dice(self.game, battle)

        battle.refresh_from_db()
        self.assertEqual(battle.defender_hits_taken, 2)  # 3 - 1 = 2

    # --- Conditions that prevent Stubborn ---

    def test_stubborn_does_not_fire_outside_warlord_clearing(self):
        """Stubborn does not fire when battle is not in the Warlord's clearing."""
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        self.warlord.clearing = c5
        self.warlord.save()

        # Place Cats in C2 for the battle
        for _ in range(3):
            self._place_warrior(self.c2, player=self.cats_player)

        battle = self._start_battle_at_c2()
        battle.step = Battle.BattleSteps.ROLL_DICE
        battle.save()

        # die1=3, die2=2 → hi=3 (Rats deal), lo=2 (Cats deal 2 to Rats)
        # Stubborn should NOT fire → attacker_hits_taken stays at min(lo, warrior_count)
        rats_warriors = Warrior.objects.filter(player=self.player, clearing=self.c2).count()
        with patch("game.transactions.battle.randint", side_effect=[3, 2]):
            from game.transactions.battle import roll_dice
            roll_dice(self.game, battle)

        battle.refresh_from_db()
        # hits capped by warrior count (lo=2, but Rats may have fewer warriors)
        expected = min(2, rats_warriors)
        self.assertEqual(battle.attacker_hits_taken, expected)

    def test_non_stubborn_mood_no_reduction(self):
        """Non-STUBBORN mood → hits are not reduced."""
        self._set_mood(RatsPlayerState.MoodType.WRATHFUL)
        for _ in range(3):
            self._place_warrior(self.c2, player=self.cats_player)

        battle = self._start_battle_at_c2()
        battle.step = Battle.BattleSteps.ROLL_DICE
        battle.save()

        # die1=3, die2=2 → lo=2 hits on Rats
        rats_warriors = Warrior.objects.filter(player=self.player, clearing=self.c2).count()
        with patch("game.transactions.battle.randint", side_effect=[3, 2]):
            from game.transactions.battle import roll_dice
            roll_dice(self.game, battle)

        battle.refresh_from_db()
        expected = min(2, rats_warriors)
        self.assertEqual(battle.attacker_hits_taken, expected)
