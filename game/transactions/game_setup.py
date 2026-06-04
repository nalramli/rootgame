from random import shuffle
from django.contrib.auth.models import User
from django.db import transaction, models
from game.errors import UnavailableActionError, IllegalActionError, InternalGameError
from game.models import (
    BuildingSlot,
    Card,
    Clearing,
    CraftableItemEntry,
    DeckEntry,
    FactionChoiceEntry,
    Game,
    Item,
    ItemTypes,
    Player,
    Ruin,
    Suit,
)
from game.game_data.cards.exiles_and_partisans import deck as exile_deck
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Faction

from game.transactions.birds_setup import start_simple_birds_setup
from game.transactions.cats_setup import start_simple_cats_setup
from game.transactions.crows_setup import start_simple_crows_setup
from game.transactions.moles_setup import start_simple_moles_setup
from game.transactions.general import draw_card_from_deck_to_hand
from game.transactions.setup_util import next_player_setup
from game.transactions.wa_setup import wa_setup
from game.utility.textchoice import next_choice


def create_new_game(
    owner: User, map: Game.BoardMaps, faction_options: list[Faction]
) -> Game:
    game = Game(boardmap=map, owner=owner)
    game.save()
    for faction_option in faction_options:
        FactionChoiceEntry.objects.create(game=game, faction=faction_option)
    return game


def add_new_player_to_game(game: Game, user_to_add: User) -> Player:
    # check that user is not already in game
    if Player.objects.filter(game=game, user=user_to_add).exists():
        raise IllegalActionError("User is already in game")
    # check there aren't already as many players as faction choices
    player_count = Player.objects.filter(game=game).count()
    faction_count = FactionChoiceEntry.objects.filter(game=game).count()
    if player_count >= faction_count:
        raise IllegalActionError(
            f"Can't add a { player_count + 1 }th player, there are only { faction_count } factions"
        )
    # create player
    player = Player(
        user=user_to_add,
        game=game,
        faction=None,
    )
    player.save()
    return player


@transaction.atomic
def player_picks_faction(player: Player, faction: FactionChoiceEntry):
    if faction.game != player.game:
        raise UnavailableActionError("faction and player games do not match")
    if faction.chosen:
        raise IllegalActionError("faction has already been chosen")
    faction.chosen = True
    player.faction = faction.faction
    faction.save()
    player.save()


@transaction.atomic
def assign_turn_order(game: Game):
    players = Player.objects.filter(game=game)
    # determine player turn order according to faction guide
    faction_turn_orders = {
        Faction.CATS: 0,
        Faction.BIRDS: 1,
        Faction.WOODLAND_ALLIANCE: 2,
        Faction.CROWS: 7,
        Faction.MOLES: 8,
        Faction.RATS: 9,
    }
    # rank players by faction turn order value
    # this will be useful when there are more factions
    player_turn_orders = []
    for player in players:
        player_turn_orders.append((faction_turn_orders[player.faction], player))
    player_turn_orders.sort(key=lambda x: x[0])
    # assign turn order to players according to the ranking
    for i, (_, player) in enumerate(player_turn_orders):
        player.turn_order = i
        player.save()


@transaction.atomic
def create_craftable_item_supply(game: Game):
    # create craftable items
    items = {
        ItemTypes.BOOTS: 2,
        ItemTypes.BAG: 2,
        ItemTypes.CROSSBOW: 1,
        ItemTypes.HAMMER: 1,
        ItemTypes.SWORD: 2,
        ItemTypes.TEA: 2,
        ItemTypes.COIN: 2,
    }
    for item_type, amount in items.items():
        for i in range(amount):
            item = Item(game=game, item_type=item_type)
            item.save()
            CraftableItemEntry(game=game, item=item).save()


