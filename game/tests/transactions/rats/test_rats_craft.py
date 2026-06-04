"""Tests for the Rats CRAFT step transaction.

Scenarios covered:
- Craft succeeds: card deducted from hand, item placed on hoard (command or prowess track)
- Crafting marks the Stronghold crafted_with=True
- A Stronghold already marked crafted_with=True cannot be used again (raises error)
- Cannot craft from a clearing with no Stronghold (raises error)
- Cannot craft a card not in hand (raises error)
- Card suit must match clearing suit (raises error)
- Command-track items (BOOTS, BAG, COIN) route to CommandItemEntry
- Prowess-track items (HAMMER, TEA, SWORD, CROSSBOW) route to ProwessItemEntry
- end_crafting advances step past CRAFT

Map reference (1-indexed clearings):
  Fox  (r): 1, 6, 8, 12
  Rabbit (y): 3, 4, 5, 10
  Mouse (o): 2, 7, 9, 11

Corner clearings: 1–4.  pick_corner uses C2 (mouse/orange) → warlord + 4 warriors + 1 stronghold.
"""

from django.test import TestCase

from game.errors import IllegalActionError, UnavailableActionError
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.enums import ItemTypes
from game.models.game_models import (
    Building,
    BuildingSlot,
    Card,
    CraftableItemEntry,
    CraftedItemEntry,
    Clearing,
    Faction,
    Game,
    HandEntry,
    Item,
)
from game.models.rats.buildings import Stronghold
from game.models.rats.player import CommandItemEntry, ProwessItemEntry
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsTurn
from game.models.events.setup import GameSimpleSetup
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------

class RatsCraftBaseTestCase(TestCase):
    def setUp(self):
        self.game = GameSetupFactory(factions=[Faction.RATS, Faction.CATS])
        self.player = self.game.players.get(faction=Faction.RATS)

        game_setup = GameSimpleSetup.objects.get(game=self.game)
        game_setup.status = GameSimpleSetup.GameSetupStatus.RATS_SETUP
        game_setup.save()

        # C2 is a Mouse (orange) clearing — the setup stronghold lands here.
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
        self.daylight.step = RatsDaylight.Steps.CRAFT
        self.daylight.save()

        # Clear any cards dealt during setup so hand-state assertions are reliable.
        from game.models.game_models import HandEntry
        HandEntry.objects.filter(player=self.player).delete()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _stronghold_in_c2(self) -> Stronghold:
        """Return the Stronghold placed in C2 during setup."""
        return Stronghold.objects.get(
            player=self.player,
            building_slot__clearing=self.c2,
        )

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
        sh.crafted_with = False
        sh.save()
        return sh

    def _ensure_item_in_pool(self, item_type: ItemTypes) -> Item:
        """Ensure an item of *item_type* is in the craftable pool; return it."""
        entry = CraftableItemEntry.objects.filter(
            game=self.game, item__item_type=item_type.value
        ).first()
        if entry is None:
            item = Item.objects.create(game=self.game, item_type=item_type.value)
            entry = CraftableItemEntry.objects.create(game=self.game, item=item)
        return entry.item


# ===========================================================================
# Basic success path
# ===========================================================================

