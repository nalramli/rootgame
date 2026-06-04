from django.urls import reverse
from game.models.game_models import CraftedCardEntry, Faction, Game, Player
from game.models.events.event import Event, EventType
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.wa.turn import WABirdsong, WADaylight, WAEvening
from game.models.moles.turn import MoleBirdsong, MoleDaylight, MoleEvening
from game.queries.current_action.events import get_current_event_action
from game.queries.general import get_current_player
from game.queries.crows.turn import get_phase as get_crows_phase
from game.models.crows.turn import CrowBirdsong, CrowDaylight, CrowEvening
from game.models.cats.turn import CatBirdsong, CatDaylight, CatEvening
from game.models.birds.turn import BirdBirdsong, BirdDaylight, BirdEvening
from game.queries.cats.turn import get_phase as get_cats_phase
from game.queries.birds.turn import get_phase as get_birds_phase
from game.queries.wa.turn import get_phase as get_wa_phase
from game.queries.moles.turn import get_phase as get_moles_phase
from game.models.rats.turn import RatsBirdsong, RatsDaylight, RatsEvening
from game.queries.rats.turn import get_phase as get_rats_phase


def get_current_turn_action(game: Game) -> str | None:
    """Return the current turn action route for the game.
    Returns None if the next set of actions should be examined.
    Raises if there is an inconsistency"""
    # 1. Check for existing event
    event_action = get_current_event_action(game)
    if event_action is not None:
        return event_action
        
    player = get_current_player(game)
    

    match player.faction:
        case Faction.CATS:
            return get_cats_turn_action(player)
        case Faction.BIRDS:
            return get_birds_turn_action(player)
        case Faction.WOODLAND_ALLIANCE:
            return get_wa_turn_action(player)
        case Faction.CROWS:
            return get_crows_turn_action(player)
        case Faction.MOLES:
            return get_moles_turn_action(player)
        case Faction.RATS:
            return get_rats_turn_action(player)
        case _:
            raise ValueError("Invalid faction")


def get_cats_turn_action(player: Player) -> str | None:
    """Return the current cats turn action route for the player or raises if unexpected step"""
    phase = get_cats_phase(player)
    match phase:
        case CatBirdsong():
            return get_cats_birdsong_turn_action(phase)
        case CatDaylight():
            return get_cats_daylight_turn_action(phase)
        case CatEvening():
            return get_cats_evening_turn_action(phase)
        case _:
            raise ValueError(f"Invalid cats phase: {phase}")


def get_cats_birdsong_turn_action(phase: CatBirdsong):
    match phase.step:
        case CatBirdsong.CatBirdsongSteps.NOT_STARTED | CatBirdsong.CatBirdsongSteps.PLACING_WOOD:
            return reverse("cats-birdsong-place-wood")
        case _:
            raise ValueError(f"Invalid cats birdsong step: {phase.step}")


def get_cats_daylight_turn_action(phase: CatDaylight):
    match phase.step:
        case CatDaylight.CatDaylightSteps.CRAFTING:
            return reverse("cats-daylight-craft")
        case CatDaylight.CatDaylightSteps.ACTIONS:
            return reverse("cats-daylight-actions")
        case _:
            raise ValueError("Invalid cats daylight step")


def get_cats_evening_turn_action(phase: CatEvening):
    match phase.step:
        case CatEvening.CatEveningSteps.DRAWING:
            return reverse("cats-evening-draw-cards")
        case CatEvening.CatEveningSteps.DISCARDING:
            return reverse("cats-evening-discard-cards")
        case _:
            raise ValueError("Invalid cats evening step")


def get_birds_birdsong_turn_action(phase: BirdBirdsong):
    match phase.step:
        case BirdBirdsong.BirdBirdsongSteps.NOT_STARTED | BirdBirdsong.BirdBirdsongSteps.ADD_TO_DECREE:
            return reverse("birds-add-to-decree")
        case BirdBirdsong.BirdBirdsongSteps.EMERGENCY_DRAWING:
            return reverse("birds-emergency-draw")
        case BirdBirdsong.BirdBirdsongSteps.EMERGENCY_ROOSTING:
            return reverse("birds-emergency-roosting")
        case _:
            raise ValueError(f"Invalid birds birdsong step: {phase.step}")


