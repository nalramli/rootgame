from django.db import transaction

from game.models import Clearing, Player, Warrior
from game.models.game_models import BuildingSlot
from game.models.rats.buildings import Stronghold
from game.models.rats.tokens import Mob, Warlord
from game.models.rats.player import RatsPlayerState
from game.models.rats.setup import RatsSimpleSetup
from game.models.cats.tokens import CatKeep
from game.models.birds.buildings import BirdRoost
from game.models.moles.tokens import Tunnel
from game.models.events.setup import GameSimpleSetup
from game.errors import UnavailableActionError, IllegalActionError
from game.transactions.setup_util import next_player_setup
from game.transactions.general import place_warriors_into_clearing, place_piece_from_supply_into_clearing, place_building_from_supply_into_slot
from game.utility.textchoice import next_choice
from game.queries.general import available_building_slot


@transaction.atomic
def create_rats_warrior_supply(player: Player):
    """create 20 generic warriors (in supply, null clearing)"""
    warriors = [Warrior(player=player) for _ in range(20)]
    for warrior in warriors:
        warrior.save()


@transaction.atomic
def create_rats_warlord(player: Player):
    """create 1 warlord (in supply, null clearing)"""
    Warlord(player=player, clearing=None).save()


@transaction.atomic
def create_rats_strongholds(player: Player):
    """create 6 strongholds (in supply, null building_slot)"""
    for _ in range(6):
        Stronghold(player=player, building_slot=None).save()


@transaction.atomic
def create_rats_mobs(player: Player):
    """create 5 mob tokens (in supply, null clearing)"""
    for _ in range(5):
        Mob(player=player, clearing=None).save()


@transaction.atomic
def create_rats_player_state(player: Player):
    """create the RatsPlayerState object with default mood (STUBBORN) and state"""
    RatsPlayerState(player=player, mood_type=RatsPlayerState.MoodType.STUBBORN).save()


@transaction.atomic
def start_simple_rats_setup(player: Player) -> RatsSimpleSetup:
    """initialize all rats pieces for setup"""
    create_rats_warrior_supply(player)
    create_rats_warlord(player)
    create_rats_strongholds(player)
    create_rats_mobs(player)
    create_rats_player_state(player)
    setup = RatsSimpleSetup(player=player, step=RatsSimpleSetup.Steps.PICKING_CORNER)
    setup.save()
    return setup


@transaction.atomic
def pick_corner(player: Player, clearing: Clearing):
    """place warlord, 4 warriors, and 1 stronghold in a corner clearing"""
    simple_setup = GameSimpleSetup.objects.get(game=player.game)
    if simple_setup.status != GameSimpleSetup.GameSetupStatus.RATS_SETUP:
        raise UnavailableActionError("Not this player's setup turn")

    rats_setup = RatsSimpleSetup.objects.get(player=player)
    if rats_setup.step != RatsSimpleSetup.Steps.PICKING_CORNER:
        raise UnavailableActionError("this has been triggered at the wrong step")

    # validate corner clearing: clearing_number must be 1–4
    if clearing.clearing_number not in [1, 2, 3, 4]:
        raise IllegalActionError("Clearing number must be 1, 2, 3, or 4 to be a corner")
    if clearing.game != player.game:
        raise IllegalActionError("Clearing is not in the same game")

    # check corner not already claimed by another faction
    if CatKeep.objects.filter(clearing=clearing).exists():
        raise IllegalActionError("Corner already claimed")
    if BirdRoost.objects.filter(building_slot__clearing=clearing).exists():
        raise IllegalActionError("Corner already claimed")
    if Tunnel.objects.filter(clearing=clearing).exists():
        raise IllegalActionError("Corner already claimed")

    # place warlord in the corner clearing
    warlord = Warlord.objects.get(player=player)
    place_piece_from_supply_into_clearing(warlord, clearing)

    # place 4 warriors in the corner clearing
    place_warriors_into_clearing(player, clearing, 4)

    # place 1 stronghold in an available building slot in the corner clearing
    slot = available_building_slot(clearing)
    if slot is None:
        raise IllegalActionError("No available building slot in the chosen corner clearing")
    stronghold = Stronghold.objects.filter(player=player, building_slot__isnull=True).first()
    assert stronghold is not None, "no stronghold in supply during rats setup!"
    place_building_from_supply_into_slot(stronghold, slot)

    # advance setup step
    rats_setup.step = next_choice(RatsSimpleSetup.Steps, rats_setup.step)
    rats_setup.save()


@transaction.atomic
def confirm_completed_setup(player: Player):
    """confirm rats setup is complete and move to next player"""
    rats_setup = RatsSimpleSetup.objects.get(player=player)
    if rats_setup.step != RatsSimpleSetup.Steps.PENDING_CONFIRMATION:
        raise UnavailableActionError("this has been triggered at the wrong step")
    rats_setup.step = next_choice(RatsSimpleSetup.Steps, rats_setup.step)
    rats_setup.save()
    # move to next step in general setup (next player, perhaps)
    next_player_setup(player.game)
