"""Tests for the Rats BITTER mood mechanic.

Bitter (hammer item): In battle in the Warlord's clearing, before the dice roll,
the Rats may remove any number of Mob tokens from the Warlord's clearing or
adjacent clearings and place an equal number of warriors in the Warlord's clearing.

Scenarios covered:

_check_bitter_or_roll (via defender_ambush_choice):
- skips to ROLL_DICE when attacker is not Rats
- skips to ROLL_DICE when Rats mood is not BITTER
- skips to ROLL_DICE when Warlord is not in battle clearing
- skips to ROLL_DICE when no mobs in local or adjacent clearings
- launches ResolveBitterEvent (battle stays at ROLL_DICE) when all conditions met
- mobs in adjacent (but not local) clearing also trigger the check

absorb_mob:
- removes mob from board, places warrior in warlord's clearing
- raises when clearing not adjacent or equal to warlord clearing
- raises when no mob in that clearing
- raises when no warriors in supply
- auto-ends (calls end_bitter) when no more mobs available after absorb
- auto-ends when no more warriors in supply after absorb

end_bitter:
- resolves the ResolveBitterEvent
- triggers dice roll (battle proceeds past ROLL_DICE)
- raises when no active bitter event

Map reference (Autumn map, 1-indexed):
  C2 (mouse/orange) ← warlord setup corner
  C2 ↔ C5, C6, C10
  C3 is NOT adjacent to C2
"""

from unittest.mock import patch

from django.test import TestCase

from game.errors import IllegalActionError, UnavailableActionError
from game.models.enums import Faction
from game.models.events.battle import Battle
from game.models.events.rats import ResolveBitterEvent
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Clearing, Game, Warrior
from game.models.rats.player import RatsPlayerState
from game.models.rats.tokens import Mob, Warlord
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsTurn
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------


class RatsBitterBaseTestCase(TestCase):
    """Game at the COMMAND step of Daylight with the Rats in BITTER mood."""

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

        # Default: BITTER mood
        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": RatsPlayerState.MoodType.BITTER},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
        self.assertIsNotNone(mob, "No mobs left in supply")
        mob.clearing = clearing
        mob.save()
        return mob

    def _start_battle_at_c2(self) -> Battle:
        """Start a Rats-vs-Cats battle at c2 (skip ambush, stop before dice)."""
        from game.transactions.battle import start_battle
        self._place_warrior(self.c2, player=self.cats_player)
        battle = start_battle(
            self.game,
            attacker=Faction.RATS,
            defender=Faction.CATS,
            clearing=self.c2,
        )
        return battle

    def _skip_defender_ambush(self, battle: Battle) -> None:
        """Call defender_ambush_choice(None) with zeroed dice so we can check state."""
        from game.transactions.battle import defender_ambush_choice
        with patch("game.transactions.battle.randint", return_value=0):
            defender_ambush_choice(self.game, battle, None)

    def _set_mood(self, mood_type) -> None:
        RatsPlayerState.objects.update_or_create(
            player=self.player,
            defaults={"mood_type": mood_type},
        )


# ===========================================================================
# _check_bitter_or_roll — trigger conditions
# ===========================================================================


