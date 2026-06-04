"""Tests for the RECRUIT step transactions and queries.

Scenarios covered:
- Warlord placement: places min(prowess, supply) warriors
- Stronghold auto-placement: enough supply for all strongholds
- Stronghold auto-placement: insufficient supply but all strongholds in one clearing
- Stronghold choice required: insufficient supply across multiple clearings
- recruit_stronghold: places warrior, marks stronghold used, auto-finishes when possible
- recruit_stronghold: stays at RECRUIT when more choices remain
- recruit_stronghold: error on wrong clearing / empty supply
- reset_rats_turn resets recruit_used

Map reference (1-indexed clearings):
  Fox  (r): 1, 6, 8, 12
  Rabbit (y): 3, 4, 5, 10
  Mouse (o): 2, 7, 9, 11

Corner clearings: 1–4.  pick_corner uses C2 (mouse) → warlord + 4 warriors + 1 stronghold.
"""

from django.test import TestCase

from game.errors import IllegalActionError, UnavailableActionError
from game.models.game_models import (
    Building,
    BuildingSlot,
    Clearing,
    Faction,
    Game,
    Player,
    Warrior,
)
from game.models.rats.buildings import Stronghold
from game.models.rats.tokens import Warlord
from game.models.rats.turn import RatsBirdsong, RatsTurn
from game.models.events.setup import GameSimpleSetup
from game.tests.my_factories import GameSetupFactory
from game.transactions.rats_setup import (
    confirm_completed_setup as rats_confirm_setup,
    pick_corner as rats_pick_corner,
)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------

class RecruitBaseTestCase(TestCase):
    def setUp(self):
        self.game = GameSetupFactory(factions=[Faction.RATS, Faction.CATS])
        self.player = self.game.players.get(faction=Faction.RATS)

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
        self.birdsong = self.rats_turn.birdsong.first()
        self.birdsong.step = RatsBirdsong.Steps.RECRUIT
        self.birdsong.save()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _regular_warrior_count(self, clearing=None) -> int:
        qs = Warrior.objects.filter(player=self.player, warlord__isnull=True)
        if clearing is not None:
            qs = qs.filter(clearing=clearing)
        else:
            qs = qs.filter(clearing__isnull=True)
        return qs.count()

    def _drain_supply_to(self, remaining: int):
        """Move warriors from supply to C2 until only *remaining* are left."""
        excess = self._regular_warrior_count() - remaining
        if excess <= 0:
            return
        warriors = list(
            Warrior.objects.filter(
                player=self.player, clearing__isnull=True, warlord__isnull=True
            )[:excess]
        )
        for w in warriors:
            w.clearing = self.c2
            w.save()

    def _deploy_stronghold(self, clearing: Clearing) -> Stronghold:
        """Move one supply stronghold onto *clearing*, using an available slot."""
        occupied_slot_ids = Building.objects.filter(
            building_slot__clearing=clearing
        ).values_list("building_slot_id", flat=True)
        slot = (
            BuildingSlot.objects.filter(clearing=clearing)
            .exclude(id__in=occupied_slot_ids)
            .first()
        )
        self.assertIsNotNone(
            slot, f"No available building slot in clearing {clearing.clearing_number}"
        )
        sh = Stronghold.objects.filter(
            player=self.player, building_slot__isnull=True
        ).first()
        self.assertIsNotNone(sh, "No strongholds left in supply")
        sh.building_slot = slot
        sh.recruit_used = False  # always start fresh
        sh.save()
        return sh

    def _warlord(self) -> Warlord:
        return Warlord.objects.get(player=self.player)

    def _send_warlord_to_supply(self):
        w = self._warlord()
        w.clearing = None
        w.save()


# ===========================================================================
# Phase 1 — Warlord placement
# ===========================================================================

