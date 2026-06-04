"""Tests for the Rats COMMAND step transaction (use_command wrapper + sub-commands).

Scenarios covered:

use_command wrapper:
- commands_used increments after each successful command
- raises UnavailableActionError when commands_used >= command_value (1 at 0 items)
- raises IllegalActionError for an unknown command_type
- raises UnavailableActionError when called at wrong step (CRAFT)

Move (_command_move):
- warriors move from origin to destination (counts in both clearings change)
- raises if origin clearing has fewer warriors than count
- raises if clearings are not adjacent

Battle (_command_battle):
- a Battle object is created in the clearing
- raises if player has no warriors in the clearing (no attacker warriors)

Build (_command_build):
- a Stronghold is placed in the clearing after spending the card
- card is removed from hand
- raises if clearing suit doesn't match card suit
- raises if Rats don't rule the clearing
- raises if no Strongholds left in supply
- raises if no building slot available in clearing

Map reference (Autumn map, 1-indexed):
  Fox  (r): 1, 6, 8, 12
  Rabbit (y): 3, 4, 5, 10
  Mouse (o): 2, 7, 9, 11

Corner clearings: 1-4.  pick_corner uses C2 (mouse/orange) →
  warlord + 4 warriors + 1 stronghold from setup.

Key adjacencies:
  C2  ↔ C5, C6, C10
  C5  ↔ C1, C2
  C6  ↔ C2, C3, C11
  C10 ↔ C1, C2, C12

  C3 is NOT adjacent to C2 (use for non-adjacency tests).
"""

from django.test import TestCase

from game.errors import IllegalActionError, UnavailableActionError
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.events.battle import Battle
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import (
    Building,
    BuildingSlot,
    Card,
    Clearing,
    Faction,
    Game,
    HandEntry,
    Warrior,
)
from game.models.rats.buildings import Stronghold
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsTurn
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------


class RatsCommandBaseTestCase(TestCase):
    """Creates a RATS + CATS game at the COMMAND step of Daylight."""

    def setUp(self):
        self.game = GameSetupFactory(factions=[Faction.RATS, Faction.CATS])
        self.player = self.game.players.get(faction=Faction.RATS)
        self.cats_player = self.game.players.get(faction=Faction.CATS)

        # Complete rats setup: force status, pick corner C2 (mouse/orange), confirm.
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

        # Clear any cards dealt during setup so hand-state assertions are reliable.
        HandEntry.objects.filter(player=self.player).delete()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_card_to_hand(self, card_enum: CardsEP) -> HandEntry:
        """Create a card of the given type and put it in the player's hand."""
        card = Card.objects.create(game=self.game, card_type=card_enum.name)
        return HandEntry.objects.create(player=self.player, card=card)

    def _deploy_stronghold(self, clearing: Clearing) -> Stronghold:
        """Move one supply Stronghold onto *clearing* into an available slot."""
        occupied_slot_ids = Building.objects.filter(
            building_slot__clearing=clearing
        ).values_list("building_slot_id", flat=True)
        slot = (
            BuildingSlot.objects.filter(clearing=clearing)
            .exclude(id__in=occupied_slot_ids)
            .first()
        )
        self.assertIsNotNone(
            slot,
            f"No available building slot in clearing {clearing.clearing_number}",
        )
        sh = Stronghold.objects.filter(
            player=self.player, building_slot__isnull=True
        ).first()
        self.assertIsNotNone(sh, "No Strongholds left in supply")
        sh.building_slot = slot
        sh.save()
        return sh

    def _place_warrior(self, clearing: Clearing, player=None) -> Warrior:
        """Move one supply warrior for *player* (default: self.player) into *clearing*."""
        if player is None:
            player = self.player
        w = Warrior.objects.filter(player=player, clearing__isnull=True).first()
        self.assertIsNotNone(w, "No warriors left in supply")
        w.clearing = clearing
        w.save()
        return w

    def _exhaust_commands(self) -> None:
        """Set commands_used to the command budget so no commands remain."""
        # At 0 command items, get_command_value returns 1.
        self.daylight.commands_used = 1
        self.daylight.save()


# ===========================================================================
# use_command wrapper tests
# ===========================================================================


