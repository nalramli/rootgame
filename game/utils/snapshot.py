from django.core import serializers
from itertools import chain

# Import all models
from game.models.game_models import (
    Game,
    FactionChoiceEntry,
    Clearing,
    BuildingSlot,
    Warrior,
    Building,
    Token,
    Ruin,
    Piece,
    Card,
    DeckEntry,
    DiscardPileEntry,
    Item,
    CraftableItemEntry,
    CraftedItemEntry,
    CraftedCardEntry,
    HandEntry,
    RevealedCardEntry,
    CoffinWarrior,
)
from game.models.dominance import DominanceSupplyEntry, ActiveDominanceEntry
from game.models.birds.player import BirdLeader, DecreeEntry, Vizier
from game.models.birds.buildings import BirdRoost
from game.models.birds.turn import BirdTurn, BirdBirdsong, BirdDaylight, BirdEvening

from game.models.cats.buildings import Workshop, Sawmill, Recruiter
from game.models.cats.tokens import CatKeep, CatWood
from game.models.cats.turn import CatTurn, CatBirdsong, CatDaylight, CatEvening

from game.models.wa.buildings import WABase
from game.models.wa.tokens import WASympathy
from game.models.wa.player import SupporterStackEntry, OfficerEntry
from game.models.wa.turn import WATurn, WABirdsong, WADaylight, WAEvening

from game.models.crows.setup import CrowsSimpleSetup
from game.models.crows.tokens import PlotToken
from game.models.crows.turn import CrowTurn, CrowBirdsong, CrowDaylight, CrowEvening
from game.models.crows.exposure import ExposureRevealedCards, ExposureGuessedPlot

from game.models.moles.burrow import Burrow
from game.models.moles.crown import Crown
from game.models.moles.tokens import Tunnel
from game.models.moles.buildings import Citadel, Market
from game.models.moles.ministers import Minister
from game.models.moles.turn import MoleTurn, MoleBirdsong, MoleDaylight, MoleEvening
from game.models.moles.setup import MolesSimpleSetup

from game.models.rats.setup import RatsSimpleSetup
from game.models.rats.player import CommandItemEntry, ProwessItemEntry, RatsPlayerState
from game.models.rats.buildings import Stronghold
from game.models.rats.tokens import Mob, Warlord
from game.models.rats.turn import RatsTurn, RatsBirdsong, RatsDaylight, RatsEvening

from game.models.events.event import Event
from game.models.events.battle import Battle
from game.models.events.wa import OutrageEvent
from game.models.events.birds import TurmoilEvent
from game.models.events.cats import FieldHospitalEvent
from game.models.events.setup import GameSimpleSetup
from game.models.cats.setup import CatsSimpleSetup
from game.models.birds.setup import BirdsSimpleSetup
from game.models.events.crafted_cards import (
    InformantsEvent,
    EyrieEmigreEvent,
    SaboteursEvent,
    CharmOffensiveEvent,
    PartisansEvent,
    SwapMeetEvent,
)
from game.models.events.crows import CrowRecruitEvent, CrowRaidEvent
from game.models.events.moles import PriceOfFailureEvent
from game.models.events.rats import HoardTooFullEvent, JubilantMobSpreadEvent, LavishEvent, LootingEvent, ResolveBitterEvent
from game.models.removal_tracker import RemovalEventTracker
from game.models.game_log import GameLog


