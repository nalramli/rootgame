from game.models.events.rats import (
    HoardTooFullEvent,
    JubilantMobSpreadEvent,
    LavishEvent,
    LootingEvent,
)
from game.models.game_models import Player


def get_active_hoard_event(player: Player) -> HoardTooFullEvent | None:
    return (
        HoardTooFullEvent.objects.filter(player=player, event__is_resolved=False)
        .select_related("event")
        .first()
    )


def get_active_looting_event(player: Player) -> LootingEvent | None:
    return (
        LootingEvent.objects.filter(
            looting_player=player, event__is_resolved=False
        )
        .select_related("event", "looted_player")
        .first()
    )


def get_active_lavish_event(player: Player) -> LavishEvent | None:
    return (
        LavishEvent.objects.filter(player=player, event__is_resolved=False)
        .select_related("event")
        .first()
    )


def get_active_jubilant_event(player: Player) -> JubilantMobSpreadEvent | None:
    return (
        JubilantMobSpreadEvent.objects.filter(player=player, event__is_resolved=False)
        .select_related("event")
        .first()
    )
