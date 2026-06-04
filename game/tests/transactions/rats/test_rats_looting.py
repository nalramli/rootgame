"""Tests for the Rats Looters mechanic.

Scenarios covered:

declare_looting:
- sets looting_declared = True when defender has crafted items
- raises IllegalActionError when defender has no crafted items

Battle starters with looting=True:
- _command_battle with looting=True calls declare_looting
- advance_battle with looting=True raises when no items

roll_dice with looting declared:
- attacker (Rats) deals 0 rolled hits to defender
- defender still deals rolled hits to attacker

end_battle with looting:
- auto-loots the only item when defender has exactly 1 item and Rats rule
- creates a LootingEvent when defender has multiple items and Rats rule
- does NOT loot when Rats don't rule the clearing
- does NOT loot (and resets flag) when defender has no items left at battle end

choose_loot:
- takes chosen item from looted player, adds to hoard, resolves event, resets flag
- raises UnavailableActionError when no active LootingEvent
- raises IllegalActionError when item is not in looted player's crafted items
"""

from unittest.mock import patch

from django.test import TestCase

from game.errors import IllegalActionError, UnavailableActionError
from game.models.enums import Faction, ItemTypes
from game.models.events.battle import Battle
from game.models.events.event import EventType
from game.models.events.rats import LootingEvent
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import (
    Clearing,
    CraftedItemEntry,
    Game,
    Item,
    Player,
    Warrior,
)
from game.models.rats.player import CommandItemEntry, ProwessItemEntry, RatsPlayerState
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsTurn
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class RatsLootingBaseTestCase(TestCase):
    """Sets up a RATS + CATS game at the COMMAND step of Daylight."""

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

        self.rats_state = RatsPlayerState.objects.get(player=self.player)

        # Override the default STUBBORN mood so it doesn't interfere with
        # hit-count assertions in looting tests.
        RatsPlayerState.objects.filter(player=self.player).update(
            mood_type=RatsPlayerState.MoodType.GRANDIOSE
        )
        self.rats_state.refresh_from_db()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _give_cats_item(self, item_type: ItemTypes) -> CraftedItemEntry:
        """Create an item and put it in the Cats player's Crafted Items box."""
        item = Item.objects.create(game=self.game, item_type=item_type.value)
        return CraftedItemEntry.objects.create(player=self.cats_player, item=item)

    def _place_warrior(self, clearing: Clearing, player=None) -> Warrior:
        if player is None:
            player = self.player
        w = Warrior.objects.filter(player=player, clearing__isnull=True).first()
        self.assertIsNotNone(w, "No warriors left in supply")
        w.clearing = clearing
        w.save()
        return w

    def _run_battle_to_end_with_zero_dice(self, looting: bool = False) -> Battle:
        """Start a battle in c2 (with 1 Cats warrior defending), skip defender ambush,
        and roll all-zero dice so no hits are taken and battle resolves cleanly.

        defender_ambush_choice(None) skips ambush and internally chains to
        roll_dice → apply_dice_hits → end_battle.
        """
        from game.transactions.battle import start_battle, defender_ambush_choice

        self._place_warrior(self.c2, player=self.cats_player)

        battle = start_battle(
            self.game,
            attacker=Faction.RATS,
            defender=Faction.CATS,
            clearing=self.c2,
        )

        if looting:
            self.rats_state.looting_declared = True
            self.rats_state.save()

        # Skip defender ambush; this chains to roll_dice → apply_dice_hits → end_battle
        with patch("game.transactions.battle.randint", return_value=0):
            defender_ambush_choice(self.game, battle, None)

        battle.refresh_from_db()
        return battle


# ===========================================================================
# declare_looting
# ===========================================================================


class DeclareLootingTests(RatsLootingBaseTestCase):

    def test_sets_looting_declared_when_defender_has_items(self):
        from game.transactions.rats.looting import declare_looting

        self._give_cats_item(ItemTypes.BOOTS)
        declare_looting(self.player, self.cats_player)

        self.rats_state.refresh_from_db()
        self.assertTrue(self.rats_state.looting_declared)

    def test_raises_when_defender_has_no_items(self):
        from game.transactions.rats.looting import declare_looting

        with self.assertRaises(IllegalActionError):
            declare_looting(self.player, self.cats_player)


# ===========================================================================
# Battle starters with looting=True
# ===========================================================================


