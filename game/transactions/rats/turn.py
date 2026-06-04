from typing import Union
from django.db import transaction

from game.models.game_models import Player, HandEntry
from game.models.rats.turn import RatsTurn, RatsBirdsong, RatsDaylight, RatsEvening
from game.queries.rats.turn import get_phase
from game.utility.textchoice import next_choice
from game.transactions.general import next_players_turn


def _next_daylight_step(player: Player, current_step: str) -> str:
    """Return the next Daylight step, accounting for Grandiose mood.

    Grandiose (tea) reverses Command and Advance:
      Normal:    CRAFT → COMMAND → ADVANCE → BEFORE_END
      Grandiose: CRAFT → ADVANCE → COMMAND → BEFORE_END
    """
    from game.models.rats.player import RatsPlayerState

    Steps = RatsDaylight.Steps
    state = RatsPlayerState.objects.filter(player=player).first()
    is_grandiose = state is not None and state.mood_type == RatsPlayerState.MoodType.GRANDIOSE

    if is_grandiose:
        match current_step:
            case Steps.CRAFT:
                return Steps.ADVANCE
            case Steps.ADVANCE:
                return Steps.COMMAND
            case Steps.COMMAND:
                return Steps.BEFORE_END

    return next_choice(Steps, current_step)


@transaction.atomic
def next_step(player: Player):
    phase = get_phase(player)
    match phase:
        case RatsBirdsong():
            phase.step = next_choice(RatsBirdsong.Steps, phase.step)
        case RatsDaylight():
            phase.step = _next_daylight_step(player, phase.step)
        case RatsEvening():
            phase.step = next_choice(RatsEvening.Steps, phase.step)
        case _:
            raise ValueError("Invalid phase")
    phase.save()

    step_effect(player, phase)


@transaction.atomic
def create_rats_turn(player: Player):
    turn = RatsTurn.create_turn(player)

    from game.serializers.logs.general import log_turn

    log_turn(player.game, player, turn_number=turn.turn_number + 1)


@transaction.atomic
def step_effect(
    player: Player, phase: Union[RatsBirdsong, RatsDaylight, RatsEvening, None] = None
):
    # Guard: if any events are still unresolved, don't advance the step machine.
    # This prevents the phase from progressing mid-stack when multiple events are
    # layered on top of each other.  The final event to resolve will call
    # step_effect() again, find no more events, and resume normally.
    from game.queries.current_action.events import get_current_event
    if get_current_event(player.game) is not None:
        return

    if phase is None:
        phase = get_phase(player)

    from game.transactions.crafted_cards.saboteurs import saboteurs_check
    from game.transactions.crafted_cards.eyrie_emigre import is_emigre
    from game.transactions.crafted_cards.charm_offensive import check_charm_offensive

    match phase:
        case RatsBirdsong():
            match phase.step:
                case RatsBirdsong.Steps.NOT_STARTED:
                    from game.serializers.logs.general import (
                        get_or_log_phase,
                        get_current_turn_log,
                    )

                    get_or_log_phase(
                        player.game,
                        player,
                        "Birdsong",
                        parent=get_current_turn_log(player.game, player),
                    )
                    if not saboteurs_check(player):
                        next_step(player)
                case RatsBirdsong.Steps.RAZE:
                    from game.transactions.rats.birdsong import raze

                    raze(player)
                case RatsBirdsong.Steps.SPREAD_MOB:
                    from game.transactions.rats.birdsong import roll_mob_die_and_spread

                    roll_mob_die_and_spread(player)
                case RatsBirdsong.Steps.RECRUIT:
                    from game.transactions.rats.birdsong import recruit

                    recruit(player)
                case RatsBirdsong.Steps.ANOINT:
                    from game.queries.rats.pieces import get_warlord

                    warlord = get_warlord(player)
                    if warlord.clearing is not None:
                        next_step(player)
                case RatsBirdsong.Steps.CHOOSE_MOOD:
                    pass
                case RatsBirdsong.Steps.BEFORE_END:
                    if not phase.lavish_complete:
                        from game.models.rats.player import RatsPlayerState, CommandItemEntry, ProwessItemEntry
                        from game.models.events.rats import LavishEvent
                        state = RatsPlayerState.objects.filter(player=player).first()
                        has_items = (
                            CommandItemEntry.objects.filter(player=player).exists()
                            or ProwessItemEntry.objects.filter(player=player).exists()
                        )
                        if state is not None and state.mood_type == RatsPlayerState.MoodType.LAVISH and has_items:
                            LavishEvent.create(player)
                            return  # event interrupts; do not advance
                        # Not lavish or no items — mark done and fall through
                        phase.lavish_complete = True
                        phase.save()
                    if not is_emigre(player):
                        next_step(player)
                case RatsBirdsong.Steps.COMPLETED:
                    step_effect(player)
                case _:
                    raise ValueError(
                        f"Invalid step in step_effect for Rats Birdsong: {phase.step}"
                    )
        case RatsDaylight():
            match phase.step:
                case RatsDaylight.Steps.NOT_STARTED:
                    from game.serializers.logs.general import (
                        get_or_log_phase,
                        get_current_turn_log,
                    )

                    get_or_log_phase(
                        player.game,
                        player,
                        "Daylight",
                        parent=get_current_turn_log(player.game, player),
                    )
                    next_step(player)
                case RatsDaylight.Steps.CRAFT:
                    pass
                case RatsDaylight.Steps.COMMAND:
                    pass
                case RatsDaylight.Steps.ADVANCE:
                    pass
                case RatsDaylight.Steps.BEFORE_END:
                    next_step(player)
                case RatsDaylight.Steps.COMPLETED:
                    step_effect(player)
                case _:
                    raise ValueError(
                        f"Invalid step in step_effect for Rats Daylight: {phase.step}"
                    )
        case RatsEvening():
            match phase.step:
                case RatsEvening.Steps.NOT_STARTED:
                    from game.serializers.logs.general import (
                        get_or_log_phase,
                        get_current_turn_log,
                    )

                    get_or_log_phase(
                        player.game,
                        player,
                        "Evening",
                        parent=get_current_turn_log(player.game, player),
                    )
                    if not check_charm_offensive(player):
                        next_step(player)
                case RatsEvening.Steps.INCITE:
                    pass
                case RatsEvening.Steps.OPPRESS:
                    from game.transactions.rats.evening import resolve_oppress
                    resolve_oppress(player)
                case RatsEvening.Steps.DRAW:
                    from game.transactions.rats.evening import draw_cards
                    draw_cards(player)
                case RatsEvening.Steps.DISCARD:
                    hand_size = HandEntry.objects.filter(player=player).count()
                    if hand_size <= 5:
                        next_step(player)
                case RatsEvening.Steps.BEFORE_END:
                    next_step(player)
                case RatsEvening.Steps.COMPLETED:
                    end_rats_turn(player)
                case _:
                    raise ValueError(
                        f"Invalid step in step_effect for Rats Evening: {phase.step}"
                    )
        case _:
            raise ValueError("Invalid phase")


@transaction.atomic
def end_rats_turn(player: Player):
    try:
        evening = get_phase(player)
        if not isinstance(evening, RatsEvening):
            raise ValueError("Not Evening phase")
        evening.step = RatsEvening.Steps.COMPLETED
        evening.save()
    except Exception:
        pass
    next_players_turn(player.game)
    reset_rats_turn(player)


@transaction.atomic
def reset_rats_turn(player: Player):
    from game.models.rats.buildings import Stronghold

    Stronghold.objects.filter(player=player).update(crafted_with=False, recruit_used=False)