@transaction.atomic
def autumn_map_setup(game: Game):

    # numbers based on map from https://www.therootdatabase.com/map/autumn/
    # 0 based in python, but one based in the map.

    # create clearings. lets start without randomizing the clearing numbers
    clearings = [Clearing(game=game, clearing_number=i + 1) for i in range(0, 12)]
    # assign suits
    fox = [1, 6, 8, 12]
    rabbit = [3, 4, 5, 10]
    mouse = [2, 7, 9, 11]
    for i in fox:
        clearings[i - 1].suit = "r"
    for i in rabbit:
        clearings[i - 1].suit = "y"
    for i in mouse:
        clearings[i - 1].suit = "o"
    # presave clearings because we need pks to connect them via m2m relationships
    for clearing in clearings:
        clearing.save()
    # connect clearings. this is a lot of redundant work but easier to comapre to a map
    clearings[0].connected_clearings.add(clearings[4], clearings[8], clearings[9])
    clearings[1].connected_clearings.add(clearings[4], clearings[5], clearings[9])
    clearings[2].connected_clearings.add(clearings[5], clearings[6], clearings[10])
    clearings[3].connected_clearings.add(clearings[7], clearings[8], clearings[11])
    clearings[4].connected_clearings.add(clearings[0], clearings[1])
    clearings[5].connected_clearings.add(clearings[1], clearings[2], clearings[10])
    clearings[6].connected_clearings.add(clearings[2], clearings[7], clearings[11])
    clearings[7].connected_clearings.add(clearings[3], clearings[6])
    clearings[8].connected_clearings.add(clearings[0], clearings[3], clearings[11])
    clearings[9].connected_clearings.add(clearings[0], clearings[1], clearings[11])
    clearings[10].connected_clearings.add(clearings[2], clearings[5], clearings[11])
    clearings[11].connected_clearings.add(
        clearings[3], clearings[6], clearings[8], clearings[9], clearings[10]
    )
    # water connected clearings. adding in order since connections are max 2.
    clearings[3].water_connected_clearings.add(clearings[6])
    clearings[6].water_connected_clearings.add(clearings[10])
    clearings[10].water_connected_clearings.add(clearings[9])
    clearings[9].water_connected_clearings.add(clearings[4])

    # save clearings again now that we have all the connections
    for clearing in clearings:
        clearing.save()

    # create building slots
    slot_counts = [1, 2, 1, 1, 2, 2, 2, 2, 2, 2, 3, 2]  # index is clearing number
    for i in range(len(clearings)):
        for j in range(slot_counts[i]):
            BuildingSlot(clearing=clearings[i], building_slot_number=j).save()

    # add ruins with randomized ruin items
    ruin_clearings = [5, 9, 10, 11]  # 0 based
    ruin_item_types = [
        ItemTypes.BAG,
        ItemTypes.BOOTS,
        ItemTypes.HAMMER,
        ItemTypes.SWORD,
    ]
    shuffle(ruin_item_types)
    for idx, i in enumerate(ruin_clearings):
        clearing = clearings[i]
        # this doesnt allow for more than one ruin per clearing
        # which is fine for all official maps
        building_slot = BuildingSlot.objects.filter(clearing=clearing).last()
        item = Item(game=game, item_type=ruin_item_types[idx])
        item.save()
        ruin = Ruin(game=game, building_slot=building_slot, item=item)
        ruin.save()


@transaction.atomic
def map_setup(game: Game):
    if game.boardmap == Game.BoardMaps.AUTUMN:
        autumn_map_setup(game)
    else:
        raise InternalGameError("Board map not supported")


@transaction.atomic
def construct_deck(game: Game):
    # create deck. because bulk creating, save logic not applied! must specify suit
    deck = [
        Card(game=game, card_type=card.name, suit=card.value.suit.value[0])
        for card in exile_deck
    ]
    Card.objects.bulk_create(deck)
    shuffle(deck)
    deck_entries = [
        DeckEntry(game=game, card=deck[i], spot=i) for i in range(len(deck))
    ]
    DeckEntry.objects.bulk_create(deck_entries)


@transaction.atomic()
def create_game_setup(game: Game):
    GameSimpleSetup(
        game=game, status=GameSimpleSetup.GameSetupStatus.INITIAL_SETUP
    ).save()


@transaction.atomic
def begin_faction_setup(game: Game):
    from game.transactions.rats_setup import start_simple_rats_setup

    setup_func_dict = {
        Faction.CATS: start_simple_cats_setup,
        Faction.BIRDS: start_simple_birds_setup,
        Faction.WOODLAND_ALLIANCE: wa_setup,
        Faction.CROWS: start_simple_crows_setup,
        Faction.MOLES: start_simple_moles_setup,
        Faction.RATS: start_simple_rats_setup,
    }
    players = Player.objects.filter(game=game)
    for player in players:
        setup_func_dict[player.faction](player)


@transaction.atomic
def deal_starting_cards(game: Game):
    # deal starting cards
    for player in Player.objects.filter(game=game):
        # deal cards
        for i in range(3):
            draw_card_from_deck_to_hand(player)


@transaction.atomic
def start_game(game: Game):
    if game.status != Game.GameStatus.NOT_STARTED:
        raise UnavailableActionError("Game is already started")
    players = Player.objects.filter(game=game)
    if any(player.faction is None for player in players):
        raise UnavailableActionError("Not all players have selected a faction")
    create_game_setup(game)
    map_setup(game)
    construct_deck(game)
    create_craftable_item_supply(game)
    deal_starting_cards(game)
    next_player_setup(game)
    # simple_setup = GameSimpleSetup.objects.get(game=game)
    # simple_setup.status = GameSimpleSetup.GameSetupStatus.CATS_SETUP
    # simple_setup.save()
    begin_faction_setup(game)
    game.status = Game.GameStatus.STARTED
    game.save()