class CommandBattleLootingTests(RatsLootingBaseTestCase):

    def test_command_battle_with_looting_sets_declared(self):
        from game.transactions.rats.daylight import use_command

        self._give_cats_item(ItemTypes.BOOTS)
        self._place_warrior(self.c2, player=self.cats_player)

        use_command(self.player, "battle", Faction.CATS, self.c2, looting=True)

        self.rats_state.refresh_from_db()
        self.assertTrue(self.rats_state.looting_declared)

    def test_command_battle_without_looting_does_not_set_declared(self):
        from game.transactions.rats.daylight import use_command

        self._place_warrior(self.c2, player=self.cats_player)

        use_command(self.player, "battle", Faction.CATS, self.c2)

        self.rats_state.refresh_from_db()
        self.assertFalse(self.rats_state.looting_declared)

    def test_command_battle_looting_fails_when_no_items(self):
        from game.transactions.rats.daylight import use_command

        self._place_warrior(self.c2, player=self.cats_player)

        with self.assertRaises(IllegalActionError):
            use_command(self.player, "battle", Faction.CATS, self.c2, looting=True)


# ===========================================================================
# roll_dice with looting declared
# ===========================================================================


class RollDiceLootingTests(RatsLootingBaseTestCase):

    def _start_battle_with_looting(self) -> Battle:
        """Create a battle in c2 with looting declared. Returns battle at
        DEFENDER_AMBUSH_CHECK step — ready for defender_ambush_choice."""
        from game.transactions.battle import start_battle

        self._give_cats_item(ItemTypes.BOOTS)
        self._place_warrior(self.c2, player=self.cats_player)

        battle = start_battle(
            self.game,
            attacker=Faction.RATS,
            defender=Faction.CATS,
            clearing=self.c2,
        )
        self.rats_state.looting_declared = True
        self.rats_state.save()
        return battle

    def test_attacker_deals_zero_rolled_hits_when_looting(self):
        """Rats' rolled hits to the defender are 0 when looting is declared.

        dice: [3, 3] → hi=3 normally goes to defender, but looting zeroes it.
        """
        from game.transactions.battle import defender_ambush_choice

        battle = self._start_battle_with_looting()
        with patch("game.transactions.battle.randint", side_effect=[3, 3]):
            defender_ambush_choice(self.game, battle, None)

        battle.refresh_from_db()
        self.assertEqual(battle.defender_hits_taken, 0)

    def test_defender_still_deals_rolled_hits_when_looting(self):
        """Defender still deals rolled hits to Rats even when looting is declared.

        dice: [3, 1] → lo=min(1, 1 cats warrior)=1 hits Rats regardless of looting.
        """
        from game.transactions.battle import defender_ambush_choice

        battle = self._start_battle_with_looting()
        with patch("game.transactions.battle.randint", side_effect=[3, 1]):
            defender_ambush_choice(self.game, battle, None)

        battle.refresh_from_db()
        # Defender hits attacker with lo=1; Rats took 1 hit
        self.assertEqual(battle.attacker_hits_taken, 1)
        # Rats hit defender with 0 (looting)
        self.assertEqual(battle.defender_hits_taken, 0)


# ===========================================================================
# end_battle with looting — testing _resolve_looting_after_battle
# ===========================================================================


