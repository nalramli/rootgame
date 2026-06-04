from typing import Union
from django.db import transaction

from game.models.game_models import Player
from game.models.crows.tokens import PlotToken
from game.models.crows.turn import CrowTurn, CrowBirdsong, CrowDaylight, CrowEvening
from game.queries.crows.turn import get_phase
from game.utility.textchoice import next_choice
from game.transactions.general import draw_card_from_deck_to_hand, next_players_turn


@transaction.atomic
def next_step(player: Player):
    """
    moves to next step in the current phase or next phase, launching events if necessary
    e.g.: for card effects that need to be triggered at a specific step
    """
    phase = get_phase(player)
    match phase:
        case CrowBirdsong():
            phase.step = next_choice(CrowBirdsong.CrowBirdsongSteps, phase.step)
        case CrowDaylight():
            phase.step = next_choice(CrowDaylight.CrowDaylightSteps, phase.step)
        case CrowEvening():
            phase.step = next_choice(CrowEvening.CrowEveningSteps, phase.step)
        case _:
            raise ValueError("Invalid phase")
    phase.save()
    
    step_effect(player, phase)


@transaction.atomic
def create_crows_turn(player: Player):
    # create turn
    turn = CrowTurn.create_turn(player)

    from game.serializers.logs.general import log_turn
    log_turn(player.game, player, turn_number=turn.turn_number + 1)
    # Birdsong log will be created in CrowBirdsong.NOT_STARTED step_effect


@transaction.atomic
def step_effect(
    player: Player, phase: Union[CrowBirdsong, CrowDaylight, CrowEvening, None] = None
):
    """executes any 'passive' effects that should occur at a specific step
    ex: drawing or launching events
    typically called from next_step
    """
    # Guard: if any events are still unresolved, don't advance the step machine.
    from game.queries.current_action.events import get_current_event
    if get_current_event(player.game) is not None:
        return

    if phase is None:
        phase = get_phase(player)
    
    match phase:
        case CrowBirdsong():
            match phase.step:
                case CrowBirdsong.CrowBirdsongSteps.NOT_STARTED:
                    from game.serializers.logs.general import get_or_log_phase, get_current_turn_log
                    from game.transactions.crafted_cards.saboteurs import saboteurs_check
                    get_or_log_phase(
                        player.game,
                        player,
                        "Birdsong",
                        parent=get_current_turn_log(player.game, player),
                    )
                    if not saboteurs_check(player):
                        next_step(player)
                case CrowBirdsong.CrowBirdsongSteps.CRAFT:
                    from game.queries.crafted_cards import get_coffin_makers_player
                    from game.transactions.crafted_cards.coffin_makers import score_coffins, release_warriors

                    coffin_player = get_coffin_makers_player(player.game)
                    if coffin_player == player:
                        score_coffins(player)
                        release_warriors(player.game)
                case CrowBirdsong.CrowBirdsongSteps.FLIP:
                    pass
                case CrowBirdsong.CrowBirdsongSteps.RECRUIT:
                    pass
                case CrowBirdsong.CrowBirdsongSteps.BEFORE_END:
                    from game.transactions.crafted_cards.eyrie_emigre import is_emigre
                    if not is_emigre(player):
                        next_step(player)
                case CrowBirdsong.CrowBirdsongSteps.COMPLETED:
                    step_effect(player)
                case _:
                    raise ValueError(
                        f"Invalid step in step_effect for Crows Birdsong: {phase.step}"
                    )
        case CrowDaylight():
            match phase.step:
                case CrowDaylight.CrowDaylightSteps.NOT_STARTED:
                    from game.serializers.logs.general import get_or_log_phase, get_current_turn_log
                    get_or_log_phase(
                        player.game,
                        player,
                        "Daylight",
                        parent=get_current_turn_log(player.game, player),
                    )
                    next_step(player)
                case CrowDaylight.CrowDaylightSteps.ACTIONS:
                    pass
                case CrowDaylight.CrowDaylightSteps.BEFORE_END:
                    from game.transactions.crafted_cards.charm_offensive import check_charm_offensive
                    if not check_charm_offensive(player):
                        next_step(player)
                case CrowDaylight.CrowDaylightSteps.COMPLETED:
                    step_effect(player)
                case _:
                    raise ValueError(
                        f"Invalid step in step_effect for Crows Daylight: {phase.step}"
                    )
        case CrowEvening():
            match phase.step:
                case CrowEvening.CrowEveningSteps.NOT_STARTED:
                    from game.serializers.logs.general import get_or_log_phase, get_current_turn_log
                    get_or_log_phase(
                        player.game,
                        player,
                        "Evening",
                        parent=get_current_turn_log(player.game, player),
                    )
                    next_step(player)
                case CrowEvening.CrowEveningSteps.EXERT:
                    pass
                case CrowEvening.CrowEveningSteps.DRAWING:
                    from game.transactions.crafted_cards.informants import informants_check
                    is_informants = informants_check(player)
                    if not is_informants:
                        if phase.exert_used:
                            next_step(player)
                        else:
                            from game.transactions.crows.evening import calculate_crow_draw_amount
                            amount = calculate_crow_draw_amount(player)
                            drawn_cards = []
                            for _ in range(amount):
                                drawn_cards.append(draw_card_from_deck_to_hand(player))

                            from game.serializers.logs.general import log_draw, get_current_phase_log
                            log_draw(player.game, player, [d.card for d in drawn_cards], parent=get_current_phase_log(player.game, player))

                            phase.cards_drawn = amount
                            phase.save()
                            next_step(player)
                case CrowEvening.CrowEveningSteps.DISCARDING:
                    from game.transactions.crows.evening import check_discard_step
                    check_discard_step(player)
                case CrowEvening.CrowEveningSteps.BEFORE_END:
                    next_step(player)
                case CrowEvening.CrowEveningSteps.COMPLETED:
                    end_crows_turn(player)
                case _:
                    raise ValueError(f"Invalid step in step_effect for Crows Evening: {phase.step}")
        case _:
            raise ValueError("Invalid phase")

@transaction.atomic
def end_crows_turn(player: Player):
    """ends the current turn, generating the next turn and moving to the next players phase"""
    try:
        evening = get_phase(player)
        if not isinstance(evening, CrowEvening):
            raise ValueError("Not Evening phase")
        evening.step = CrowEvening.CrowEveningSteps.COMPLETED
        evening.save()
    except Exception:
        pass
    next_players_turn(player.game)
    reset_crows_turn(player)

@transaction.atomic
def reset_crows_turn(player: Player):
    """resets crows components to initial state"""
    PlotToken.objects.filter(player=player).update(crafted_with=False)