class WarlordRecruitTests(RecruitBaseTestCase):

    def test_places_prowess_value_warriors_at_warlord_clearing(self):
        """When supply >= prowess, places exactly prowess_value warriors."""
        from game.transactions.rats.birdsong import recruit
        from game.queries.rats.birdsong import get_prowess_value

        warlord = self._warlord()
        prowess = get_prowess_value(self.player)
        before = Warrior.objects.filter(
            player=self.player, clearing=warlord.clearing, warlord__isnull=True
        ).count()
        # Retract the setup stronghold so Phase 2 has nothing to do
        Stronghold.objects.filter(player=self.player).update(building_slot=None)

        recruit(self.player)

        after = Warrior.objects.filter(
            player=self.player, clearing=warlord.clearing, warlord__isnull=True
        ).count()
        self.assertEqual(after, before + prowess)

    def test_places_only_available_warriors_when_supply_low(self):
        """When supply < prowess, places only as many as are available."""
        from game.transactions.rats.birdsong import recruit
        from game.queries.rats.birdsong import get_prowess_value

        prowess = get_prowess_value(self.player)
        # Leave fewer warriors in supply than prowess value
        self._drain_supply_to(max(0, prowess - 1))
        supply_before = self._regular_warrior_count()

        warlord = self._warlord()
        before = Warrior.objects.filter(
            player=self.player, clearing=warlord.clearing, warlord__isnull=True
        ).count()
        # Retract strongholds so no Phase 2 complications
        Stronghold.objects.filter(player=self.player).update(building_slot=None)

        recruit(self.player)

        after = Warrior.objects.filter(
            player=self.player, clearing=warlord.clearing, warlord__isnull=True
        ).count()
        self.assertEqual(after, before + supply_before)

    def test_skips_warlord_placement_when_off_map(self):
        """If warlord is not on map, no warriors are placed at warlord clearing."""
        from game.transactions.rats.birdsong import recruit

        warlord_clearing = self._warlord().clearing
        self._send_warlord_to_supply()
        # Retract strongholds
        Stronghold.objects.filter(player=self.player).update(building_slot=None)

        before = Warrior.objects.filter(
            player=self.player, clearing=warlord_clearing, warlord__isnull=True
        ).count()

        recruit(self.player)

        after = Warrior.objects.filter(
            player=self.player, clearing=warlord_clearing, warlord__isnull=True
        ).count()
        self.assertEqual(after, before)


# ===========================================================================
# Phase 2 — Stronghold auto-placement
# ===========================================================================

class StrongholdAutoPlaceTests(RecruitBaseTestCase):

    def setUp(self):
        super().setUp()
        # Retract the setup stronghold (in C2) so tests control placement precisely
        Stronghold.objects.filter(player=self.player).update(building_slot=None, recruit_used=False)

    def test_auto_places_when_supply_exceeds_strongholds(self):
        """When supply >= stronghold count, places 1 warrior per stronghold."""
        from game.transactions.rats.birdsong import recruit

        # Deploy strongholds in C3 and C7 (both different from warlord C2)
        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        c7 = Clearing.objects.get(game=self.game, clearing_number=7)
        self._deploy_stronghold(c3)
        self._deploy_stronghold(c7)

        before_c3 = Warrior.objects.filter(
            player=self.player, clearing=c3, warlord__isnull=True
        ).count()
        before_c7 = Warrior.objects.filter(
            player=self.player, clearing=c7, warlord__isnull=True
        ).count()

        recruit(self.player)

        self.assertEqual(
            Warrior.objects.filter(
                player=self.player, clearing=c3, warlord__isnull=True
            ).count(),
            before_c3 + 1,
        )
        self.assertEqual(
            Warrior.objects.filter(
                player=self.player, clearing=c7, warlord__isnull=True
            ).count(),
            before_c7 + 1,
        )

    def test_auto_places_all_in_single_clearing_when_supply_short(self):
        """All strongholds in same clearing → auto-place min(supply, count) warriors."""
        from game.transactions.rats.birdsong import recruit

        # C7 has 2 building slots — deploy 2 strongholds there
        c7 = Clearing.objects.get(game=self.game, clearing_number=7)
        self._deploy_stronghold(c7)
        self._deploy_stronghold(c7)

        # Only 1 supply warrior for 2 strongholds in the same clearing
        self._send_warlord_to_supply()
        self._drain_supply_to(1)
        before = Warrior.objects.filter(
            player=self.player, clearing=c7, warlord__isnull=True
        ).count()

        recruit(self.player)

        after = Warrior.objects.filter(
            player=self.player, clearing=c7, warlord__isnull=True
        ).count()
        self.assertEqual(after, before + 1)

    def test_step_advances_after_auto_placement(self):
        """Step advances past RECRUIT when placement completes without a choice."""
        from game.transactions.rats.birdsong import recruit

        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        self._deploy_stronghold(c3)
        # Remove warlord so Phase 1 is skipped and supply is untouched
        self._send_warlord_to_supply()

        recruit(self.player)

        self.birdsong.refresh_from_db()
        self.assertNotEqual(self.birdsong.step, RatsBirdsong.Steps.RECRUIT)

    def test_recruit_pauses_when_choice_required(self):
        """Insufficient supply across multiple clearings → step stays at RECRUIT."""
        from game.transactions.rats.birdsong import recruit

        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        c7 = Clearing.objects.get(game=self.game, clearing_number=7)
        self._deploy_stronghold(c3)
        self._deploy_stronghold(c7)

        # Only 1 warrior in supply for 2 strongholds in different clearings
        self._send_warlord_to_supply()
        self._drain_supply_to(1)

        recruit(self.player)

        self.birdsong.refresh_from_db()
        self.assertEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.RECRUIT,
            "Step should stay at RECRUIT when a choice is required",
        )

    def test_strongholds_marked_used_after_auto_placement(self):
        """After auto-placement each stronghold that received a warrior is marked recruit_used."""
        from game.transactions.rats.birdsong import recruit

        c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        self._deploy_stronghold(c3)
        self._send_warlord_to_supply()

        recruit(self.player)

        deployed = Stronghold.objects.filter(
            player=self.player, building_slot__isnull=False
        )
        self.assertTrue(all(sh.recruit_used for sh in deployed))


