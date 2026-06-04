from django.db import transaction

from game.errors import IllegalActionError, UnavailableActionError
from game.models.game_models import Clearing, Player, Warrior
from game.models.rats.tokens import Mob
from game.queries.general import get_adjacent_clearings
from game.queries.rats.bitter import get_active_bitter_event, has_mobs_available
from game.queries.rats.pieces import get_warlord


@transaction.atomic
def absorb_mob(player: Player, clearing: Clearing) -> None:
    """Remove one Mob token from *clearing* and place a warrior in the Warlord's clearing.

    *clearing* must be the Warlord's current clearing or adjacent to it.
    After absorbing, if no more mobs are available or no warriors remain in supply,
    end_bitter is called automatically.

    Raises:
        UnavailableActionError: if there is no active Bitter mood event.
        IllegalActionError: if *clearing* is not adjacent or equal to the Warlord's
            clearing, if there is no Mob in *clearing*, or no warriors left in supply.
    """
    bitter_event = get_active_bitter_event(player)
    if bitter_event is None:
        raise UnavailableActionError("No active Bitter mood event")

    warlord = get_warlord(player)
    if warlord.clearing is None:
        raise IllegalActionError("Warlord is not deployed on the map")
    warlord_clearing = warlord.clearing

    # Validate clearing is local or adjacent
    adjacent_and_local = get_adjacent_clearings(player, warlord_clearing) | {warlord_clearing}
    if clearing not in adjacent_and_local:
        raise IllegalActionError(
            "Clearing is not the Warlord's clearing or adjacent to it"
        )

    # Find a mob in that clearing
    mob = Mob.objects.filter(player=player, clearing=clearing).first()
    if mob is None:
        raise IllegalActionError("No Mob token in that clearing")

    # Find a warrior in supply
    warrior = Warrior.objects.filter(player=player, clearing__isnull=True).first()
    if warrior is None:
        raise IllegalActionError("No warriors left in supply")

    # Remove mob from board
    mob_clearing_number = clearing.clearing_number
    mob.clearing = None
    mob.save()

    # Place warrior in warlord's clearing
    warrior.clearing = warlord_clearing
    warrior.save()

    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.rats import log_rats_bitter_absorb
    phase_log = get_active_phase_log(player.game)
    log_rats_bitter_absorb(
        player.game, player,
        mob_clearing_number, warlord_clearing.clearing_number,
        parent=phase_log,
    )

    # Auto-end if no more mobs available or no more supply warriors
    no_more_mobs = not has_mobs_available(player)
    no_more_supply = not Warrior.objects.filter(player=player, clearing__isnull=True).exists()
    if no_more_mobs or no_more_supply:
        end_bitter(player)


@transaction.atomic
def end_bitter(player: Player) -> None:
    """Resolve the active Bitter mood event and proceed to the dice roll.

    Raises:
        UnavailableActionError: if there is no active Bitter mood event.
    """
    from game.transactions.battle import roll_dice

    bitter_event = get_active_bitter_event(player)
    if bitter_event is None:
        raise UnavailableActionError("No active Bitter mood event")
    battle = bitter_event.battle
    game = battle.event.game

    bitter_event.event.is_resolved = True
    bitter_event.event.save()

    roll_dice(game, battle)