class BitterCheckTriggerTests(RatsBitterBaseTestCase):

    def test_skips_to_roll_dice_when_no_mobs(self):
        """No mobs in local/adjacent → battle proceeds straight to ROLL_DICE with no bitter event."""
        battle = self._start_battle_at_c2()
        with patch("game.transactions.battle.randint", return_value=0):
            from game.transactions.battle import defender_ambush_choice
            defender_ambush_choice(self.game, battle, None)

        self.assertFalse(
            ResolveBitterEvent.objects.filter(player=self.player).exists()
        )

    def test_skips_when_mood_is_not_bitter(self):
        """Non-BITTER mood → no event launched."""
        self._set_mood(RatsPlayerState.MoodType.STUBBORN)
        self._place_mob(self.c2)
        battle = self._start_battle_at_c2()
        with patch("game.transactions.battle.randint", return_value=0):
            from game.transactions.battle import defender_ambush_choice
            defender_ambush_choice(self.game, battle, None)

        battle.refresh_from_db()
        self.assertFalse(
            ResolveBitterEvent.objects.filter(player=self.player).exists()
        )

    def test_skips_when_warlord_not_in_battle_clearing(self):
        """Warlord in a different clearing → no event launched."""
        self._place_mob(self.c2)
        # Move warlord out of c2
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        self.warlord.clearing = c5
        self.warlord.save()

        battle = self._start_battle_at_c2()
        with patch("game.transactions.battle.randint", return_value=0):
            from game.transactions.battle import defender_ambush_choice
            defender_ambush_choice(self.game, battle, None)

        battle.refresh_from_db()
        self.assertFalse(
            ResolveBitterEvent.objects.filter(player=self.player).exists()
        )

    def test_launches_event_when_mob_in_warlord_clearing(self):
        """Mob in battle/warlord clearing → ResolveBitterEvent created, battle waits at ROLL_DICE."""
        self._place_mob(self.c2)
        battle = self._start_battle_at_c2()

        from game.transactions.battle import defender_ambush_choice
        defender_ambush_choice(self.game, battle, None)

        battle.refresh_from_db()
        self.assertEqual(battle.step, Battle.BattleSteps.ROLL_DICE)
        self.assertTrue(
            ResolveBitterEvent.objects.filter(
                player=self.player,
                event__is_resolved=False,
            ).exists()
        )

    def test_launches_event_when_mob_in_adjacent_clearing(self):
        """Mob in an adjacent clearing (not the battle clearing itself) → event launched, step = ROLL_DICE."""
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        self._place_mob(c5)
        battle = self._start_battle_at_c2()

        from game.transactions.battle import defender_ambush_choice
        defender_ambush_choice(self.game, battle, None)

        battle.refresh_from_db()
        self.assertEqual(battle.step, Battle.BattleSteps.ROLL_DICE)
        self.assertTrue(
            ResolveBitterEvent.objects.filter(
                player=self.player,
                event__is_resolved=False,
            ).exists()
        )

    def test_does_not_launch_event_when_mob_in_non_adjacent_clearing(self):
        """Mob only in a non-adjacent clearing (C3) → no event launched."""
        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        self._place_mob(c3)
        battle = self._start_battle_at_c2()
        with patch("game.transactions.battle.randint", return_value=0):
            from game.transactions.battle import defender_ambush_choice
            defender_ambush_choice(self.game, battle, None)

        battle.refresh_from_db()
        self.assertFalse(
            ResolveBitterEvent.objects.filter(player=self.player).exists()
        )


# ===========================================================================
# absorb_mob
# ===========================================================================


