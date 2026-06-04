from django.db import transaction
from game.models.game_models import CraftedCardEntry, CraftedItemEntry, Faction
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.queries.cards.active_effects import can_use_card
from game.transactions.general import move_warriors
from game.transactions.battle import start_battle

@transaction.atomic
def use_league_of_adventurers(
    crafted_card_entry: CraftedCardEntry, 
    crafted_item_entry: CraftedItemEntry, 
    move_data: dict | None = None, 
    battle_data: dict | None = None
):
    """
    Implementation of the League of Adventurers crafted card effect.
    Once in Daylight, may exhaust an item in your Crafted Item Box to take a move or initiate a battle.
    """
    player = crafted_card_entry.player

    # 1. Validate card is League of Adventurers
    if crafted_card_entry.card.card_type != CardsEP.LEAGUE_OF_ADVENTURERS.name:
        raise ValueError("Card is not League of Adventurous Mice.")
        
    # 2. Check if card can be used now (Daylight)
    from game.queries.general import is_phase
    from game.errors import UnavailableActionError
    if not is_phase(player, "Daylight"):
        raise UnavailableActionError("League of Adventurers cannot be used right now. It must be in your Daylight.")
    
    if crafted_card_entry.used == CraftedCardEntry.UsedChoice.USED:
        raise ValueError("This card has already been used this turn.")

    # 3. Validate item belongs to the same player and is not exhausted
    if crafted_item_entry.player != player:
        raise ValueError("Player does not own this crafted item.")
    if crafted_item_entry.exhausted:
        from game.errors import IllegalActionError
        raise IllegalActionError("This item is already exhausted.")
        
    # 4. Validate move/battle data
    if move_data and battle_data:
        raise ValueError("Cannot perform both a move and a battle.")
    if not move_data and not battle_data:
        raise ValueError("Must provide either move data or battle data.")

    # 5. Execute action
    if move_data:
        # move_data: {origin_clearing, target_clearing, number, move_warlord}
        origin = move_data["origin_clearing"]
        target = move_data["target_clearing"]
        number = move_data["number"]
        move_warlord = bool(move_data.get("move_warlord", False))
        move_warriors(player, origin, target, number, move_warlord=move_warlord)
    else:
        # battle_data: {clearing, opponent_faction}
        clearing = battle_data["clearing"]
        opponent_faction_code = battle_data["opponent_faction"]
        if isinstance(opponent_faction_code, str):
            opponent_faction = Faction(opponent_faction_code)
        else:
            opponent_faction = opponent_faction_code
            
        start_battle(player.game, Faction(player.faction), opponent_faction, clearing)

    # 6. Exhaust the item
    crafted_item_entry.exhausted = True
    crafted_item_entry.save()
    
    # 7. Mark card as used
    crafted_card_entry.used = CraftedCardEntry.UsedChoice.USED
    crafted_card_entry.save()

    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.crafted_cards import log_crafted_card_action
    
    action_type = "move" if move_data else "battle"
    details = {}
    if move_data:
        details = {
            "count": move_data["number"],
            "origin": move_data["origin_clearing"].clearing_number,
            "destination": move_data["target_clearing"].clearing_number
        }
    else:
        details = {
            "defender_faction": battle_data["opponent_faction"],
            "clearing": battle_data["clearing"].clearing_number
        }

    log_crafted_card_action(
        player.game,
        player,
        crafted_card_entry.card,
        action_type,
        details=details,
        parent=get_active_phase_log(player.game)
    )