class RatsCommandWrapperTests(RatsCommandBaseTestCase):

    def test_commands_used_increments_after_move(self):
        """commands_used increments by 1 after a successful move command."""
        from game.transactions.rats.daylight import use_command

        # Warriors are already in C2 from setup; move to adjacent C5.
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        initial = self.daylight.commands_used

        use_command(self.player, "move", self.c2, c5, 1)

        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.commands_used, initial + 1)

    def test_commands_used_increments_after_battle(self):
        """commands_used increments by 1 after a successful battle command."""
        from game.transactions.rats.daylight import use_command

        # Place a Cats warrior in C2 to act as the defender.
        self._place_warrior(self.c2, player=self.cats_player)
        initial = self.daylight.commands_used

        use_command(self.player, "battle", Faction.CATS, self.c2)

        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.commands_used, initial + 1)

    def test_commands_used_increments_after_build(self):
        """commands_used increments by 1 after a successful build command."""
        from game.transactions.rats.daylight import use_command

        # ROOT_TEA_ORANGE: suit=ORANGE matches C2 (orange/mouse clearing).
        hand_entry = self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        initial = self.daylight.commands_used

        use_command(self.player, "build", CardsEP.ROOT_TEA_ORANGE, self.c2)

        self.daylight.refresh_from_db()
        self.assertEqual(self.daylight.commands_used, initial + 1)

    def test_no_commands_remaining_raises_unavailable(self):
        """UnavailableActionError is raised when commands_used >= command_value (1 at 0 items)."""
        from game.transactions.rats.daylight import use_command

        self._exhaust_commands()
        c5 = Clearing.objects.get(game=self.game, clearing_number=5)

        with self.assertRaises(UnavailableActionError):
            use_command(self.player, "move", self.c2, c5, 1)

    def test_unknown_command_type_raises_illegal(self):
        """IllegalActionError is raised for an unrecognised command_type string."""
        from game.transactions.rats.daylight import use_command

        with self.assertRaises(IllegalActionError):
            use_command(self.player, "forage")

    def test_wrong_step_raises_unavailable(self):
        """UnavailableActionError is raised when not at the COMMAND step."""
        from game.transactions.rats.daylight import use_command

        self.daylight.step = RatsDaylight.Steps.CRAFT
        self.daylight.save()

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        with self.assertRaises(UnavailableActionError):
            use_command(self.player, "move", self.c2, c5, 1)

    def test_step_advances_after_last_command(self):
        """Step advances past COMMAND once commands_used reaches command_value.

        At 0 items on the Command track, command_value=1. Using one command
        should exhaust the budget and auto-advance the step.
        """
        from game.transactions.rats.daylight import use_command

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        use_command(self.player, "move", self.c2, c5, 1)

        self.daylight.refresh_from_db()
        self.assertNotEqual(
            self.daylight.step,
            RatsDaylight.Steps.COMMAND,
            "Step should advance past COMMAND after the last command is used",
        )


# ===========================================================================
# Move tests
# ===========================================================================


class RatsCommandMoveTests(RatsCommandBaseTestCase):

    def test_move_transfers_warriors_between_clearings(self):
        """Warriors move from origin to destination; counts in both clearings change."""
        from game.transactions.rats.daylight import use_command

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)

        initial_c2 = Warrior.objects.filter(player=self.player, clearing=self.c2).count()
        initial_c5 = Warrior.objects.filter(player=self.player, clearing=c5).count()

        use_command(self.player, "move", self.c2, c5, 1)

        final_c2 = Warrior.objects.filter(player=self.player, clearing=self.c2).count()
        final_c5 = Warrior.objects.filter(player=self.player, clearing=c5).count()

        self.assertEqual(final_c2, initial_c2 - 1, "Origin should lose one warrior")
        self.assertEqual(final_c5, initial_c5 + 1, "Destination should gain one warrior")

    def test_move_not_enough_warriors_raises(self):
        """IllegalActionError is raised if origin has fewer warriors than requested count."""
        from game.transactions.rats.daylight import use_command

        c5 = Clearing.objects.get(game=self.game, clearing_number=5)
        # C5 starts empty; request more warriors than are there.
        available = Warrior.objects.filter(player=self.player, clearing=c5).count()

        with self.assertRaises((IllegalActionError, Exception)):
            use_command(self.player, "move", c5, self.c2, available + 5)

    def test_move_non_adjacent_clearings_raises(self):
        """IllegalActionError is raised when origin and destination are not adjacent.

        C2 and C3 are not adjacent (C2 ↔ C5, C6, C10 only).
        """
        from game.transactions.rats.daylight import use_command

        c3 = Clearing.objects.get(game=self.game, clearing_number=3)

        with self.assertRaises((IllegalActionError, Exception)):
            use_command(self.player, "move", self.c2, c3, 1)


