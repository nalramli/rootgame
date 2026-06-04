from game.models.game_models import Faction
from game.models import Player
from django.db import transaction
from rest_framework.exceptions import ValidationError
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.events.event import Event, EventType
from game.models.events.crafted_cards import InformantsEvent
from game.models.game_models import CraftedCardEntry, DiscardPileEntry, HandEntry, Card

@transaction.atomic
def use_informants(crafted_card_entry: CraftedCardEntry, ambush_card_in_discard: DiscardPileEntry):
    if crafted_card_entry.card.card_type != CardsEP.INFORMANTS.name:
         raise ValueError("Card is not Informants.")
    
    if crafted_card_entry.used != CraftedCardEntry.UsedChoice.UNUSED:
        raise ValueError("Card has already been used this turn.")

    # Validate ambush card
    card_data = CardsEP[ambush_card_in_discard.card.card_type].value
    if not card_data.ambush:
        raise ValueError("Selected card is not an ambush card.")

    player = crafted_card_entry.player
    game = player.game

    # Move card from discard pile to hand
    HandEntry.objects.create(player=player, card=ambush_card_in_discard.card)
    ambush_card_in_discard.delete()

    # Mark as used
    crafted_card_entry.used = CraftedCardEntry.UsedChoice.USED
    crafted_card_entry.save()

    # Resolve event
    informants_event = InformantsEvent.objects.filter(crafted_card_entry=crafted_card_entry, event__is_resolved=False).first()
    if informants_event:
        informants_event.event.is_resolved = True
        informants_event.event.save()

    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.crafted_cards import log_crafted_card_action
    log_crafted_card_action(
        game,
        player,
        crafted_card_entry.card,
        "use",
        details={
            "card_name": ambush_card_in_discard.card.title
        },
        parent=get_active_phase_log(game)
    )
    #bypass drawing by setting phase step to drawing and calling faction specific next_step
    match player.faction:
        case Faction.WOODLAND_ALLIANCE:
            from game.models.wa.turn import WAEvening
            from game.transactions.wa import next_step
            from game.queries.wa.turn import get_phase
            phase = get_phase(player)
            phase.step = WAEvening.WAEveningSteps.DRAWING
            phase.save()
            next_step(player)
        case Faction.BIRDS:
            from game.models.birds.turn import BirdEvening
            from game.transactions.birds import next_step
            from game.queries.birds.turn import get_phase
            phase = get_phase(player)
            phase.step = BirdEvening.BirdEveningSteps.DRAWING
            phase.save()
            next_step(player)
        case Faction.CATS:
            from game.models.cats.turn import CatEvening
            from game.transactions.cats import next_step
            from game.queries.cats.turn import get_phase
            phase = get_phase(player)
            phase.step = CatEvening.CatEveningSteps.DRAWING
            phase.save()
            next_step(player)
        case _:
            raise ValueError("Faction not implemented yet in informants")
            

@transaction.atomic
def skip_informants(crafted_card_entry: CraftedCardEntry):
    if crafted_card_entry.card.card_type != CardsEP.INFORMANTS.name:
         raise ValueError("Card is not Informants.")

    # Mark as used
    crafted_card_entry.used = CraftedCardEntry.UsedChoice.USED
    crafted_card_entry.save()

    # Resolve event
    informants_event = InformantsEvent.objects.filter(crafted_card_entry=crafted_card_entry, event__is_resolved=False).first()
    if informants_event:
        informants_event.event.is_resolved = True
        informants_event.event.save()
    # Resume the step machine via the general dispatcher (guarded against stacked events).
    player = crafted_card_entry.player
    from game.transactions.general import step_effect
    step_effect(player)


@transaction.atomic
def informants_check(player: Player) -> bool:
    """checks if the player has any unused informants cards, and launches event if so
    returns True if there are unused informants cards, False otherwise
    """
    informants = CraftedCardEntry.objects.filter(player=player, card__card_type=CardsEP.INFORMANTS.name, used=CraftedCardEntry.UsedChoice.UNUSED).first()
    has_informants = informants is not None
    if has_informants:
        InformantsEvent.create(crafted_card_entry=informants)
    return has_informants