class RatsCraftSuccessTests(RatsCraftBaseTestCase):

    def test_craft_removes_card_from_hand(self):
        """After crafting, the used card is no longer in the player's hand."""
        from game.transactions.rats.daylight import craft_card

        # ROOT_TEA_ORANGE: orange suit, cost [ORANGE], item=TEA
        self._ensure_item_in_pool(ItemTypes.TEA)
        hand_entry = self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        stronghold = self._stronghold_in_c2()
        stronghold.crafted_with = False
        stronghold.save()

        craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [stronghold])

        self.assertFalse(
            HandEntry.objects.filter(player=self.player, card=hand_entry.card).exists(),
            "Card should be removed from hand after crafting",
        )

    def test_craft_marks_stronghold_crafted_with(self):
        """The Stronghold used for crafting is marked crafted_with=True."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.TEA)
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        stronghold = self._stronghold_in_c2()
        stronghold.crafted_with = False
        stronghold.save()

        craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [stronghold])

        stronghold.refresh_from_db()
        self.assertTrue(
            stronghold.crafted_with,
            "Stronghold should be marked crafted_with=True after use",
        )

    def test_craft_item_placed_in_hoard(self):
        """Crafting with add_to_hoard=True places the item on the hoard track."""
        from game.transactions.rats.daylight import craft_card

        # ROOT_TEA_ORANGE → TEA → prowess track
        self._ensure_item_in_pool(ItemTypes.TEA)
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        stronghold = self._stronghold_in_c2()
        stronghold.crafted_with = False
        stronghold.save()

        before_prowess = ProwessItemEntry.objects.filter(player=self.player).count()

        craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [stronghold], add_to_hoard=True)

        after_prowess = ProwessItemEntry.objects.filter(player=self.player).count()
        self.assertEqual(
            after_prowess,
            before_prowess + 1,
            "TEA item should be added to prowess track",
        )


# ===========================================================================
# Item routing: command track vs prowess track
# ===========================================================================

class RatsCraftHoardRoutingTests(RatsCraftBaseTestCase):
    """Verify each item type routes to the correct hoard track."""

    def _craft_item_card(self, card_enum: CardsEP, item_type: ItemTypes):
        """Helper: set up a stronghold matching the card's cost suit and craft it."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(item_type)
        self._add_card_to_hand(card_enum)

        # Find a stronghold in a clearing whose suit satisfies the first cost element.
        cost_suits = [s.value for s in card_enum.value.cost]
        first_suit = cost_suits[0]

        # Use the C2 stronghold if its clearing suit matches; otherwise deploy one.
        sh = self._stronghold_in_c2()
        sh.crafted_with = False
        sh.save()
        if sh.building_slot.clearing.suit != first_suit:
            # Retract C2 stronghold and deploy in a clearing with the right suit.
            sh.building_slot = None
            sh.save()
            target = Clearing.objects.filter(
                game=self.game, suit=first_suit
            ).first()
            self.assertIsNotNone(
                target,
                f"No clearing with suit '{first_suit}' found on map",
            )
            sh = self._deploy_stronghold(target)

        craft_card(self.player, card_enum, [sh])
        return sh

    # --- Command track items ---

    def test_boots_goes_to_command_track(self):
        """BOOTS item is placed on the CommandItemEntry track."""
        # TRAVEL_GEAR_ORANGE: orange suit, cost [YELLOW], item=BOOTS
        # Use A_VISIT_TO_FRIENDS (yellow, cost [YELLOW], BOOTS) instead for easier setup.
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.BOOTS)

        # TRAVEL_GEAR_ORANGE is orange suit, cost=[YELLOW] — deploy stronghold in yellow clearing.
        c3 = Clearing.objects.get(game=self.game, clearing_number=3)  # rabbit/yellow
        # Retract C2 stronghold, deploy in C3
        sh = self._stronghold_in_c2()
        sh.building_slot = None
        sh.save()
        sh = self._deploy_stronghold(c3)
        sh.crafted_with = False
        sh.save()

        self._add_card_to_hand(CardsEP.TRAVEL_GEAR_ORANGE)
        before = CommandItemEntry.objects.filter(player=self.player).count()

        craft_card(self.player, CardsEP.TRAVEL_GEAR_ORANGE, [sh], add_to_hoard=True)

        after = CommandItemEntry.objects.filter(player=self.player).count()
        self.assertEqual(after, before + 1, "BOOTS should be added to command track")
        self.assertEqual(
            ProwessItemEntry.objects.filter(player=self.player).count(),
            0,
            "BOOTS should NOT be added to prowess track",
        )

    def test_bag_goes_to_command_track(self):
        """BAG item is placed on the CommandItemEntry track."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.BAG)
        # MOUSE_IN_A_SACK: orange suit, cost=[ORANGE], item=BAG
        self._add_card_to_hand(CardsEP.MOUSE_IN_A_SACK)
        stronghold = self._stronghold_in_c2()  # C2 is orange — matches cost
        stronghold.crafted_with = False
        stronghold.save()

        before = CommandItemEntry.objects.filter(player=self.player).count()
        craft_card(self.player, CardsEP.MOUSE_IN_A_SACK, [stronghold], add_to_hoard=True)

        self.assertEqual(
            CommandItemEntry.objects.filter(player=self.player).count(),
            before + 1,
            "BAG should be added to command track",
        )

    def test_coin_goes_to_command_track(self):
        """COIN item is placed on the CommandItemEntry track."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.COIN)
        # PROTECTION_RACKET: red suit, cost=[YELLOW, YELLOW], item=COIN
        # Use BAKE_SALE: yellow, cost=[YELLOW, YELLOW], item=COIN
        # Need 2 strongholds in yellow clearings.
        sh_c2 = self._stronghold_in_c2()
        sh_c2.building_slot = None
        sh_c2.save()

        c3 = Clearing.objects.get(game=self.game, clearing_number=3)  # rabbit/yellow
        c4 = Clearing.objects.get(game=self.game, clearing_number=4)  # rabbit/yellow
        sh1 = self._deploy_stronghold(c3)
        sh2 = self._deploy_stronghold(c4)
        sh1.crafted_with = False
        sh1.save()
        sh2.crafted_with = False
        sh2.save()

        self._add_card_to_hand(CardsEP.BAKE_SALE)
        before = CommandItemEntry.objects.filter(player=self.player).count()
        craft_card(self.player, CardsEP.BAKE_SALE, [sh1, sh2], add_to_hoard=True)

        self.assertEqual(
            CommandItemEntry.objects.filter(player=self.player).count(),
            before + 1,
            "COIN should be added to command track",
        )

    # --- Prowess track items ---

    def test_tea_goes_to_prowess_track(self):
        """TEA item is placed on the ProwessItemEntry track."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.TEA)
        # ROOT_TEA_ORANGE: orange suit, cost=[ORANGE], item=TEA — C2 matches.
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        stronghold = self._stronghold_in_c2()
        stronghold.crafted_with = False
        stronghold.save()

        before = ProwessItemEntry.objects.filter(player=self.player).count()
        craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [stronghold], add_to_hoard=True)

        self.assertEqual(
            ProwessItemEntry.objects.filter(player=self.player).count(),
            before + 1,
            "TEA should be added to prowess track",
        )
        self.assertEqual(
            CommandItemEntry.objects.filter(player=self.player).count(),
            0,
            "TEA should NOT be added to command track",
        )

    def test_sword_goes_to_prowess_track(self):
        """SWORD item is placed on the ProwessItemEntry track."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.SWORD)
        # SWORD (orange): cost=[RED, RED], item=SWORD — need 2 fox clearings.
        sh_c2 = self._stronghold_in_c2()
        sh_c2.building_slot = None
        sh_c2.save()

        c1 = Clearing.objects.get(game=self.game, clearing_number=1)  # fox/red
        c6 = Clearing.objects.get(game=self.game, clearing_number=6)  # fox/red
        sh1 = self._deploy_stronghold(c1)
        sh2 = self._deploy_stronghold(c6)
        sh1.crafted_with = False
        sh1.save()
        sh2.crafted_with = False
        sh2.save()

        self._add_card_to_hand(CardsEP.SWORD)
        before = ProwessItemEntry.objects.filter(player=self.player).count()
        craft_card(self.player, CardsEP.SWORD, [sh1, sh2], add_to_hoard=True)

        self.assertEqual(
            ProwessItemEntry.objects.filter(player=self.player).count(),
            before + 1,
            "SWORD should be added to prowess track",
        )

    def test_hammer_goes_to_prowess_track(self):
        """HAMMER item is placed on the ProwessItemEntry track."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.HAMMER)
        # ANVIL: red suit, cost=[RED], item=HAMMER — need 1 fox clearing.
        sh_c2 = self._stronghold_in_c2()
        sh_c2.building_slot = None
        sh_c2.save()

        c1 = Clearing.objects.get(game=self.game, clearing_number=1)  # fox/red
        sh = self._deploy_stronghold(c1)
        sh.crafted_with = False
        sh.save()

        self._add_card_to_hand(CardsEP.ANVIL)
        before = ProwessItemEntry.objects.filter(player=self.player).count()
        craft_card(self.player, CardsEP.ANVIL, [sh], add_to_hoard=True)

        self.assertEqual(
            ProwessItemEntry.objects.filter(player=self.player).count(),
            before + 1,
            "HAMMER should be added to prowess track",
        )

    def test_crossbow_goes_to_prowess_track(self):
        """CROSSBOW item is placed on the ProwessItemEntry track."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.CROSSBOW)
        # CROSSBOW_ORANGE: orange suit, cost=[RED], item=CROSSBOW — need 1 fox clearing.
        sh_c2 = self._stronghold_in_c2()
        sh_c2.building_slot = None
        sh_c2.save()

        c1 = Clearing.objects.get(game=self.game, clearing_number=1)  # fox/red
        sh = self._deploy_stronghold(c1)
        sh.crafted_with = False
        sh.save()

        self._add_card_to_hand(CardsEP.CROSSBOW_ORANGE)
        before = ProwessItemEntry.objects.filter(player=self.player).count()
        craft_card(self.player, CardsEP.CROSSBOW_ORANGE, [sh], add_to_hoard=True)

        self.assertEqual(
            ProwessItemEntry.objects.filter(player=self.player).count(),
            before + 1,
            "CROSSBOW should be added to prowess track",
        )


