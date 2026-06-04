from rest_framework.exceptions import ValidationError

from game.decorators.transaction_decorator import atomic_game_action
from game.models.enums import ItemTypes, Suit
from game.models.events.rats import HoardTooFullEvent, JubilantMobSpreadEvent, LavishEvent, LootingEvent
from game.models.game_models import CraftedItemEntry, Clearing, Faction
from game.models.rats.player import CommandItemEntry, ProwessItemEntry
from game.queries.rats.bitter import get_active_bitter_event, get_available_mobs_for_bitter
from game.queries.rats.birdsong import get_mob_spread_targets
from game.queries.rats.events import (
    get_active_hoard_event,
    get_active_jubilant_event,
    get_active_lavish_event,
    get_active_looting_event,
)
from game.transactions.rats.bitter import absorb_mob, end_bitter
from game.transactions.rats.hoard import discard_hoard_item
from game.transactions.rats.jubilant import jubilant_choose_clearing, jubilant_end, jubilant_roll
from game.transactions.rats.lavish import end_lavish_step, liquidate_hoard_item
from game.transactions.rats.looting import choose_loot
from game.views.action_views.general import GameActionView


# ---------------------------------------------------------------------------
# HoardTooFull view
# ---------------------------------------------------------------------------


class RatsHoardTooFullView(GameActionView):
    """HOARD_TOO_FULL event: player must discard one item from the overfull track.

    Scores 1 VP for the discarded item, then resolves the event.
    """

    action_name = "RATS_HOARD_TOO_FULL"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        event = get_active_hoard_event(player)
        options = self._item_options(player, event.track)
        track_label = HoardTooFullEvent.Track(event.track).label
        return self.generate_step(
            name="select_item",
            prompt=f"Your {track_label} track is over capacity. Discard one item (you score 1 VP).",
            endpoint="item",
            payload_details=[{"type": "item_type", "name": "item_type"}],
            options=options,
        )

    def _item_options(self, player, track: str):
        if track == HoardTooFullEvent.Track.COMMAND:
            entries = CommandItemEntry.objects.filter(player=player).select_related("item")
        else:
            entries = ProwessItemEntry.objects.filter(player=player).select_related("item")
        return [
            {"value": entry.item.item_type, "label": ItemTypes(entry.item.item_type).label}
            for entry in entries
        ]

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "item":
                return self.post_item(request, game_id)
        return super().route_post(request, game_id, route)

    def post_item(self, request, game_id: int):
        player = self.player(request, game_id)
        item_type = request.data.get("item_type")
        event = get_active_hoard_event(player)
        if event.track == HoardTooFullEvent.Track.COMMAND:
            entry = CommandItemEntry.objects.filter(player=player, item__item_type=item_type).first()
        else:
            entry = ProwessItemEntry.objects.filter(player=player, item__item_type=item_type).first()
        if entry is None:
            raise ValidationError({"detail": "Item not found"})

        atomic_game_action(discard_hoard_item)(player, entry.item)
        return self.generate_completed_step()

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        if get_active_hoard_event(player) is None:
            raise ValidationError({"detail": "No active HoardTooFull event"})


# ---------------------------------------------------------------------------
# ResolveBitter view
# ---------------------------------------------------------------------------


