from django.db import transaction

from game.errors import IllegalActionError, UnavailableActionError
from game.models.enums import ItemTypes
from game.models.events.rats import HoardTooFullEvent
from game.models.game_models import Item, Player
from game.models.rats.player import CommandItemEntry, ProwessItemEntry
from game.queries.rats.hoard import get_item_track

_COMMAND_ITEMS: set[str] = {ItemTypes.BOOTS, ItemTypes.BAG, ItemTypes.COIN}
_PROWESS_ITEMS: set[str] = {
    ItemTypes.HAMMER,
    ItemTypes.TEA,
    ItemTypes.SWORD,
    ItemTypes.CROSSBOW,
}


@transaction.atomic
def add_item_to_hoard(player: Player, item: Item) -> None:
    """Add a single item to either the Command or Prowess track in the hoard.

    If the track exceeds 4 items after adding, a HoardTooFullEvent is created
    and the player must call discard_hoard_item to resolve it.
    """
    if item.item_type in _COMMAND_ITEMS:
        CommandItemEntry.objects.create(player=player, item=item)
        if CommandItemEntry.objects.filter(player=player).count() > 4:
            HoardTooFullEvent.create(player, HoardTooFullEvent.Track.COMMAND)
    elif item.item_type in _PROWESS_ITEMS:
        ProwessItemEntry.objects.create(player=player, item=item)
        if ProwessItemEntry.objects.filter(player=player).count() > 4:
            HoardTooFullEvent.create(player, HoardTooFullEvent.Track.PROWESS)
    # Items with types outside both sets are silently ignored (future-proofing)


@transaction.atomic
def discard_hoard_item(player: Player, item: Item) -> None:
    """Player discards one item from an overfull hoard track.

    Validates that there is an unresolved HoardTooFullEvent for the track
    corresponding to *item*'s type.  Removes the item from the hoard (and the
    game entirely), scores the player 1 VP, and resolves the event.

    Raises:
        IllegalActionError: if the item does not belong to a hoard track, or
            is not currently on the expected track for this player.
        UnavailableActionError: if there is no unresolved HoardTooFullEvent for
            the relevant track.
    """
    track = get_item_track(item.item_type)

    # Validate there is an unresolved HoardTooFull event for this track
    hoard_event = HoardTooFullEvent.objects.filter(
        player=player,
        track=track,
        event__is_resolved=False,
    ).first()
    if hoard_event is None:
        raise UnavailableActionError(
            f"No unresolved HoardTooFull event for the {track} track"
        )

    # Validate the item is actually on this player's track
    if track == HoardTooFullEvent.Track.COMMAND:
        entry = CommandItemEntry.objects.filter(player=player, item=item).first()
        if entry is None:
            raise IllegalActionError("Item is not on this player's Command track")
        entry.delete()
    else:
        entry = ProwessItemEntry.objects.filter(player=player, item=item).first()
        if entry is None:
            raise IllegalActionError("Item is not on this player's Prowess track")
        entry.delete()

    # Capture for logging before deleting
    item_type = item.item_type
    track_value = track.value if hasattr(track, "value") else str(track)

    # Remove the item from the game entirely
    item.delete()

    # Score 1 VP for the discard
    from game.transactions.general import raise_score
    raise_score(player, 1)

    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.rats import log_rats_hoard_discard
    phase_log = get_active_phase_log(player.game)
    log_rats_hoard_discard(player.game, player, item_type, track_value, parent=phase_log)

    # Resolve the event
    hoard_event.event.is_resolved = True
    hoard_event.event.save()

    # Resume the phase step machine.  The guard in step_effect ensures this is a
    # no-op if another HoardTooFull event (for the other track) is still unresolved.
    from game.transactions.rats.turn import step_effect
    step_effect(player)