# ===========================================================================
# Error cases
# ===========================================================================

class RatsCraftErrorTests(RatsCraftBaseTestCase):

    def test_stronghold_already_used_raises(self):
        """A Stronghold with crafted_with=True cannot be used again; raises IllegalActionError."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.TEA)
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        stronghold = self._stronghold_in_c2()
        stronghold.crafted_with = True
        stronghold.save()

        with self.assertRaises(IllegalActionError):
            craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [stronghold])

    def test_no_stronghold_in_clearing_raises(self):
        """Passing a Stronghold not in any clearing (supply) raises IllegalActionError."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.TEA)
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)

        # Retract the setup stronghold to supply
        stronghold = self._stronghold_in_c2()
        stronghold.building_slot = None
        stronghold.crafted_with = False
        stronghold.save()

        with self.assertRaises(IllegalActionError):
            craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [stronghold])

    def test_card_not_in_hand_raises(self):
        """Attempting to craft a card not in the player's hand raises IllegalActionError."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.TEA)
        # Do NOT add the card to hand
        stronghold = self._stronghold_in_c2()
        stronghold.crafted_with = False
        stronghold.save()

        with self.assertRaises(IllegalActionError):
            craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [stronghold])

    def test_wrong_suit_raises(self):
        """Stronghold suit mismatch with card cost raises IllegalActionError."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.HAMMER)
        # ANVIL costs [RED]; C2 is orange — suit mismatch.
        self._add_card_to_hand(CardsEP.ANVIL)
        stronghold = self._stronghold_in_c2()  # orange clearing
        stronghold.crafted_with = False
        stronghold.save()

        with self.assertRaises(IllegalActionError):
            craft_card(self.player, CardsEP.ANVIL, [stronghold])

    def test_too_few_strongholds_raises(self):
        """Providing fewer Strongholds than the card's cost requires raises IllegalActionError."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.COIN)
        # BAKE_SALE costs [YELLOW, YELLOW] — 2 pieces needed; provide only 1.
        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        sh_c2 = self._stronghold_in_c2()
        sh_c2.building_slot = None
        sh_c2.save()
        sh = self._deploy_stronghold(c3)
        sh.crafted_with = False
        sh.save()

        self._add_card_to_hand(CardsEP.BAKE_SALE)

        with self.assertRaises(IllegalActionError):
            craft_card(self.player, CardsEP.BAKE_SALE, [sh])

    def test_wrong_step_raises(self):
        """Calling craft_card when not in the CRAFT step raises UnavailableActionError."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.TEA)
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        stronghold = self._stronghold_in_c2()
        stronghold.crafted_with = False
        stronghold.save()

        self.daylight.step = RatsDaylight.Steps.COMMAND
        self.daylight.save()

        with self.assertRaises(UnavailableActionError):
            craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [stronghold])

    def test_duplicate_stronghold_raises(self):
        """Passing the same Stronghold twice raises IllegalActionError."""
        from game.transactions.rats.daylight import craft_card

        self._ensure_item_in_pool(ItemTypes.COIN)
        # BAKE_SALE costs [YELLOW, YELLOW]; try to satisfy with the same piece twice.
        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        sh_c2 = self._stronghold_in_c2()
        sh_c2.building_slot = None
        sh_c2.save()
        sh = self._deploy_stronghold(c3)
        sh.crafted_with = False
        sh.save()

        self._add_card_to_hand(CardsEP.BAKE_SALE)

        with self.assertRaises(IllegalActionError):
            craft_card(self.player, CardsEP.BAKE_SALE, [sh, sh])


