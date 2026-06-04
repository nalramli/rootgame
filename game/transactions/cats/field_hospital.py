from django.db import transaction

from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.cats.tokens import CatKeep
from game.models.events.event import Event, EventType
from game.models.events.cats import FieldHospitalEvent
from game.models.game_models import Clearing, Faction, Player, Suit, Warrior
from game.queries.cats.field_hospital import get_field_hospital_event
from game.queries.general import validate_player_has_card_in_hand
from game.transactions.general import discard_card_from_hand, place_piece_from_supply_into_clearing


@transaction.atomic
def create_field_hospital_event(clearing: Clearing, removed_player: Player, count: int):
    """creates a field hospital event when a cat gets warriors removed
    if keep is destroyed, skip creation
    """
    keep = CatKeep.objects.get(player=removed_player)
    if keep.destroyed:
        return
    event = Event.objects.create(game=clearing.game, type=EventType.FIELD_HOSPITAL)
    fh_event = FieldHospitalEvent.objects.create(
        event=event,
        player=removed_player,
        clearing=clearing,
        troops_to_save=count,
        suit=clearing.suit,
    )


@transaction.atomic
def cat_resolve_field_hospital(player: Player, card: CardsEP | None):
    """resolves the field hospital event, saving the troops and placing them at the keep
    If None is passed for card, resolves field hospital without saving troops
    If card is passed, discard it
    -- card must match the event suit
    """
    assert player.faction == Faction.CATS, "Not a cats player"
    field_hospital_event = get_field_hospital_event(player)
    from game.transactions.removal import return_warrior_to_supply

    to_save = field_hospital_event.troops_to_save
    keep = CatKeep.objects.get(player=player)
    warriors = list(Warrior.objects.filter(clearing=None, player=player)[:to_save])

    if card is None:
        for warrior in warriors:
            return_warrior_to_supply(warrior)
    else:
        hand_entry = validate_player_has_card_in_hand(player, card)
        if not (
            card.value.suit == field_hospital_event.suit or card.value.suit == Suit.WILD
        ):
            raise ValueError("Card is not the right suit")

        for warrior in warriors:
            place_piece_from_supply_into_clearing(warrior, keep.clearing)
        discard_card_from_hand(player, hand_entry)

        from game.serializers.logs.general import get_active_phase_log
        from game.serializers.logs.cats import log_cats_field_hospitals

        log_cats_field_hospitals(
            player.game,
            player,
            (
                field_hospital_event.clearing.clearing_number
                if field_hospital_event.clearing
                else 0
            ),
            to_save,
            parent=get_active_phase_log(player.game),
        )

    field_hospital_event.event.is_resolved = True
    field_hospital_event.event.save()

    # Resume the current player's turn machine. If field hospital fired during
    # another faction's turn (e.g. Rats advance), step_effect was blocked by the
    # unresolved FH event. Now that it is resolved, we must call step_effect on
    # the current turn player so the phase machine can continue.
    from game.queries.general import get_current_player
    from game.transactions.general import step_effect
    current_player = get_current_player(field_hospital_event.event.game)
    step_effect(current_player)