def get_birds_daylight_turn_action(phase: BirdDaylight):
    match phase.step:
        case BirdDaylight.BirdDaylightSteps.CRAFTING:
            return reverse("birds-craft")
        case BirdDaylight.BirdDaylightSteps.RECRUITING:
            return reverse("birds-recruit")
        case BirdDaylight.BirdDaylightSteps.MOVING:
            return reverse("birds-move")
        case BirdDaylight.BirdDaylightSteps.BATTLING:
            return reverse("birds-battle")
        case BirdDaylight.BirdDaylightSteps.BUILDING:
            return reverse("birds-build")
        case _:
            raise ValueError(f"Invalid birds daylight step: {phase.step}")


def get_birds_evening_turn_action(phase: BirdEvening):
    match phase.step:
        case BirdEvening.BirdEveningSteps.DISCARDING:
            return reverse("birds-discard-cards")
        case _:
            raise ValueError(f"Invalid birds evening step: {phase.step}")


def get_birds_turn_action(player: Player) -> str | None:
    """Return the current birds turn action route for the player or raises if unexpected step"""
    phase = get_birds_phase(player)
    match phase:
        case BirdBirdsong():
            return get_birds_birdsong_turn_action(phase)
        case BirdDaylight():
            return get_birds_daylight_turn_action(phase)
        case BirdEvening():
            return get_birds_evening_turn_action(phase)
        case _:
            raise ValueError("Invalid birds phase")


def get_wa_turn_action(player: Player) -> str | None:
    """Return the current wa turn action route for the player or raises if unexpected step"""
    phase = get_wa_phase(player)
    match phase:
        case WABirdsong():
            return get_wa_birdsong_turn_action(phase)
        case WADaylight():
            return get_wa_daylight_turn_action(phase)
        case WAEvening():
            return get_wa_evening_turn_action(phase)
        case _:
            raise ValueError("Invalid wa phase")


def get_wa_birdsong_turn_action(phase: WABirdsong):
    match phase.step:
        case WABirdsong.WABirdsongSteps.NOT_STARTED | WABirdsong.WABirdsongSteps.REVOLT:
            return reverse("wa-revolt")
        case WABirdsong.WABirdsongSteps.SPREAD_SYMPATHY:
            return reverse("wa-spread-sympathy")
        case _:
            raise ValueError(f"Invalid Woodland Alliance birdsong step: {phase.step}")


def get_wa_daylight_turn_action(phase: WADaylight):
    match phase.step:
        case WADaylight.WADaylightSteps.ACTIONS:
            return reverse("wa-daylight")
        case _:
            raise ValueError("Invalid Woodland Alliance daylight step")


def get_wa_evening_turn_action(phase: WAEvening):
    match phase.step:
        case WAEvening.WAEveningSteps.MILITARY_OPERATIONS:
            return reverse("wa-operations")
        case WAEvening.WAEveningSteps.DISCARDING:
            return reverse("wa-discard-cards")
        case _:
            raise ValueError("Invalid Woodland Alliance evening step")


def get_crows_turn_action(player: Player) -> str | None:
    """Return the current crows turn action route for the player."""
    phase = get_crows_phase(player)
    match phase:
        case CrowBirdsong():
            return get_crows_birdsong_turn_action(phase)
        case CrowDaylight():
            return get_crows_daylight_turn_action(phase)
        case CrowEvening():
            return get_crows_evening_turn_action(phase)
        case _:
            raise ValueError(f"Invalid crows phase: {phase}")


def get_crows_birdsong_turn_action(phase: CrowBirdsong):
    match phase.step:
        case CrowBirdsong.CrowBirdsongSteps.CRAFT:
            return reverse("crows-crafting")
        case CrowBirdsong.CrowBirdsongSteps.FLIP:
            return reverse("crows-flipping")
        case CrowBirdsong.CrowBirdsongSteps.RECRUIT:
            return reverse("crows-recruiting")
        case CrowBirdsong.CrowBirdsongSteps.COMPLETED:
            return None
        case _:
            raise ValueError(f"Invalid crows birdsong step: {phase.step}")


def get_crows_daylight_turn_action(phase: CrowDaylight):
    match phase.step:
        case CrowDaylight.CrowDaylightSteps.ACTIONS:
            return reverse("crows-daylight")
        case CrowDaylight.CrowDaylightSteps.COMPLETED:
            return None
        case _:
            raise ValueError("Invalid crows daylight step")