# ===========================================================================
# end_crafting
# ===========================================================================

class RatsCraftEndTests(RatsCraftBaseTestCase):

    def test_end_crafting_advances_step(self):
        """end_crafting advances the daylight step past CRAFT."""
        from game.transactions.rats.daylight import end_crafting

        end_crafting(self.player)

        self.daylight.refresh_from_db()
        self.assertNotEqual(
            self.daylight.step,
            RatsDaylight.Steps.CRAFT,
            "Step should advance past CRAFT after end_crafting",
        )

    def test_end_crafting_wrong_step_raises(self):
        """Calling end_crafting when not in CRAFT step raises UnavailableActionError."""
        from game.transactions.rats.daylight import end_crafting

        self.daylight.step = RatsDaylight.Steps.COMMAND
        self.daylight.save()

        with self.assertRaises(UnavailableActionError):
            end_crafting(self.player)


# ===========================================================================
# Contempt for Trade: hoard vs score choice
# ===========================================================================


class RatsCraftContemptForTradeTests(RatsCraftBaseTestCase):
    """Verify Contempt for Trade: add_to_hoard=True vs add_to_hoard=False."""

    def _setup_tea_craft(self):
        """Return the C2 stronghold ready for crafting ROOT_TEA_ORANGE."""
        from game.transactions.rats.daylight import craft_card  # noqa: F401
        self._ensure_item_in_pool(ItemTypes.TEA)
        self._add_card_to_hand(CardsEP.ROOT_TEA_ORANGE)
        sh = self._stronghold_in_c2()
        sh.crafted_with = False
        sh.save()
        return sh

    def test_add_to_hoard_places_item_on_track(self):
        """add_to_hoard=True routes the item to the prowess track."""
        from game.transactions.rats.daylight import craft_card

        sh = self._setup_tea_craft()
        before = ProwessItemEntry.objects.filter(player=self.player).count()

        craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [sh], add_to_hoard=True)

        self.assertEqual(
            ProwessItemEntry.objects.filter(player=self.player).count(),
            before + 1,
            "Item should be on prowess track when add_to_hoard=True",
        )
        # Item should NOT be in the generic crafted items box
        self.assertFalse(
            CraftedItemEntry.objects.filter(player=self.player).exists(),
            "Item should NOT appear in CraftedItemEntry when add_to_hoard=True",
        )

    def test_add_to_hoard_scores_zero_vp(self):
        """add_to_hoard=True scores 0 VP (Contempt for Trade)."""
        from game.transactions.rats.daylight import craft_card

        sh = self._setup_tea_craft()
        score_before = self.player.score

        craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [sh], add_to_hoard=True)

        self.player.refresh_from_db()
        self.assertEqual(
            self.player.score,
            score_before,
            "Crafting with add_to_hoard=True should score 0 VP",
        )

    def test_score_removes_item_permanently(self):
        """add_to_hoard=False scores listed VP and deletes the item from the game entirely."""
        from game.transactions.rats.daylight import craft_card

        sh = self._setup_tea_craft()
        tea_item = self._ensure_item_in_pool(ItemTypes.TEA)  # get the Item pk
        score_before = self.player.score

        craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [sh], add_to_hoard=False)

        self.player.refresh_from_db()
        # Should have scored the listed points (TEA = 2 VP)
        self.assertGreater(
            self.player.score,
            score_before,
            "Crafting with add_to_hoard=False should score VP",
        )
        # Item is deleted from the game — not in CraftedItemEntry, not on hoard track
        from game.models.game_models import Item
        self.assertFalse(
            Item.objects.filter(pk=tea_item.pk).exists(),
            "Item should be deleted from the game when add_to_hoard=False",
        )
        self.assertFalse(
            CraftedItemEntry.objects.filter(player=self.player).exists(),
            "Rats do not have a CraftedItemEntry box",
        )
        self.assertEqual(
            ProwessItemEntry.objects.filter(player=self.player).count(),
            0,
            "Item should NOT be on prowess track when add_to_hoard=False",
        )

    def test_default_does_not_add_to_hoard(self):
        """Default (no add_to_hoard kwarg) deletes the item and scores VP — same as add_to_hoard=False."""
        from game.transactions.rats.daylight import craft_card

        sh = self._setup_tea_craft()
        tea_item = self._ensure_item_in_pool(ItemTypes.TEA)
        score_before = self.player.score

        craft_card(self.player, CardsEP.ROOT_TEA_ORANGE, [sh])

        self.player.refresh_from_db()
        from game.models.game_models import Item
        self.assertGreater(
            self.player.score,
            score_before,
            "Default craft should score VP",
        )
        self.assertFalse(
            Item.objects.filter(pk=tea_item.pk).exists(),
            "Item should be deleted from the game on default (score) craft",
        )
        self.assertEqual(
            ProwessItemEntry.objects.filter(player=self.player).count(),
            0,
            "Default craft should NOT add item to prowess track",
        )
        self.assertFalse(
            CraftedItemEntry.objects.filter(player=self.player).exists(),
            "Rats do not have a CraftedItemEntry box",
        )

    def test_non_item_card_unaffected_by_add_to_hoard(self):
        """Non-item cards (e.g. crafted-card abilities) are not affected by add_to_hoard."""
        from game.transactions.rats.daylight import craft_card
        from game.models.game_models import CraftedCardEntry

        # RABBIT_PARTISANS: suit=YELLOW, cost=[YELLOW], no item — always has matching clearings.
        non_item_card = CardsEP.RABBIT_PARTISANS

        self._add_card_to_hand(non_item_card)
        cost = non_item_card.value.cost
        # Deploy strongholds matching the cost suits
        strongholds = []
        for suit in cost:
            target = Clearing.objects.filter(game=self.game, suit=suit.value).first()
            self.assertIsNotNone(target, f"No clearing with suit {suit}")
            sh = self._deploy_stronghold(target)
            sh.crafted_with = False
            sh.save()
            strongholds.append(sh)

        craft_card(self.player, non_item_card, strongholds, add_to_hoard=True)

        # Card should land in CraftedCardEntry regardless of add_to_hoard
        self.assertTrue(
            CraftedCardEntry.objects.filter(player=self.player).exists(),
            "Non-item card should go to CraftedCardEntry even when add_to_hoard=True",
        )
