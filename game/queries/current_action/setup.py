from django.urls import reverse
from game.models.birds.setup import BirdsSimpleSetup
from game.models.cats.setup import CatsSimpleSetup
from game.models.crows.setup import CrowsSimpleSetup
from game.models.moles.setup import MolesSimpleSetup
from game.models.rats.setup import RatsSimpleSetup
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Faction, Game, Player


def get_setup_action(game: Game) -> str | None:
    """Return the current setup action route for the game.
    Returns None if the next set of actions should be examined.
    Raises if there is an inconsistency in the setup status
    """
    setup = GameSimpleSetup.objects.get(game=game)
    match setup.status:
        case GameSimpleSetup.GameSetupStatus.CATS_SETUP:
            return get_cats_setup_action(game)
        case GameSimpleSetup.GameSetupStatus.BIRDS_SETUP:
            return get_birds_setup_action(game)
        case GameSimpleSetup.GameSetupStatus.WA_SETUP:
            # WA setup is now fully automatic and bypassed in next_player_setup
            return None
        case GameSimpleSetup.GameSetupStatus.VB_SETUP:
            # Placeholder until VB setup views are implemented
            return None
        case GameSimpleSetup.GameSetupStatus.CROWS_SETUP:
            return get_crows_setup_action(game)
        case GameSimpleSetup.GameSetupStatus.MOLES_SETUP:
            return get_moles_setup_action(game)
        case GameSimpleSetup.GameSetupStatus.RATS_SETUP:
            return get_rats_setup_action(game)
        case GameSimpleSetup.GameSetupStatus.COMPLETED:
            return None
        case _:
            raise ValueError(f"Invalid setup status: {setup.status}")


def get_cats_setup_action(game: Game) -> str | None:
    """Return the current cats setup action route for the game or raises if unexpected step"""
    cat_player = Player.objects.get(game=game, faction=Faction.CATS)
    cats_setup = CatsSimpleSetup.objects.get(player=cat_player)
    match cats_setup.step:
        case CatsSimpleSetup.Steps.PICKING_CORNER:
            return reverse("cats-setup-pick-corner")
        case CatsSimpleSetup.Steps.PLACING_BUILDINGS:
            return reverse("cats-setup-place-initial-building")
        case CatsSimpleSetup.Steps.PENDING_CONFIRMATION:
            return reverse("cats-setup-confirm-completed-setup")
        case _:
            raise ValueError("Invalid cats setup step")


def get_birds_setup_action(game: Game) -> str | None:
    """Return the current birds setup action route for the game or raises if unexpected step"""
    bird_player = Player.objects.get(game=game, faction=Faction.BIRDS)
    birds_setup = BirdsSimpleSetup.objects.get(player=bird_player)
    match birds_setup.step:
        case BirdsSimpleSetup.Steps.PICKING_CORNER:
            return reverse("birds-setup-pick-corner")
        case BirdsSimpleSetup.Steps.CHOOSING_LEADER:
            return reverse("birds-setup-choose-leader")
        case BirdsSimpleSetup.Steps.PENDING_CONFIRMATION:
            return reverse("birds-setup-confirm-completed-setup")
        case _:
            raise ValueError("Invalid birds setup step")


def get_crows_setup_action(game: Game) -> str | None:
    """Return the current crows setup action route for the game or raises if unexpected step"""
    crow_player = Player.objects.get(game=game, faction=Faction.CROWS)
    crows_setup = CrowsSimpleSetup.objects.get(player=crow_player)
    match crows_setup.step:
        case CrowsSimpleSetup.Steps.WARRIOR_PLACE:
            return reverse("crows-setup-pick-clearing")
        case CrowsSimpleSetup.Steps.PENDING_CONFIRMATION:
            return reverse("crows-setup-confirm-completed-setup")
        case _:
            raise ValueError("Invalid crows setup step")


def get_moles_setup_action(game: Game) -> str | None:
    """Return the current moles setup action route for the game or raises if unexpected step"""
    moles_player = Player.objects.get(game=game, faction=Faction.MOLES)
    moles_setup = MolesSimpleSetup.objects.get(player=moles_player)
    match moles_setup.step:
        case MolesSimpleSetup.Steps.PICKING_CORNER:
            return reverse("moles-setup-pick-corner")
        case MolesSimpleSetup.Steps.PENDING_CONFIRMATION:
            return reverse("moles-setup-confirm-completed-setup")
        case _:
            raise ValueError("Invalid moles setup step")


def get_rats_setup_action(game: Game) -> str | None:
    """Return the current rats setup action route for the game or raises if unexpected step."""
    rats_player = Player.objects.get(game=game, faction=Faction.RATS)
    rats_setup = RatsSimpleSetup.objects.get(player=rats_player)
    match rats_setup.step:
        case RatsSimpleSetup.Steps.PICKING_CORNER:
            return reverse("rats-setup-pick-corner")
        case RatsSimpleSetup.Steps.PENDING_CONFIRMATION:
            return reverse("rats-setup-confirm-completed-setup")
        case _:
            raise ValueError("Invalid rats setup step")