class RatsResolveBitterView(GameActionView):
    """BITTER_RESOLVE event: optionally absorb mobs to reinforce the Warlord's clearing.

    Player picks a clearing (Warlord's or adjacent) that contains a Mob token
    to absorb — removing the mob and placing a warrior in the Warlord's clearing.
    Repeat as desired, then press End to proceed to the dice roll.
    """

    action_name = "RATS_BITTER_RESOLVE"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        options = self._mob_options(player)
        options.append({"value": "", "label": "End Bitter"})
        return self.generate_step(
            name="select_action",
            prompt="Bitter: absorb a nearby mob to place a warrior in the Warlord's clearing, or end.",
            endpoint="select",
            payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
            options=options,
        )

    def _mob_options(self, player):
        return [
            {
                "value": mob.clearing.clearing_number,
                "label": f"Absorb mob from clearing {mob.clearing.clearing_number} ({mob.clearing.suit})",
            }
            for mob in get_available_mobs_for_bitter(player)
        ]

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "select":
                return self.post_select(request, game_id)
        return super().route_post(request, game_id, route)

    def post_select(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        clearing_number = request.data.get("clearing_number", "")

        if clearing_number == "" or clearing_number is None:
            atomic_game_action(end_bitter)(player)
            return self.generate_completed_step()

        try:
            cn = int(clearing_number)
        except (ValueError, TypeError):
            raise ValidationError({"detail": "Invalid clearing number"})

        clearing = Clearing.objects.get(game=game, clearing_number=cn)
        atomic_game_action(absorb_mob)(player, clearing)

        # absorb_mob auto-calls end_bitter when no more mobs/warriors — check
        if get_active_bitter_event(player) is None:
            return self.generate_completed_step()

        # Still more mobs to potentially absorb
        options = self._mob_options(player)
        options.append({"value": "", "label": "End Bitter"})
        return self.generate_step(
            name="select_action",
            prompt="Absorb another mob, or end.",
            endpoint="select",
            payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
            options=options,
        )

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        if get_active_bitter_event(player) is None:
            raise ValidationError({"detail": "No active Bitter resolve event"})


# ---------------------------------------------------------------------------
# Looting view
# ---------------------------------------------------------------------------


class RatsLootingView(GameActionView):
    """LOOTING event: player chooses which item to take from the looted player.

    Only created when the defender has multiple items (single-item loot is auto-resolved).
    """

    action_name = "RATS_LOOTING"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        event = get_active_looting_event(player)
        looted_player = event.looted_player
        options = self._item_options(looted_player)
        return self.generate_step(
            name="select_item",
            prompt=f"Looting: choose one item to take from {looted_player.faction}.",
            endpoint="item",
            payload_details=[{"type": "item_type", "name": "item_type"}],
            options=options,
        )

    def _item_options(self, looted_player):
        return [
            {"value": entry.item.item_type, "label": ItemTypes(entry.item.item_type).label}
            for entry in CraftedItemEntry.objects.filter(
                player=looted_player
            ).select_related("item")
        ]

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "item":
                return self.post_item(request, game_id)
        return super().route_post(request, game_id, route)

    def post_item(self, request, game_id: int):
        player = self.player(request, game_id)
        item_type = request.data.get("item_type")
        event = get_active_looting_event(player)
        entry = CraftedItemEntry.objects.filter(
            player=event.looted_player, item__item_type=item_type
        ).first()
        if entry is None:
            raise ValidationError({"detail": "Item not found"})

        atomic_game_action(choose_loot)(player, entry.item)
        return self.generate_completed_step()

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        if get_active_looting_event(player) is None:
            raise ValidationError({"detail": "No active Looting event"})


# ---------------------------------------------------------------------------
# Lavish hoard liquidation view
# ---------------------------------------------------------------------------


class RatsLavishView(GameActionView):
    """LAVISH event: at end of Birdsong, player may remove any number of Hoard
    items permanently — each yields 2 warriors in the Warlord's clearing.

    Single-step UI: show all remaining Hoard items as options plus an End option.
    Posting an empty item_id ends the event; posting an item_id liquidates that item.
    Re-renders after each liquidation until the player ends or the Hoard is empty.
    """

    action_name = "RATS_LAVISH"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        options = self._item_options(player)
        options.append({"value": "", "label": "End (keep remaining items)"})
        return self.generate_step(
            name="select_item",
            prompt="Lavish: remove items from your Hoard (each yields 2 warriors in your Warlord's clearing), or end.",
            endpoint="select",
            payload_details=[{"type": "item_type", "name": "item_type"}],
            options=options,
        )

    def _item_options(self, player):
        options = []
        for entry in CommandItemEntry.objects.filter(player=player).select_related("item"):
            options.append({"value": entry.item.item_type, "label": ItemTypes(entry.item.item_type).label})
        for entry in ProwessItemEntry.objects.filter(player=player).select_related("item"):
            options.append({"value": entry.item.item_type, "label": ItemTypes(entry.item.item_type).label})
        return options

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "select":
                return self.post_select(request, game_id)
        return super().route_post(request, game_id, route)

    def post_select(self, request, game_id: int):
        player = self.player(request, game_id)
        item_type = request.data.get("item_type", "")

        if item_type == "" or item_type is None:
            atomic_game_action(end_lavish_step)(player)
            return self.generate_completed_step()

        atomic_game_action(liquidate_hoard_item)(player, item_type)

        # Auto-resolved if hoard emptied
        if get_active_lavish_event(player) is None:
            return self.generate_completed_step()

        options = self._item_options(player)
        options.append({"value": "", "label": "End (keep remaining items)"})
        return self.generate_step(
            name="select_item",
            prompt="Lavish: remove another item, or end.",
            endpoint="select",
            payload_details=[{"type": "item_type", "name": "item_type"}],
            options=options,
        )

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        if get_active_lavish_event(player) is None:
            raise ValidationError({"detail": "No active Lavish event"})


# ---------------------------------------------------------------------------
# Jubilant mob spread view
# ---------------------------------------------------------------------------


class RatsJubilantMobSpreadView(GameActionView):
    """JUBILANT_MOB_SPREAD event: after Incite in the Warlord's clearing (Jubilant mood),
    the player may roll the mob die up to 4 times and place mobs in adjacent clearings.

    States:
      - current_roll is None → "roll or end" prompt
      - current_roll is set  → clearing picker for that suit
    """

    action_name = "RATS_JUBILANT_MOB_SPREAD"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        return self._render_current_state(player)

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "roll":
                return self.post_roll(request, game_id)
            case "choose":
                return self.post_choose(request, game_id)
        return super().route_post(request, game_id, route)

    def post_roll(self, request, game_id: int):
        player = self.player(request, game_id)
        action = request.data.get("action", "roll")

        if action == "end":
            atomic_game_action(jubilant_end)(player)
            return self.generate_completed_step()

        atomic_game_action(jubilant_roll)(player)

        # Check if event resolved (no targets, last roll, supply exhausted)
        if get_active_jubilant_event(player) is None:
            return self.generate_completed_step()

        return self._render_current_state(player)

    def post_choose(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        try:
            clearing_number = int(request.data.get("clearing_number"))
        except (ValueError, TypeError):
            raise ValidationError({"detail": "Invalid clearing number"})

        clearing = Clearing.objects.get(game=game, clearing_number=clearing_number)
        atomic_game_action(jubilant_choose_clearing)(player, clearing)

        if get_active_jubilant_event(player) is None:
            return self.generate_completed_step()

        return self._render_current_state(player)

    def _render_current_state(self, player):
        """Build the appropriate step response based on the current event state."""
        evt = get_active_jubilant_event(player)
        if evt is None:
            return self.generate_completed_step()

        if evt.current_roll is not None:
            targets = get_mob_spread_targets(player, Suit(evt.current_roll))
            options = [
                {"value": str(c.clearing_number), "label": f"Clearing {c.clearing_number} ({c.suit})"}
                for c in sorted(targets, key=lambda c: c.clearing_number)
            ]
            return self.generate_step(
                name="choose_clearing",
                prompt=f"Jubilant: rolled {evt.current_roll}. Choose a clearing to place a mob.",
                endpoint="choose",
                payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
                options=options,
            )

        options = [
            {"value": "roll", "label": f"Roll the mob die ({evt.rolls_remaining} roll(s) remaining)"},
            {"value": "end", "label": "End Jubilant spreading"},
        ]
        return self.generate_step(
            name="roll_or_end",
            prompt=f"Jubilant: you may roll the mob die to spread mobs. {evt.rolls_remaining} roll(s) remaining.",
            endpoint="roll",
            payload_details=[{"type": "action", "name": "action"}],
            options=options,
        )

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        if get_active_jubilant_event(player) is None:
            raise ValidationError({"detail": "No active Jubilant mob spread event"})
