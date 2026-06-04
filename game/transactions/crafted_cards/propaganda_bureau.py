from game.queries.general import validate_player_has_crafted_card
from game.models import CraftedCardEntry
from game.transactions.general import discard_card_from_hand
from game.models import Warrior
from game.queries.cards.active_effects import can_use_card
from game.queries.general import card_matches_clearing
from game.queries.general import validate_player_has_card_in_hand
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.game_models import HandEntry, Player, Clearing, Faction


def use_propaganda_bureau(player: Player, card_to_spend : CardsEP, clearing : Clearing, target_faction : Faction):
    """
    Replaces warrior of target faction with a warrior of player's faction, discarding the matching card in hand and
    using up the propaganda bureau card for the turn
    """
    from game.errors import IllegalActionError, UnavailableActionError
    # validate that target faction is not player's faction
    if player.faction == target_faction:
        raise IllegalActionError("Target faction cannot be player's faction")

    card_in_hand = validate_player_has_card_in_hand(player, card_to_spend)

    if not card_matches_clearing(card_to_spend, clearing):
        raise IllegalActionError("Card suit does not match clearing suit")
    crafted_card = validate_player_has_crafted_card(player, CardsEP.PROPAGANDA_BUREAU)
    # validate that card is not already used
    if crafted_card.used == CraftedCardEntry.UsedChoice.USED:
        raise IllegalActionError("Propaganda Bureau cannot be used right now")
    # validate that effect is usable in current phase
    if not can_use_card(player, crafted_card):
        raise UnavailableActionError("Propaganda Bureau cannot be used right now")
    # remove enemy warrior. if doesn't exist, raise.
    # Order so regular warriors (is_warlord=0) come first; Warlord last (is_warlord=1).
    from game.models.rats.tokens import Warlord as RatsWarlord
    from django.db.models import Case, IntegerField, Value, When

    enemy_warrior = (
        Warrior.objects.filter(player__faction=target_faction, clearing=clearing)
        .annotate(
            is_warlord=Case(
                When(warlord__isnull=False, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("is_warlord")
        .first()
    )
    if enemy_warrior is None:
        raise IllegalActionError("No enemy warrior found in clearing")
    if RatsWarlord.objects.filter(pk=enemy_warrior.pk).exists():
        raise IllegalActionError("Cannot target the Warlord with Propaganda Bureau")
    enemy_warrior.clearing = None
    enemy_warrior.save()
    # add player's warrior to clearing, if able. if not, don't raise
    player_warrior = Warrior.objects.filter(player=player, clearing=None).first()
    if player_warrior is not None:
        player_warrior.clearing = clearing
        player_warrior.save()
    discard_card_from_hand(player, card_in_hand)
    # use up propaganda bureau card
    crafted_card.used = CraftedCardEntry.UsedChoice.USED
    crafted_card.save()

    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.crafted_cards import log_crafted_card_action
    log_crafted_card_action(
        player.game,
        player,
        crafted_card.card,
        "use",
        details={
            "clearing": clearing.clearing_number
        },
        parent=get_active_phase_log(player.game)
    )
    
    