def get_crows_evening_turn_action(phase: CrowEvening):
    match phase.step:
        case CrowEvening.CrowEveningSteps.EXERT:
            return reverse("crows-exert")
        case CrowEvening.CrowEveningSteps.DISCARDING:
            return reverse("crows-discard-cards")
        case CrowEvening.CrowEveningSteps.DRAWING:
            return None
        case CrowEvening.CrowEveningSteps.COMPLETED:
            return None
        case _:
            raise ValueError("Invalid crows evening step")


def get_moles_turn_action(player: Player) -> str | None:
    """Return the current moles turn action route for the player or raises if unexpected step"""
    phase = get_moles_phase(player)
    match phase:
        case MoleBirdsong():
            return get_moles_birdsong_turn_action(phase)
        case MoleDaylight():
            return get_moles_daylight_turn_action(phase)
        case MoleEvening():
            return get_moles_evening_turn_action(phase)
        case _:
            raise ValueError("Invalid moles phase")


def get_moles_birdsong_turn_action(phase: MoleBirdsong):
    match phase.step:
        case MoleBirdsong.MoleBirdsongSteps.PLACE_WARRIORS:
            return None
        case MoleBirdsong.MoleBirdsongSteps.COMPLETED:
            return None
        case _:
            raise ValueError(f"Invalid moles birdsong step: {phase.step}")


def get_moles_daylight_turn_action(phase: MoleDaylight):
    match phase.step:
        case MoleDaylight.MoleDaylightSteps.ACTIONS:
            return reverse("moles-daylight-actions")
        case MoleDaylight.MoleDaylightSteps.MINISTER_ACTIONS:
            return reverse("moles-minister-actions")
        case MoleDaylight.MoleDaylightSteps.SWAY_MINISTER:
            return reverse("moles-sway-minister")
        case MoleDaylight.MoleDaylightSteps.BEFORE_END | MoleDaylight.MoleDaylightSteps.COMPLETED:
            return None
        case _:
            raise ValueError("Invalid moles daylight step")


def get_moles_evening_turn_action(phase: MoleEvening):
    match phase.step:
        case MoleEvening.MoleEveningSteps.PROCESS_REVEALED_CARDS:
            return None
        case MoleEvening.MoleEveningSteps.CRAFT:
            return reverse("moles-craft")
        case MoleEvening.MoleEveningSteps.DRAW:
            return None
        case MoleEvening.MoleEveningSteps.DISCARD:
            return reverse("moles-discard")
        case MoleEvening.MoleEveningSteps.BEFORE_END:
            return None
        case MoleEvening.MoleEveningSteps.COMPLETED:
            return None
        case _:
            return None


def get_rats_turn_action(player: Player) -> str | None:
    """Return the current rats turn action route for the player or raises if unexpected step."""
    phase = get_rats_phase(player)
    match phase:
        case RatsBirdsong():
            return get_rats_birdsong_turn_action(phase)
        case RatsDaylight():
            return get_rats_daylight_turn_action(phase)
        case RatsEvening():
            return get_rats_evening_turn_action(phase)
        case _:
            raise ValueError(f"Invalid rats phase: {phase}")


def get_rats_birdsong_turn_action(phase: RatsBirdsong) -> str | None:
    match phase.step:
        case RatsBirdsong.Steps.SPREAD_MOB:
            return reverse("rats-birdsong-spread-mob")
        case RatsBirdsong.Steps.CHOOSE_MOOD:
            return reverse("rats-birdsong-choose-mood")
        case _:
            # All other steps (RAZE, RECRUIT, ANOINT, BEFORE_END, COMPLETED, NOT_STARTED)
            # are handled automatically by step_effect
            return None


def get_rats_daylight_turn_action(phase: RatsDaylight) -> str | None:
    match phase.step:
        case RatsDaylight.Steps.CRAFT:
            return reverse("rats-daylight-craft")
        case RatsDaylight.Steps.COMMAND:
            return reverse("rats-daylight-command")
        case RatsDaylight.Steps.ADVANCE:
            return reverse("rats-daylight-advance")
        case _:
            return None


def get_rats_evening_turn_action(phase: RatsEvening) -> str | None:
    match phase.step:
        case RatsEvening.Steps.INCITE:
            return reverse("rats-evening-incite")
        case RatsEvening.Steps.DISCARD:
            return reverse("rats-evening-discard")
        case _:
            # OPPRESS, DRAW, BEFORE_END, COMPLETED — auto-fire or end-of-turn
            return None
