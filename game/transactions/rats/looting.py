from django.db import transaction

from game.errors import IllegalActionError, UnavailableActionError
from game.models.events.rats import LootingEvent
from game.models.game_models import CraftedItemEntry, Item, Player
from game.models.rats.player import RatsPlayerState
from game.transactions.rats.hoard import add_item_to_hoard


@transaction.atomic
def declare_looting(player: Player, defender_player: Player) -> None:
    """Validate eligibility and set looting_declared = True.

    Called by _command_battle / advance_battle when looting=True is passed.

    Raises:
        IllegalActionError: if the defender has no items in their Crafted Items box.
    """
    if not CraftedItemEntry.objects.filter(player=defender_player).exists():
        raise IllegalActionError("Defender has no items to loot")

    state = RatsPlayerState.objects.get(player=player)
    state.looting_declared = True
    state.save()


@transaction.atomic
def choose_loot(player: Player, item: Item) -> None:
    """Resolve an active LootingEvent by choosing which item to take.

    The chosen item is removed from the looted player's Crafted Items box
    and added to the Rats hoard.  Resets looting_declared.

    Raises:
        UnavailableActionError: if there is no unresolved LootingEvent.
        IllegalActionError: if the item is not in the looted player's Crafted Items box.
    """
    looting_event = (
        LootingEvent.objects.filter(
            looting_player=player,
            event__is_resolved=False,
        )
        .select_related("event", "looted_player")
        .first()
    )
    if looting_event is None:
        raise UnavailableActionError("No active looting event")

    looted_player = looting_event.looted_player
    entry = CraftedItemEntry.objects.filter(
        player=looted_player, item=item
    ).first()
    if entry is None:
        raise IllegalActionError("Item is not in the looted player's crafted items")

    # Capture for logging before deletion
    item_type = item.item_type
    looted_faction = looted_player.faction

    entry.delete()
    add_item_to_hoard(player, item)

    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.rats import log_rats_loot
    phase_log = get_active_phase_log(player.game)
    log_rats_loot(player.game, player, item_type, looted_faction, parent=phase_log)

    looting_event.event.is_resolved = True
    looting_event.event.save()

    state = RatsPlayerState.objects.get(player=player)
    state.looting_declared = False
    state.save()

    # Resume the phase step machine.  The guard in step_effect ensures this is a
    # no-op if another event (e.g. the parent Battle event) is still unresolved.
    from game.transactions.rats.turn import step_effect
    step_effect(player)
