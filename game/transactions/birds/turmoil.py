from django.db import transaction

from game.models.birds.player import BirdLeader, DecreeEntry, Vizier
from game.models.birds.turn import BirdDaylight
from game.models.game_models import DiscardPileEntry, Faction, Player
from game.models.events.birds import TurmoilEvent
from game.models.events.event import Event, EventType
from game.queries.birds.turn import get_phase, get_turmoil_event
from game.queries.general import get_player_hand_size
from game.transactions.general import discard_card_from_hand, raise_score
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.game_models import Suit


@transaction.atomic
def turmoil(player: Player):
    """turmoil the player.
    --lose points,
    --clear their decree,
    --set leader to unavailable
    -- if all leaders unavailable, make them all available
    -- move the daylight step to "completed"
    -- create turmoil event (where player chooses new leader)
    """
    assert player.faction == Faction.BIRDS.value
    # lose points according to birds in decree (2 automatically from viziers)
    points_to_lose = 2
    points_to_lose += DecreeEntry.objects.filter(
        player=player, card__suit=Suit.WILD
    ).count()
    raise_score(player, -points_to_lose)

    # clear the decree: disard all cards and destory the viziers
    cards_lost = 0
    for decree_entry in DecreeEntry.objects.filter(player=player):
        discard_card_from_decree(player, decree_entry)
        cards_lost += 1
    Vizier.objects.filter(player=player).delete()
    # set leader to unavailable and inactive
    current_leader = BirdLeader.objects.get(player=player, active=True)
    current_leader.active = False
    current_leader.available = False
    current_leader.save()
    # if all leaders unavailable, make them all available
    if BirdLeader.objects.filter(player=player, available=False).count() == 4:
        BirdLeader.objects.filter(player=player, available=False).update(available=True)

    # move daylight to completed
    daylight = get_phase(player)
    assert type(daylight) == BirdDaylight

    # derive action string for logging
    action = None
    if daylight.step == BirdDaylight.BirdDaylightSteps.RECRUITING:
        action = "recruit"
    elif daylight.step == BirdDaylight.BirdDaylightSteps.MOVING:
        action = "move"
    elif daylight.step == BirdDaylight.BirdDaylightSteps.BATTLING:
        action = "battle"
    elif daylight.step == BirdDaylight.BirdDaylightSteps.BUILDING:
        action = "build"

    from game.serializers.logs.birds import log_birds_turmoil
    from game.serializers.logs.general import get_current_phase_log
    log_birds_turmoil(player.game, player, points_to_lose, cards_lost, action, parent=get_current_phase_log(player.game, player))

    # create turmoil event
    event = Event.objects.create(game=player.game, type=EventType.TURMOIL)
    TurmoilEvent.objects.create(event=event, player=player)


@transaction.atomic
def discard_card_from_decree(player: Player, decree_entry: DecreeEntry):
    """discards the given card from the player's Decree into the gamediscard pile"""
    # check that decree belongs to player
    if decree_entry.player != player:
        raise ValueError("Decree entry does not belong to player")
    card = decree_entry.card
    decree_entry.delete()
    # add card to discard pile
    discard_pile_entry = DiscardPileEntry.create_from_card(card)


@transaction.atomic
def turmoil_choose_new_leader(player: Player, leader: BirdLeader):
    """chooses a new leader for the given player and resolves the turmoil event
    -- leader msut be available
    """
    # check that leader is available
    if not leader.available:
        raise ValueError("Leader is not available")
    # make leader active
    leader.active = True
    leader.save()
    # create viziers
    Vizier.create_viziers(player=player)
    # resolve turmoil event
    turmoil_event = get_turmoil_event(player)
    turmoil_event.new_leader_chosen = True
    turmoil_event.save()
    event = turmoil_event.event
    event.is_resolved = True
    event.save()

    from game.serializers.logs.birds import log_birds_new_leader
    from game.serializers.logs.general import get_current_phase_log
    log_birds_new_leader(player.game, player, leader, parent=get_current_phase_log(player.game, player))

    # move daylight to completed
    from game.queries.birds.turn import get_phase
    daylight = get_phase(player)
    assert type(daylight) == BirdDaylight
    daylight.step = BirdDaylight.BirdDaylightSteps.COMPLETED
    daylight.save()

    # activate step effects for end of daylight
    from game.transactions.general import step_effect
    step_effect(player)