# ===========================================================================
# recruit_stronghold
# ===========================================================================

class RecruitStrongholdTests(RecruitBaseTestCase):

    def setUp(self):
        super().setUp()
        # Retract setup stronghold; deploy 2 in different clearings
        Stronghold.objects.filter(player=self.player).update(building_slot=None, recruit_used=False)
        self.c3 = Clearing.objects.get(game=self.game, clearing_number=3)
        self.c7 = Clearing.objects.get(game=self.game, clearing_number=7)
        self._deploy_stronghold(self.c3)
        self._deploy_stronghold(self.c7)
        # 2 warriors in supply for 2 strongholds in different clearings
        self._send_warlord_to_supply()
        self._drain_supply_to(2)

    def test_places_warrior_in_chosen_clearing(self):
        """recruit_stronghold places one warrior in the chosen clearing."""
        from game.transactions.rats.birdsong import recruit_stronghold

        before = Warrior.objects.filter(
            player=self.player, clearing=self.c3, warlord__isnull=True
        ).count()

        recruit_stronghold(self.player, self.c3)

        after = Warrior.objects.filter(
            player=self.player, clearing=self.c3, warlord__isnull=True
        ).count()
        self.assertEqual(after, before + 1)

    def test_marks_stronghold_as_used(self):
        """The stronghold in the chosen clearing is marked recruit_used after placement."""
        from game.transactions.rats.birdsong import recruit_stronghold

        recruit_stronghold(self.player, self.c3)

        sh = Stronghold.objects.get(
            player=self.player, building_slot__clearing=self.c3
        )
        self.assertTrue(sh.recruit_used)

    def test_step_advances_after_last_choice(self):
        """After the last needed choice the step advances past RECRUIT."""
        from game.transactions.rats.birdsong import recruit_stronghold

        # Reduce to 1 supply warrior for 2 clearings: after placing at C3, supply=0 → done
        self._drain_supply_to(1)
        recruit_stronghold(self.player, self.c3)

        self.birdsong.refresh_from_db()
        self.assertNotEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.RECRUIT,
            "Step should advance once supply is exhausted",
        )

    def test_step_stays_when_more_choices_remain(self):
        """If another choice is needed after placement, step stays at RECRUIT."""
        from game.transactions.rats.birdsong import recruit_stronghold

        # Give 2 supply but deploy 3 strongholds in 3 different clearings
        c8 = Clearing.objects.get(game=self.game, clearing_number=8)
        self._deploy_stronghold(c8)
        self._drain_supply_to(2)  # now 2 supply, 3 strongholds in 3 clearings

        recruit_stronghold(self.player, self.c3)

        self.birdsong.refresh_from_db()
        self.assertEqual(
            self.birdsong.step,
            RatsBirdsong.Steps.RECRUIT,
            "Step should stay at RECRUIT while choices remain",
        )

    def test_raises_when_clearing_has_no_unused_stronghold(self):
        """Choosing a clearing without an unused stronghold raises IllegalActionError."""
        from game.transactions.rats.birdsong import recruit_stronghold

        c6 = Clearing.objects.get(game=self.game, clearing_number=6)
        with self.assertRaises(IllegalActionError):
            recruit_stronghold(self.player, c6)

    def test_raises_when_supply_empty(self):
        """Calling recruit_stronghold with no warriors in supply raises UnavailableActionError."""
        from game.transactions.rats.birdsong import recruit_stronghold

        self._drain_supply_to(0)
        with self.assertRaises(UnavailableActionError):
            recruit_stronghold(self.player, self.c3)


# ===========================================================================
# reset_rats_turn
# ===========================================================================

class ResetRecruitUsedTests(RecruitBaseTestCase):

    def test_recruit_used_reset_at_end_of_turn(self):
        """reset_rats_turn sets recruit_used=False on all strongholds."""
        from game.transactions.rats.turn import reset_rats_turn

        # Mark some strongholds as used
        Stronghold.objects.filter(player=self.player).update(recruit_used=True)

        reset_rats_turn(self.player)

        any_used = Stronghold.objects.filter(
            player=self.player, recruit_used=True
        ).exists()
        self.assertFalse(any_used)
