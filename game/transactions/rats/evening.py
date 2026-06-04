from django.db import transaction

from game.errors import IllegalActionError, UnavailableActionError
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.game_models import HandEntry, Player
from game.models.rats.tokens import Mob
from game.models.rats.turn import RatsEvening
from game.queries.general import (
    card_matches_clearing,
    get_cards_matching_clearing,
    get_player_hand_size,
    validate_player_has_card_in_hand,
)
from game.queries.rats.evening import (
    get_incite_eligible_clearings,
    get_oppressed_clearing_count,
    get_rowdy_draw_count,
)
from game.queries.rats.turn import validate_step
from game.serializers.logs.general import (
    get_current_phase_log,
    log_discard,
    log_draw,
)
from game.transactions.general import (
    discard_card_from_hand,
    draw_card_from_deck_to_hand,
    raise_score,
    place_piece_from_supply_into_clearing,
)
from game.transactions.rats.turn import next_step

from game.models.game_models import Clearing

# ---------------------------------------------------------------------------
# INCITE step
# ---------------------------------------------------------------------------


@transaction.atomic
def incite(player: Player, clearing: Clearing, card: CardsEP) -> None:
    """Spend *card* to place a Mob token in *clearing*.

    Requirements:
    - It is the INCITE step.
    - *card* matches the suit of *clearing* (or is wild).
    - *clearing* has at least one Hundreds warrior (Rats warrior or Warlord).
    - *clearing* has no existing Mob token.
    - At least one Mob token is in supply.

    Raises:
        UnavailableActionError: if not the INCITE step.
        IllegalActionError: if any of the other requirements are not met.
    """
    validate_step(player, RatsEvening.Steps.INCITE)

    hand_entry = validate_player_has_card_in_hand(player, card)

    if not card_matches_clearing(card, clearing):
        raise IllegalActionError("Card suit does not match clearing suit")

    # Clearing must contain at least one Hundreds warrior (incl. Warlord, a Warrior subtype)
    from game.models.game_models import Warrior

    if not Warrior.objects.filter(player=player, clearing=clearing).exists():
        raise IllegalActionError(
            "Clearing has no Hundreds warrior — cannot incite there"
        )

    # Clearing must not already have a Mob token belonging to this player
    if Mob.objects.filter(player=player, clearing=clearing).exists():
        raise IllegalActionError("Clearing already has a Mob token")

    # A Mob token must be available in supply
    mob = Mob.objects.filter(player=player, clearing__isnull=True).first()
    if mob is None:
        raise IllegalActionError("No Mob tokens in supply")

    card_model = hand_entry.card
    discard_card_from_hand(player, hand_entry)

    place_piece_from_supply_into_clearing(mob, clearing)

    phase_log = get_current_phase_log(player.game, player)
    from game.serializers.logs.rats import log_rats_incite

    log_rats_incite(
        player.game, player, clearing.clearing_number, card_model, parent=phase_log
    )

    # Jubilant mood: if incite happened in the Warlord's clearing and mobs remain
    # in supply, create a JubilantMobSpreadEvent for up to 4 bonus rolls.
    from game.models.rats.player import RatsPlayerState
    from game.models.events.rats import JubilantMobSpreadEvent

    state = RatsPlayerState.objects.get(player=player)
    if state.mood_type == RatsPlayerState.MoodType.JUBILANT:
        from game.queries.rats.pieces import get_warlord

        warlord = get_warlord(player)
        if warlord.clearing == clearing:
            mob_in_supply = Mob.objects.filter(
                player=player, clearing__isnull=True
            ).exists()
            if mob_in_supply:
                JubilantMobSpreadEvent.create(player)


@transaction.atomic
def end_incite_step(player: Player) -> None:
    """End the INCITE step and advance.

    Raises:
        UnavailableActionError: if not the INCITE step.
    """
    validate_step(player, RatsEvening.Steps.INCITE)
    next_step(player)


# ---------------------------------------------------------------------------
# OPPRESS step
# ---------------------------------------------------------------------------


@transaction.atomic
def resolve_oppress(player: Player) -> None:
    """Score victory points based on oppress count, then advance.

    Scoring table (clearings ruled by Rats with no enemy pieces):
      1–2  → 1 VP
      3–4  → 2 VP
      5    → 3 VP
      6+   → 4 VP

    Auto-called by step_effect when entering the OPPRESS step.

    Raises:
        UnavailableActionError: if not the OPPRESS step.
    """
    validate_step(player, RatsEvening.Steps.OPPRESS)

    count = get_oppressed_clearing_count(player)

    if count >= 6:
        vp = 4
    elif count == 5:
        vp = 3
    elif count >= 3:
        vp = 2
    elif count >= 1:
        vp = 1
    else:
        vp = 0

    if vp > 0:
        raise_score(player, vp)

    from game.serializers.logs.rats import log_rats_oppress

    phase_log = get_current_phase_log(player.game, player)
    log_rats_oppress(player.game, player, count, vp, parent=phase_log)

    next_step(player)


# ---------------------------------------------------------------------------
# DRAW step
# ---------------------------------------------------------------------------


@transaction.atomic
def draw_cards(player: Player) -> None:
    """Draw cards at the start of the Draw step.

    Base draw is 1 card. ROWDY mood may increase this to 2 or 3 (see
    get_rowdy_draw_count). Auto-called by step_effect on entering DRAW.

    Raises:
        UnavailableActionError: if not the DRAW step.
    """
    validate_step(player, RatsEvening.Steps.DRAW)

    count = get_rowdy_draw_count(player)
    drawn = []
    for _ in range(count):
        entry = draw_card_from_deck_to_hand(player)
        drawn.append(entry.card)

    phase_log = get_current_phase_log(player.game, player)
    log_draw(player.game, player, drawn, parent=phase_log)

    next_step(player)


# ---------------------------------------------------------------------------
# DISCARD step
# ---------------------------------------------------------------------------


@transaction.atomic
def discard_card(player: Player, card_entry: HandEntry) -> None:
    """Discard one card from hand during the DISCARD step.

    Advances automatically to the next step when the hand drops to 5 or fewer.

    Raises:
        UnavailableActionError: if not the DISCARD step, or hand is already ≤ 5.
        IllegalActionError: if *card_entry* does not belong to *player*.
    """
    validate_step(player, RatsEvening.Steps.DISCARD)

    if get_player_hand_size(player) <= 5:
        raise UnavailableActionError("Hand is already at or below 5 cards")

    if card_entry.player != player:
        raise IllegalActionError("Card does not belong to this player")

    card_model = card_entry.card
    discard_card_from_hand(player, card_entry)

    phase_log = get_current_phase_log(player.game, player)
    log_discard(player.game, player, card_model, parent=phase_log)

    if get_player_hand_size(player) <= 5:
        next_step(player)


@transaction.atomic
def end_discard(player: Player) -> None:
    """Explicitly end the DISCARD step when the hand is already at or below 5 cards.

    Raises:
        UnavailableActionError: if not the DISCARD step, or hand still exceeds 5 cards.
    """
    validate_step(player, RatsEvening.Steps.DISCARD)

    if get_player_hand_size(player) > 5:
        raise UnavailableActionError(
            "Cannot end discard: hand still has more than 5 cards"
        )

    next_step(player)
