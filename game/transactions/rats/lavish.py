from django.db import transaction

from game.errors import IllegalActionError, UnavailableActionError
from game.models.events.rats import HoardTooFullEvent, LavishEvent
from game.models.game_models import Player
from game.models.rats.player import CommandItemEntry, ProwessItemEntry
from game.queries.rats.hoard import get_item_track


def _get_active_lavish_event(player: Player) -> LavishEvent:
    evt = (
        LavishEvent.objects.filter(player=player, event__is_resolved=False)
        .select_related("event")
        .first()
    )
    if evt is None:
        raise UnavailableActionError("No active Lavish event")
    return evt


def _has_hoard_items(player: Player) -> bool:
    return (
        CommandItemEntry.objects.filter(player=player).exists()
        or ProwessItemEntry.objects.filter(player=player).exists()
    )


@transaction.atomic
def liquidate_hoard_item(player: Player, item_type: str) -> None:
    """Remove one item from the Hoard, place 2 warriors in the Warlord's clearing.

    Validates that a Lavish event is active and an item of this type exists in the
    player's Hoard. Raises IllegalActionError if warrior supply is 0 (player can't
    waste an item for no warriors). Places up to 2 warriors (partial placement
    allowed when supply has exactly 1 warrior). Auto-resolves the event when no
    items remain.
    """
    from game.queries.rats.pieces import get_warlord
    from game.queries.rats.recruit import get_warrior_supply_count
    from game.transactions.rats.birdsong import _place_warriors_excluding_warlord

    _get_active_lavish_event(player)  # validate event is active

    cmd_entry = CommandItemEntry.objects.filter(
        player=player, item__item_type=item_type
    ).first()
    prw_entry = ProwessItemEntry.objects.filter(
        player=player, item__item_type=item_type
    ).first()
    if cmd_entry is None and prw_entry is None:
        raise IllegalActionError("No item of this type in this player's Hoard")

    if get_warrior_supply_count(player) == 0:
        raise IllegalActionError(
            "No warriors in supply — cannot liquidate a Hoard item for 0 warriors"
        )

    # Capture for logging before deletion
    entry = cmd_entry or prw_entry
    assert entry is not None
    item = entry.item

    track_enum = get_item_track(item_type)
    track = "Command" if track_enum == HoardTooFullEvent.Track.COMMAND else "Prowess"

    entry.delete()
    item.delete()

    warlord = get_warlord(player)
    supply_before = get_warrior_supply_count(player)
    clearing_number = None
    if warlord.clearing is not None:
        clearing_number = warlord.clearing.clearing_number
        _place_warriors_excluding_warlord(player, warlord.clearing, 2)
    warriors_placed = supply_before - get_warrior_supply_count(player)

    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.rats import log_rats_lavish_liquidate
    phase_log = get_active_phase_log(player.game)
    log_rats_lavish_liquidate(
        player.game, player,
        item_type, track, warriors_placed, clearing_number,
        parent=phase_log,
    )

    if not _has_hoard_items(player):
        end_lavish_step(player)


@transaction.atomic
def end_lavish_step(player: Player) -> None:
    """Player ends voluntarily (or auto-called when Hoard is empty).

    Resolves the LavishEvent, marks lavish_complete on the current RatsBirdsong
    phase, then resumes the step machine via step_effect().
    """
    from game.models.rats.turn import RatsBirdsong
    from game.transactions.rats.turn import step_effect

    evt = _get_active_lavish_event(player)
    evt.event.is_resolved = True
    evt.event.save()

    birdsong = RatsBirdsong.objects.filter(
        turn__player=player, step=RatsBirdsong.Steps.BEFORE_END
    ).first()
    if birdsong is not None:
        birdsong.lavish_complete = True
        birdsong.save()
        step_effect(player, birdsong)