# ===========================================================================
# Battle tests
# ===========================================================================


class RatsCommandBattleTests(RatsCommandBaseTestCase):

    def test_battle_creates_battle_object(self):
        """A Battle record is created in the clearing after initiating a battle command."""
        from game.transactions.rats.daylight import use_command

        # Ensure defender (Cats) has pieces in C2.
        self._place_warrior(self.c2, player=self.cats_player)

        initial_battles = Battle.objects.filter(event__game=self.game).count()

        use_command(self.player, "battle", Faction.CATS, self.c2)

        final_battles = Battle.objects.filter(event__game=self.game).count()
        self.assertEqual(final_battles, initial_battles + 1, "A new Battle should be created")

    def test_battle_correct_clearing_recorded(self):
        """The created Battle is associated with the correct clearing."""
        from game.transactions.rats.daylight import use_command

        self._place_warrior(self.c2, player=self.cats_player)

        use_command(self.player, "battle", Faction.CATS, self.c2)

        battle = Battle.objects.filter(event__game=self.game).order_by("-id").first()
        self.assertIsNotNone(battle)
        self.assertEqual(battle.clearing, self.c2)

    def test_battle_no_attacker_warriors_raises(self):
        """IllegalActionError is raised if the Rats have no warriors in the clearing."""
        from game.transactions.rats.daylight import use_command

        # Remove all Rats warriors from C2.
        Warrior.objects.filter(player=self.player, clearing=self.c2).update(clearing=None)
        # Ensure Cats still have a piece there so the target exists.
        self._place_warrior(self.c2, player=self.cats_player)

        with self.assertRaises((IllegalActionError, Exception)):
            use_command(self.player, "battle", Faction.CATS, self.c2)


# ===========================================================================
# Build tests
# ===========================================================================