class EndBattleLootingTests(RatsLootingBaseTestCase):

    def test_auto_loot_when_one_item_and_rats_rule(self):
        """With 1 item and Rats ruling c2, the item is automatically added to hoard."""
        self._give_cats_item(ItemTypes.BOOTS)
        self._run_battle_to_end_with_zero_dice(looting=True)

        self.rats_state.refresh_from_db()
        self.assertFalse(self.rats_state.looting_declared)
        # BOOTS → Command track
        self.assertTrue(CommandItemEntry.objects.filter(player=self.player).exists())
        self.assertFalse(CraftedItemEntry.objects.filter(player=self.cats_player).exists())

    def test_looting_event_created_when_multiple_items_and_rats_rule(self):
        """With 2+ items and Rats ruling, a LootingEvent is created for player choice."""
        self._give_cats_item(ItemTypes.BOOTS)
        self._give_cats_item(ItemTypes.COIN)
        self._run_battle_to_end_with_zero_dice(looting=True)

        self.assertTrue(
            LootingEvent.objects.filter(
                looting_player=self.player,
                event__is_resolved=False,
            ).exists()
        )
        # looting_declared stays True while event is pending
        self.rats_state.refresh_from_db()
        self.assertTrue(self.rats_state.looting_declared)

    def test_no_loot_when_rats_dont_rule(self):
        """Looting fails when Rats don't rule the clearing — flag reset, items untouched.

        Tests _resolve_looting_after_battle directly to avoid the start_battle
        warrior-presence requirement conflict with stripping Rats warriors.
        """
        from game.transactions.battle import _resolve_looting_after_battle
        from game.models.events.event import Event

        self._give_cats_item(ItemTypes.BOOTS)
        self.rats_state.looting_declared = True
        self.rats_state.save()

        # Remove all Rats warriors from c2 so Cats rule
        Warrior.objects.filter(player=self.player, clearing=self.c2).update(clearing=None)
        self._place_warrior(self.c2, player=self.cats_player)

        # Create a minimal completed battle pointing at c2
        event = Event.objects.create(
            game=self.game, type=EventType.BATTLE, is_resolved=True
        )
        battle = Battle.objects.create(
            event=event,
            attacker=Faction.RATS,
            defender=Faction.CATS,
            clearing=self.c2,
            step=Battle.BattleSteps.COMPLETED,
        )

        _resolve_looting_after_battle(self.game, battle)

        self.rats_state.refresh_from_db()
        self.assertFalse(self.rats_state.looting_declared)
        # Item untouched
        self.assertTrue(CraftedItemEntry.objects.filter(player=self.cats_player).exists())

    def test_no_loot_when_no_items_at_end(self):
        """Flag is reset and no event created when defender has no items at battle end."""
        # No items given to Cats; set looting flag manually and run resolution
        from game.transactions.battle import _resolve_looting_after_battle
        from game.models.events.event import Event

        self.rats_state.looting_declared = True
        self.rats_state.save()

        event = Event.objects.create(
            game=self.game, type=EventType.BATTLE, is_resolved=True
        )
        battle = Battle.objects.create(
            event=event,
            attacker=Faction.RATS,
            defender=Faction.CATS,
            clearing=self.c2,
            step=Battle.BattleSteps.COMPLETED,
        )

        _resolve_looting_after_battle(self.game, battle)

        self.rats_state.refresh_from_db()
        self.assertFalse(self.rats_state.looting_declared)
        self.assertFalse(
            LootingEvent.objects.filter(looting_player=self.player).exists()
        )

    def test_no_looting_event_without_declaration(self):
        """No looting occurs when looting=False, even if defender has items."""
        self._give_cats_item(ItemTypes.BOOTS)
        self._run_battle_to_end_with_zero_dice(looting=False)

        self.assertFalse(
            LootingEvent.objects.filter(looting_player=self.player).exists()
        )
        self.assertTrue(CraftedItemEntry.objects.filter(player=self.cats_player).exists())


# ===========================================================================
# choose_loot
# ===========================================================================


class ChooseLootTests(RatsLootingBaseTestCase):

    def _setup_looting_event(self) -> tuple:
        """Give Cats two items and create an active LootingEvent. Returns (item1, item2)."""
        entry1 = self._give_cats_item(ItemTypes.BOOTS)
        entry2 = self._give_cats_item(ItemTypes.COIN)
        self.rats_state.looting_declared = True
        self.rats_state.save()
        LootingEvent.create(
            looting_player=self.player,
            looted_player=self.cats_player,
        )
        return entry1.item, entry2.item

    def test_choose_loot_takes_item_and_adds_to_hoard(self):
        from game.transactions.rats.looting import choose_loot

        item1, _ = self._setup_looting_event()
        choose_loot(self.player, item1)

        self.assertFalse(
            CraftedItemEntry.objects.filter(player=self.cats_player, item=item1).exists()
        )
        # BOOTS → Command track
        self.assertTrue(CommandItemEntry.objects.filter(player=self.player, item=item1).exists())

    def test_choose_loot_resolves_event(self):
        from game.transactions.rats.looting import choose_loot

        item1, _ = self._setup_looting_event()
        choose_loot(self.player, item1)

        self.assertFalse(
            LootingEvent.objects.filter(
                looting_player=self.player, event__is_resolved=False
            ).exists()
        )

    def test_choose_loot_resets_looting_declared(self):
        from game.transactions.rats.looting import choose_loot

        item1, _ = self._setup_looting_event()
        choose_loot(self.player, item1)

        self.rats_state.refresh_from_db()
        self.assertFalse(self.rats_state.looting_declared)

    def test_choose_loot_raises_without_active_event(self):
        from game.transactions.rats.looting import choose_loot

        item = self._give_cats_item(ItemTypes.BOOTS).item
        with self.assertRaises(UnavailableActionError):
            choose_loot(self.player, item)

    def test_choose_loot_raises_for_wrong_item(self):
        from game.transactions.rats.looting import choose_loot

        self._setup_looting_event()
        # Item that's not in Cats' crafted items
        wrong_item = Item.objects.create(game=self.game, item_type=ItemTypes.SWORD.value)

        with self.assertRaises(IllegalActionError):
            choose_loot(self.player, wrong_item)
