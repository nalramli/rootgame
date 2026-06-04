from game.models.enums import Faction
from game.models.events.rats import ResolveBitterEvent
from game.models.game_models import Clearing, Player
from game.models.rats.player import RatsPlayerState
from game.models.rats.tokens import Mob
from game.queries.general import get_adjacent_clearings
from game.queries.rats.pieces import get_warlord


def get_active_bitter_event(player: Player) -> ResolveBitterEvent | None:
    """Return the unresolved ResolveBitterEvent for *player*, or None."""
    return (
        ResolveBitterEvent.objects.filter(
            player=player,
            event__is_resolved=False,
        )
        .select_related("event", "battle")
        .first()
    )


def get_available_mobs_for_bitter(player: Player):
    """Return the queryset of Mob tokens available to absorb during Bitter resolution.

    A mob is available if it is in the Warlord's current clearing or any adjacent
    clearing (adjacency accounts for passive effects such as Riverboats).
    Returns an empty queryset if the Warlord is not deployed.
    """
    warlord = get_warlord(player)
    if warlord.clearing is None:
        return Mob.objects.none()
    warlord_clearing = warlord.clearing
    adjacent_and_local = get_adjacent_clearings(player, warlord_clearing) | {warlord_clearing}
    return Mob.objects.filter(player=player, clearing__in=adjacent_and_local).select_related("clearing")


def has_mobs_available(player: Player) -> bool:
    """Return True if there are any Mob tokens in the Warlord's clearing or adjacent."""
    return get_available_mobs_for_bitter(player).exists()


def can_trigger_bitter_event(game, attacker_faction: Faction, battle_clearing: Clearing) -> bool:
    """Check if a Bitter event should be triggered during battle.

    Returns True if:
    - Attacker is Rats
    - Rats player has BITTER mood
    - Warlord is in the battle clearing
    - Mobs are available (in battle clearing or adjacent)
    """
    if attacker_faction != Faction.RATS:
        return False

    rats_player = Player.objects.get(game=game, faction=Faction.RATS)
    state = RatsPlayerState.objects.filter(player=rats_player).first()
    if not state or state.mood_type != RatsPlayerState.MoodType.BITTER:
        return False

    warlord = get_warlord(rats_player)
    if warlord.clearing != battle_clearing:
        return False

    return has_mobs_available(rats_player)