def get_all_game_objects(game: Game):
    """
    Collects all model instances related to the given game instance.
    Returns a list of objects in an order suitable for serialization (dependencies first).
    """
    objects = []

    # 1. Root Game Object
    objects.append(game)

    # 2. Static-ish components (depend on Game)
    objects.extend(FactionChoiceEntry.objects.filter(game=game))
    objects.extend(Clearing.objects.filter(game=game))
    # Moles Burrows (special Clearing variant)
    objects.extend(Burrow.objects.filter(game=game))
    # BuildingSlot depends on Clearing
    objects.extend(BuildingSlot.objects.filter(clearing__game=game))

    # Cards & Items (Global/Game level)
    objects.extend(Card.objects.filter(game=game))
    objects.extend(Item.objects.filter(game=game))

    # Game State Collections (Deck, Discard, Ruins, Craftable)
    objects.extend(DeckEntry.objects.filter(game=game))
    objects.extend(DiscardPileEntry.objects.filter(game=game))
    objects.extend(Ruin.objects.filter(game=game))
    objects.extend(CraftableItemEntry.objects.filter(game=game))
    objects.extend(DominanceSupplyEntry.objects.filter(game=game))

    # Setup State (depend on Game)
    objects.extend(GameSimpleSetup.objects.filter(game=game))

    # 3. Players and their direct assets
    players = game.players.all().order_by("turn_order")
    objects.extend(players)

    for player in players:
        # Player generic assets
        objects.extend(HandEntry.objects.filter(player=player))
        objects.extend(RevealedCardEntry.objects.filter(player=player))
        objects.extend(CraftedItemEntry.objects.filter(player=player))
        objects.extend(CraftedCardEntry.objects.filter(player=player))
        objects.extend(ActiveDominanceEntry.objects.filter(player=player))
        objects.extend(CoffinWarrior.objects.filter(player=player))

        # Setup state (depend on Player)
        objects.extend(CatsSimpleSetup.objects.filter(player=player))
        objects.extend(BirdsSimpleSetup.objects.filter(player=player))
        objects.extend(CrowsSimpleSetup.objects.filter(player=player))
        objects.extend(MolesSimpleSetup.objects.filter(player=player))
        objects.extend(RatsSimpleSetup.objects.filter(player=player))

        # Pieces (Warriors, Buildings, Tokens)
        # For MTI (Multi-Table Inheritance), we MUST serialize the base models as well
        # to capture the inherited fields (like 'player' on Piece, 'clearing' on Token).
        # Order matters: Base -> Child.

        # 3a. Base Piece (Parent of Token, Building, Warrior)
        # Note: We filter by player to keep it organized, though we could do bulk query.
        objects.extend(Piece.objects.filter(player=player))

        # 3b. Intermediate Bases (Token, Building)
        objects.extend(Token.objects.filter(player=player))
        objects.extend(Building.objects.filter(player=player))

        # 3c. Leaf Classes
        # Warriors (Direct child of Piece)
        objects.extend(Warrior.objects.filter(player=player))

        # Faction Specific Assets & Pieces
        # Birds
        objects.extend(BirdLeader.objects.filter(player=player))
        objects.extend(DecreeEntry.objects.filter(player=player))
        objects.extend(Vizier.objects.filter(player=player))
        objects.extend(BirdRoost.objects.filter(player=player))

        # Cats
        objects.extend(Workshop.objects.filter(player=player))
        objects.extend(Sawmill.objects.filter(player=player))
        objects.extend(Recruiter.objects.filter(player=player))
        objects.extend(CatKeep.objects.filter(player=player))
        objects.extend(CatWood.objects.filter(player=player))

        # WA
        objects.extend(WABase.objects.filter(player=player))
        objects.extend(WASympathy.objects.filter(player=player))
        objects.extend(SupporterStackEntry.objects.filter(player=player))
        objects.extend(OfficerEntry.objects.filter(player=player))

        # Turn History / State
        # Birds
        bird_turns = BirdTurn.objects.filter(player=player)
        objects.extend(bird_turns)
        objects.extend(BirdBirdsong.objects.filter(turn__in=bird_turns))
        objects.extend(BirdDaylight.objects.filter(turn__in=bird_turns))
        objects.extend(BirdEvening.objects.filter(turn__in=bird_turns))

        # Cats
        cat_turns = CatTurn.objects.filter(player=player)
        objects.extend(cat_turns)
        objects.extend(CatBirdsong.objects.filter(turn__in=cat_turns))
        objects.extend(CatDaylight.objects.filter(turn__in=cat_turns))
        objects.extend(CatEvening.objects.filter(turn__in=cat_turns))

        # WA
        wa_turns = WATurn.objects.filter(player=player)
        objects.extend(wa_turns)
        objects.extend(WABirdsong.objects.filter(turn__in=wa_turns))
        objects.extend(WADaylight.objects.filter(turn__in=wa_turns))
        objects.extend(WAEvening.objects.filter(turn__in=wa_turns))

        # Crows
        crow_turns = CrowTurn.objects.filter(player=player)
        objects.extend(crow_turns)
        objects.extend(CrowBirdsong.objects.filter(turn__in=crow_turns))
        objects.extend(CrowDaylight.objects.filter(turn__in=crow_turns))
        objects.extend(CrowEvening.objects.filter(turn__in=crow_turns))
        objects.extend(PlotToken.objects.filter(player=player))
        objects.extend(ExposureRevealedCards.objects.filter(player=player))
        objects.extend(ExposureGuessedPlot.objects.filter(player=player))

        # Moles
        objects.extend(Crown.objects.filter(player=player))
        objects.extend(Minister.objects.filter(player=player))
        objects.extend(Tunnel.objects.filter(player=player))
        objects.extend(Citadel.objects.filter(player=player))
        objects.extend(Market.objects.filter(player=player))

        # Turn History / State
        mole_turns = MoleTurn.objects.filter(player=player)
        objects.extend(mole_turns)
        objects.extend(MoleBirdsong.objects.filter(turn__in=mole_turns))
        objects.extend(MoleDaylight.objects.filter(turn__in=mole_turns))
        objects.extend(MoleEvening.objects.filter(turn__in=mole_turns))

        # Rats
        objects.extend(RatsPlayerState.objects.filter(player=player))
        objects.extend(CommandItemEntry.objects.filter(player=player))
        objects.extend(ProwessItemEntry.objects.filter(player=player))
        objects.extend(Stronghold.objects.filter(player=player))
        objects.extend(Mob.objects.filter(player=player))
        objects.extend(Warlord.objects.filter(player=player))

        # Rats Turn History / State
        rats_turns = RatsTurn.objects.filter(player=player)
        objects.extend(rats_turns)
        objects.extend(RatsBirdsong.objects.filter(turn__in=rats_turns))
        objects.extend(RatsDaylight.objects.filter(turn__in=rats_turns))
        objects.extend(RatsEvening.objects.filter(turn__in=rats_turns))


    # 4. Removal Tracker (depends on Game)
    removal_tracker = RemovalEventTracker.objects.filter(game=game).first()
    if removal_tracker:
        objects.append(removal_tracker)

    # 5. Events
    # Events depend on Game, but sub-events depend on Event + Players/Clearings
    events = Event.objects.filter(game=game)
    objects.extend(events)
    # Sub-events (OneToOne)
    objects.extend(Battle.objects.filter(event__in=events))
    objects.extend(OutrageEvent.objects.filter(event__in=events))
    objects.extend(TurmoilEvent.objects.filter(event__in=events))
    objects.extend(FieldHospitalEvent.objects.filter(event__in=events))
    objects.extend(InformantsEvent.objects.filter(event__in=events))
    objects.extend(EyrieEmigreEvent.objects.filter(event__in=events))
    objects.extend(SaboteursEvent.objects.filter(event__in=events))
    objects.extend(CharmOffensiveEvent.objects.filter(event__in=events))
    objects.extend(PartisansEvent.objects.filter(event__in=events))
    objects.extend(SwapMeetEvent.objects.filter(event__in=events))
    objects.extend(CrowRecruitEvent.objects.filter(event__in=events))
    objects.extend(CrowRaidEvent.objects.filter(event__in=events))
    objects.extend(PriceOfFailureEvent.objects.filter(event__in=events))
    objects.extend(HoardTooFullEvent.objects.filter(event__in=events))
    objects.extend(LootingEvent.objects.filter(event__in=events))
    objects.extend(ResolveBitterEvent.objects.filter(event__in=events))
    objects.extend(JubilantMobSpreadEvent.objects.filter(event__in=events))
    objects.extend(LavishEvent.objects.filter(event__in=events))

    # 6. Game Logs
    objects.extend(GameLog.objects.filter(game=game).order_by("created_at"))

    return objects


import json


def capture_gamestate(game: Game) -> list:
    """
    Captures the full state of the game as a list of dicts (fixture format).
    Ensures datetimes are serialized to strings for JSONField compatibility.
    """
    objects = get_all_game_objects(game)
    # Use 'json' serializer to handle datetimes, then load back to a list of dicts
    json_data = serializers.serialize("json", objects)
    return json.loads(json_data)