class AbsorbMobTests(RatsBitterBaseTestCase):

    def _setup_bitter_event(self) -> tuple[Battle, ResolveBitterEvent]:
        """Place a mob in c2, start a battle, and trigger the bitter event."""
        self._place_mob(self.c2)
        battle = self._start_battle_at_c2()
        from game.transactions.battle import defender_ambush_choice
        defender_ambush_choice(self.game, battle, None)
        battle.refresh_from_db()
        bitter_event = ResolveBitterEvent.objects.get(player=self.player, event__is_resolved=False)
        return battle, bitter_event

    def test_removes_mob_from_clearing(self):
        from game.transactions.rats.bitter import absorb_mob

        _, _ = self._setup_bitter_event()
        initial_mobs_on_board = Mob.objects.filter(player=self.player, clearing__isnull=False).count()

        absorb_mob(self.player, self.c2)

        final_mobs_on_board = Mob.objects.filter(player=self.player, clearing__isnull=False).count()
        self.assertEqual(final_mobs_on_board, initial_mobs_on_board - 1)

    def test_places_warrior_in_warlord_clearing(self):
        """absorb_mob places one warrior in the warlord's clearing.

        Patches randint to 0 so the auto-triggered roll_dice (from end_bitter after
        the only mob is absorbed) causes no hits and doesn't remove warriors.
        """
        from game.transactions.rats.bitter import absorb_mob

        _, _ = self._setup_bitter_event()
        initial_warriors = Warrior.objects.filter(player=self.player, clearing=self.c2).count()

        with patch("game.transactions.battle.randint", return_value=0):
            absorb_mob(self.player, self.c2)

        final_warriors = Warrior.objects.filter(player=self.player, clearing=self.c2).count()
        self.assertEqual(final_warriors, initial_warriors + 1)

    def test_absorb_from_adjacent_clearing(self):
        """Mob in adjacent C5 can be absorbed — warrior still goes to warlord's C2.

        Patches randint to 0 so the auto-triggered roll_dice (from end_bitter after
        the only mob is absorbed) causes no hits and doesn't remove warriors.
        """
        from game.transactions.rats.bitter import absorb_mob

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        self._place_mob(c5)
        battle = self._start_battle_at_c2()
        from game.transactions.battle import defender_ambush_choice
        defender_ambush_choice(self.game, battle, None)

        initial_warriors_c2 = Warrior.objects.filter(player=self.player, clearing=self.c2).count()
        with patch("game.transactions.battle.randint", return_value=0):
            absorb_mob(self.player, c5)

        self.assertFalse(Mob.objects.filter(player=self.player, clearing=c5).exists())
        final_warriors_c2 = Warrior.objects.filter(player=self.player, clearing=self.c2).count()
        self.assertEqual(final_warriors_c2, initial_warriors_c2 + 1)

    def test_raises_for_non_adjacent_clearing(self):
        from game.transactions.rats.bitter import absorb_mob

        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        self._place_mob(self.c2)
        self._setup_bitter_event()

        with self.assertRaises(IllegalActionError):
            absorb_mob(self.player, c3)

    def test_raises_when_no_mob_in_clearing(self):
        from game.transactions.rats.bitter import absorb_mob

        self._setup_bitter_event()
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        # c5 has no mob

        with self.assertRaises(IllegalActionError):
            absorb_mob(self.player, c5)

    def test_raises_when_no_warriors_in_supply(self):
        from game.transactions.rats.bitter import absorb_mob

        _, _ = self._setup_bitter_event()
        # Drain all supply warriors into c2
        Warrior.objects.filter(player=self.player, clearing__isnull=True).update(clearing=self.c2)

        with self.assertRaises(IllegalActionError):
            absorb_mob(self.player, self.c2)

    def test_raises_without_active_event(self):
        from game.transactions.rats.bitter import absorb_mob

        self._place_mob(self.c2)
        with self.assertRaises(UnavailableActionError):
            absorb_mob(self.player, self.c2)

    def test_auto_ends_when_no_more_mobs_after_absorb(self):
        """After absorbing the only mob, end_bitter is called automatically — battle proceeds past ROLL_DICE."""
        from game.transactions.rats.bitter import absorb_mob

        _, _ = self._setup_bitter_event()

        with patch("game.transactions.battle.randint", return_value=0):
            absorb_mob(self.player, self.c2)

        # Bitter event resolved
        self.assertFalse(
            ResolveBitterEvent.objects.filter(
                player=self.player, event__is_resolved=False
            ).exists()
        )
        # Battle moved past ROLL_DICE
        battle = Battle.objects.filter(event__game=self.game).order_by("-id").first()
        self.assertNotEqual(battle.step, Battle.BattleSteps.ROLL_DICE)


# ===========================================================================
# end_bitter
# ===========================================================================


class EndBitterTests(RatsBitterBaseTestCase):

    def _setup_bitter_event(self) -> Battle:
        self._place_mob(self.c2)
        battle = self._start_battle_at_c2()
        from game.transactions.battle import defender_ambush_choice
        defender_ambush_choice(self.game, battle, None)
        battle.refresh_from_db()
        return battle

    def test_resolves_event(self):
        from game.transactions.rats.bitter import end_bitter

        self._setup_bitter_event()
        with patch("game.transactions.battle.randint", return_value=0):
            end_bitter(self.player)

        self.assertFalse(
            ResolveBitterEvent.objects.filter(
                player=self.player, event__is_resolved=False
            ).exists()
        )

    def test_battle_proceeds_to_roll_dice(self):
        """After bitter trigger, battle waits at ROLL_DICE; after end_bitter, it proceeds."""
        from game.transactions.rats.bitter import end_bitter

        battle = self._setup_bitter_event()
        self.assertEqual(battle.step, Battle.BattleSteps.ROLL_DICE)

        with patch("game.transactions.battle.randint", return_value=0):
            end_bitter(self.player)

        battle.refresh_from_db()
        self.assertNotEqual(battle.step, Battle.BattleSteps.ROLL_DICE)

    def test_raises_without_active_event(self):
        from game.transactions.rats.bitter import end_bitter

        with self.assertRaises(UnavailableActionError):
            end_bitter(self.player)
