
from game.models import DiscardPileEntry
from game.queries.general import get_enemy_factions_in_clearing
from game.transactions.battle import start_battle

from game.models import Clearing
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.events import EyrieEmigreEvent
from game.models import CraftedCardEntry
from django.db import transaction
from game.models.game_models import Faction, Player

@transaction.atomic
def is_emigre(player: Player) -> bool:
    """ checks if the player has an unused eyrie emigre card
    if so, returns True and launches event
    """
    eyrie_emigre = CraftedCardEntry.objects.filter(player=player, card__card_type=CardsEP.EYRIE_EMIGRE.name, used=CraftedCardEntry.UsedChoice.UNUSED).first()
    has_eyrie_emigre = eyrie_emigre is not None
    if has_eyrie_emigre:
        EyrieEmigreEvent.create(crafted_card_entry=eyrie_emigre)
    return has_eyrie_emigre

@transaction.atomic
def emigre_move(event: EyrieEmigreEvent, origin: Clearing, destination: Clearing, count: int, move_warlord: bool = False):
    """
    execute the move action for eyrie emigre event
    Mark the move as completed on the event, and mark the destination clearing
    """
    player = event.crafted_card_entry.player
    # check move hasn't been done yet
    if event.move_completed:
        raise ValueError("Move already completed")
    from game.transactions.general import move_warriors
    move_warriors(player, origin, destination, count, move_warlord=move_warlord)
    event.move_completed = True
    event.move_destination = destination
    event.save()

    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.crafted_cards import log_crafted_card_action
    log_crafted_card_action(
        player.game,
        player,
        event.crafted_card_entry.card,
        "move",
        details={
            "count": count,
            "origin": origin.clearing_number,
            "destination": destination.clearing_number
        },
        parent=get_active_phase_log(player.game)
    )
    # if no enemy in destination, trigger emigre_failure
    enemy_factions = get_enemy_factions_in_clearing(player, destination)

    if len(enemy_factions) == 0:
        emigre_failure(event)

@transaction.atomic
def emigre_battle(event: EyrieEmigreEvent, target_faction : Faction):
    """
    Initiate battle in destination_clearing of emigre event against target_faction
    Mark the battle as initiated on the event,
    mark the card as used, and resolve the event
    """
    if event.battle_initiated:
        raise ValueError("Battle already initiated")
    if not event.move_completed:
        raise ValueError("Move must be completed before battle")
    game = event.event.game
    clearing = event.move_destination
    assert clearing is not None, "Destination Clearing of Emigre Event is None!"
    from game.models.game_models import Faction
    attacking_faction = Faction(event.crafted_card_entry.player.faction)
    defending_faction = target_faction
    #mark battle initiated
    event.battle_initiated = True
    event.save()
    #mark card as used
    event.crafted_card_entry.used = CraftedCardEntry.UsedChoice.USED
    event.crafted_card_entry.save()
    #mark event as resolved
    event.event.is_resolved = True
    event.event.save()

    # Advance the turn machine BEFORE creating the battle event.
    # If we called step_effect after start_battle, the new unresolved
    # BATTLE event would block general.step_effect's guard and the
    # phase would never advance from BirdBirdsong.BEFORE_END.
    from game.transactions.general import step_effect
    step_effect(event.crafted_card_entry.player)

    # Initiate the battle (creates a new unresolved BATTLE event)
    start_battle(game, attacking_faction, defending_faction, clearing)

    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.crafted_cards import log_crafted_card_action
    log_crafted_card_action(
        game,
        event.crafted_card_entry.player,
        event.crafted_card_entry.card,
        "battle",
        details={
            "defender_faction": defending_faction,
            "clearing": clearing.clearing_number
        },
        parent=get_active_phase_log(game)
    )


@transaction.atomic
def emigre_skip(event: EyrieEmigreEvent):
    """
    Skip the Eyrie Emigre event entirely.
    """
    event.event.is_resolved = True
    event.event.save()
    
    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.crafted_cards import log_crafted_card_action
    log_crafted_card_action(
        event.event.game,
        event.crafted_card_entry.player,
        event.crafted_card_entry.card,
        "skip",
        parent=get_active_phase_log(event.event.game)
    )
    
    # mark as used
    event.crafted_card_entry.used = CraftedCardEntry.UsedChoice.USED
    event.crafted_card_entry.save()

    # continue turn
    # continue turn
    from game.transactions.general import step_effect
    step_effect(event.crafted_card_entry.player)




@transaction.atomic
def emigre_skip_battle(event: EyrieEmigreEvent):
    """
    Skip the battle after moving. This results in failure (discarding the card).
    """
    emigre_failure(event)



@transaction.atomic
def emigre_failure(event: EyrieEmigreEvent):
    """
    Execute the failure action for eyrie emigre event
    resolve the event, and discard the crafted card
    """
    #mark event as resolved
    event.event.is_resolved = True
    event.event.save()

    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.crafted_cards import log_crafted_card_action
    log_crafted_card_action(
        event.event.game,
        event.crafted_card_entry.player,
        event.crafted_card_entry.card,
        "failure",
        parent=get_active_phase_log(event.event.game)
    )

    player = event.crafted_card_entry.player
    #discard the crafted card
    card = event.crafted_card_entry.card
    event.crafted_card_entry.delete()
    #event is now deleted due to cascade
    DiscardPileEntry.create_from_card(card)

    # continue turn
    # continue turn
    from game.transactions.general import step_effect
    step_effect(player)


