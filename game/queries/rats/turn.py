from game.models.game_models import Faction, Player
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsEvening, RatsTurn
from game.queries.general import get_current_player
from game.errors import UnavailableActionError, InternalGameError


def validate_turn(player: Player) -> RatsTurn:
    """returns the turn if it is the player's turn, else raises error"""
    current_player = get_current_player(player.game)
    if current_player != player:
        raise UnavailableActionError("Not this player's turn")
    if current_player.faction != Faction.RATS:
        raise UnavailableActionError("This player is not the Rats")
    rats_turn = RatsTurn.objects.filter(player=player).order_by("-turn_number").first()
    if rats_turn is None:
        raise InternalGameError("No turns found for this Rats player")
    return rats_turn


def get_phase(player: Player) -> RatsBirdsong | RatsDaylight | RatsEvening:
    """returns the current active phase, raising if it's not the player's turn"""
    rats_turn = validate_turn(player)
    birdsong = RatsBirdsong.objects.get(turn=rats_turn)
    daylight = RatsDaylight.objects.get(turn=rats_turn)
    evening = RatsEvening.objects.get(turn=rats_turn)
    if birdsong.step != RatsBirdsong.Steps.COMPLETED:
        return birdsong
    elif daylight.step != RatsDaylight.Steps.COMPLETED:
        return daylight
    else:
        return evening


def validate_phase(
    player: Player, phase_type: type[RatsBirdsong | RatsDaylight | RatsEvening]
) -> RatsBirdsong | RatsDaylight | RatsEvening:
    """returns the phase if it matches phase_type, else raises UnavailableActionError"""
    mapper = {
        RatsBirdsong: "Not Birdsong phase",
        RatsDaylight: "Not Daylight phase",
        RatsEvening: "Not Evening phase",
    }
    player_phase = get_phase(player)
    if phase_type != type(player_phase):
        raise UnavailableActionError(mapper[phase_type])
    return player_phase


def validate_step(
    player: Player,
    step: (
        RatsBirdsong.Steps
        | RatsDaylight.Steps
        | RatsEvening.Steps
    ),
) -> None:
    """Validate player is at the given step, raise UnavailableActionError if not."""
    player_phase = get_phase(player)
    if step == player_phase.step:
        return
    if isinstance(player_phase, RatsBirdsong):
        mapper = {
            RatsBirdsong.Steps.RAZE: "Not Raze step",
            RatsBirdsong.Steps.SPREAD_MOB: "Not Spread Mob step",
            RatsBirdsong.Steps.RECRUIT: "Not Recruit step",
            RatsBirdsong.Steps.ANOINT: "Not Anoint step",
            RatsBirdsong.Steps.CHOOSE_MOOD: "Not Choose Mood step",
        }
        raise UnavailableActionError(mapper.get(step, "Invalid Birdsong step"))
    elif isinstance(player_phase, RatsDaylight):
        mapper = {
            RatsDaylight.Steps.CRAFT: "Not Craft step",
            RatsDaylight.Steps.COMMAND: "Not Command step",
            RatsDaylight.Steps.ADVANCE: "Not Advance step",
        }
        raise UnavailableActionError(mapper.get(step, "Invalid Daylight step"))
    elif isinstance(player_phase, RatsEvening):
        mapper = {
            RatsEvening.Steps.INCITE: "Not Incite step",
            RatsEvening.Steps.OPPRESS: "Not Oppress step",
            RatsEvening.Steps.DRAW: "Not Draw step",
            RatsEvening.Steps.DISCARD: "Not Discard step",
        }
        raise UnavailableActionError(mapper.get(step, "Invalid Evening step"))
    else:
        raise UnavailableActionError("Invalid phase")