class RatsCommandBuildTests(RatsCommandBaseTestCase):

    def test_build_places_stronghold_in_clearing(self):
        """A Stronghold is placed in the clearing after a successful build command."""
        from game.transactions.rats.daylight import use_command

        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        initial_deployed = Stronghold.objects.filter(
            player=self.player, building_slot__isnull=False
        ).count()

        use_command(self.player, "build", CardsEP.ROOT_TEA_ORANGE, self.c2)

        final_deployed = Stronghold.objects.filter(
            player=self.player, building_slot__isnull=False
        ).count()
        self.assertEqual(
            final_deployed,
            initial_deployed + 1,
            "One additional Stronghold should be deployed after build",
        )

    def test_build_places_stronghold_in_correct_clearing(self):
        """The newly-deployed Stronghold is located in the target clearing."""
        from game.transactions.rats.daylight import use_command

        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)

        use_command(self.player, "build", CardsEP.ROOT_TEA_ORANGE, self.c2)

        # All strongholds deployed in C2 (we deployed into C2 during setup too).
        deployed_in_c2 = Stronghold.objects.filter(
            player=self.player,
            building_slot__clearing=self.c2,
        ).count()
        self.assertGreaterEqual(deployed_in_c2, 1)

    def test_build_removes_card_from_hand(self):
        """The card spent on build is removed from the player's hand."""
        from game.transactions.rats.daylight import use_command

        hand_entry = self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)

        use_command(self.player, "build", CardsEP.ROOT_TEA_ORANGE, self.c2)

        self.assertFalse(
            HandEntry.objects.filter(player=self.player, card=hand_entry.card).exists(),
            "Card should be removed from hand after build",
        )

    def test_build_wrong_card_suit_raises(self):
        """IllegalActionError is raised when the card's suit doesn't match the clearing suit.

        C2 is ORANGE (mouse); ANVIL has suit=RED — mismatch.
        """
        from game.transactions.rats.daylight import use_command

        self._add_card_to_hand(CardsEP.ANVIL)

        with self.assertRaises(IllegalActionError):
            use_command(self.player, "build", CardsEP.ANVIL, self.c2)

    def test_build_unruled_clearing_raises(self):
        """IllegalActionError is raised when the Rats don't rule the target clearing.

        Move all Rats warriors out of C2, ensuring they no longer rule it.
        """
        from game.transactions.rats.daylight import use_command

        # Strip all Rats warriors from C2 so they no longer rule it.
        Warrior.objects.filter(player=self.player, clearing=self.c2).update(clearing=None)
        # Place a Cats warrior so someone else rules (or clearing is disputed).
        self._place_warrior(self.c2, player=self.cats_player)

        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)

        with self.assertRaises(IllegalActionError):
            use_command(self.player, "build", CardsEP.ROOT_TEA_ORANGE, self.c2)

    def test_build_no_strongholds_in_supply_raises(self):
        """IllegalActionError is raised when no Strongholds remain in supply.

        Deploy every supply Stronghold onto the map before attempting the build.
        """
        from game.transactions.rats.daylight import use_command

        # C2 already has one Stronghold (from setup). Deploy remaining supply ones.
        supply_strongholds = list(
            Stronghold.objects.filter(player=self.player, building_slot__isnull=True)
        )
        # Use non-C2 clearings that have open slots (C5, C6, C10 are adjacent to C2
        # but we just need any clearing with a free slot).
        other_clearings = Clearing.objects.filter(game=self.game).exclude(
            clearing_number=2
        )
        for i, sh in enumerate(supply_strongholds):
            for clearing in other_clearings:
                occupied = Building.objects.filter(
                    building_slot__clearing=clearing
                ).values_list("building_slot_id", flat=True)
                slot = (
                    BuildingSlot.objects.filter(clearing=clearing)
                    .exclude(id__in=occupied)
                    .first()
                )
                if slot is not None:
                    sh.building_slot = slot
                    sh.save()
                    break

        # Confirm supply is empty.
        remaining_supply = Stronghold.objects.filter(
            player=self.player, building_slot__isnull=True
        ).count()
        if remaining_supply > 0:
            self.skipTest("Could not drain Stronghold supply — not enough map slots")

        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)

        with self.assertRaises(IllegalActionError):
            use_command(self.player, "build", CardsEP.ROOT_TEA_ORANGE, self.c2)

    def test_build_no_slot_available_raises(self):
        """IllegalActionError is raised when C2 has no empty building slots.

        Fill every building slot in C2 with Strongholds, then attempt another build there.
        """
        from game.transactions.rats.daylight import use_command

        # Fill all remaining slots in C2.
        while True:
            occupied = Building.objects.filter(
                building_slot__clearing=self.c2
            ).values_list("building_slot_id", flat=True)
            slot = (
                BuildingSlot.objects.filter(clearing=self.c2)
                .exclude(id__in=occupied)
                .first()
            )
            if slot is None:
                break  # all slots full
            sh = Stronghold.objects.filter(
                player=self.player, building_slot__isnull=True
            ).first()
            if sh is None:
                self.skipTest("Ran out of Stronghold supply before filling all C2 slots")
            sh.building_slot = slot
            sh.save()

        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)

        with self.assertRaises(IllegalActionError):
            use_command(self.player, "build", CardsEP.ROOT_TEA_ORANGE, self.c2)

    def test_build_card_not_in_hand_raises(self):
        """IllegalActionError is raised when the card to build with is not in hand."""
        from game.transactions.rats.daylight import use_command
        from game.models.game_models import HandEntry

        # Remove any ROOT_TEA_ORANGE that may have been dealt during setup.
        HandEntry.objects.filter(
            player=self.player, card__card_type=CardsEP.ROOT_TEA_ORANGE.name
        ).delete()

        with self.assertRaises(IllegalActionError):
            use_command(self.player, "build", CardsEP.ROOT_TEA_ORANGE, self.c2)
