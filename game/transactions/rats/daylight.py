from typing import Literal

from django.db import transaction

from game.errors import IllegalActionError, UnavailableActionError
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.enums import Faction
from game.models.game_models import Clearing, Player
from game.models.rats.buildings import Stronghold
from game.models.rats.turn import RatsAdvance, RatsDaylight
from game.queries.general import (
    available_building_slot,
    card_matches_clearing,
    determine_clearing_rule,
    validate_legal_move,
    validate_player_has_card_in_hand,
)
from game.queries.rats.birdsong import get_command_value, get_prowess_value
from game.queries.rats.daylight import validate_crafting_pieces_satisfy_requirements
from game.queries.rats.pieces import get_warlord
from game.queries.rats.turn import get_phase, validate_step
from game.serializers.logs.general import get_current_phase_log, log_craft, log_move
from game.serializers.logs.rats import log_rats_build
from game.transactions.battle import log_battle_start, start_battle
from game.transactions.general import (
    craft_card as general_craft_card,
    discard_card_from_hand,
    move_warriors,
    place_building_from_supply_into_slot,
)
from game.transactions.rats.turn import next_step


@transaction.atomic
def craft_card(
    player: Player,
    card: CardsEP,
    strongholds: list[Stronghold],
    add_to_hoard: bool = False,
) -> None:
    """Craft a card using the given Strongholds as crafting pieces.

    Each Stronghold must be deployed (have a building_slot) and not yet used
    this turn (crafted_with=False). The combined clearing suits of the Strongholds
    must satisfy the card's crafting cost.

    For item cards, the player may choose to add the item to the hoard (score no VP)
    or remove it permanently to score the listed VP (Contempt for Trade rule).
    Pass ``add_to_hoard=True`` to route the item onto the hoard instead of scoring.

    Args:
        player: The Rats player performing the craft action.
        card: The card enum value to craft from hand.
        strongholds: The Strongholds whose clearings satisfy the card's cost.
        add_to_hoard: If True and the card yields an item, route it to the hoard
            (Command or Prowess track) and score 0 VP.  If False, remove the item
            permanently and score the listed VP.  Has no effect for non-item cards.

    Raises:
        UnavailableActionError: if it is not the CRAFT step.
        IllegalActionError: if the card is not in hand, any Stronghold is in supply,
            or the Strongholds do not satisfy the card's cost.
    """
    validate_step(player, RatsDaylight.Steps.CRAFT)

    card_in_hand = validate_player_has_card_in_hand(player, card)

    for sh in strongholds:
        if sh.building_slot is None:
            raise IllegalActionError(
                "Stronghold is in supply and cannot be used for crafting"
            )

    validate_crafting_pieces_satisfy_requirements(player, card, strongholds)

    card_model = card_in_hand.card
    general_craft_card(card_in_hand, strongholds, adding_to_hoard=add_to_hoard)

    phase_log = get_current_phase_log(player.game, player)
    log_craft(player.game, player, card_model, parent=phase_log)


@transaction.atomic
def end_crafting(player: Player) -> None:
    """End the CRAFT step and advance to the next Daylight step.

    Raises:
        UnavailableActionError: if it is not the CRAFT step.
    """
    validate_step(player, RatsDaylight.Steps.CRAFT)
    next_step(player)


# ---------------------------------------------------------------------------
# COMMAND step
# ---------------------------------------------------------------------------


def _validate_command_available(player: Player) -> RatsDaylight:
    """Validate the player is at the COMMAND step and has commands remaining.

    Returns the RatsDaylight instance for the caller to increment commands_used
    after the action succeeds.

    Raises:
        UnavailableActionError: if not the COMMAND step or all commands are spent.
    """
    validate_step(player, RatsDaylight.Steps.COMMAND)
    daylight = get_phase(player)
    assert isinstance(daylight, RatsDaylight)
    if daylight.commands_used >= get_command_value(player):
        raise UnavailableActionError("No commands remaining this turn")
    return daylight


@transaction.atomic
def use_command(
    player: Player,
    command_type: Literal["move", "battle", "build"],
    *args,
    **kwargs,
) -> None:
    """Dispatch a command action and increment commands_used.

    Validates timing and command budget, then delegates to the appropriate
    command function (_command_move, _command_battle, or _command_build),
    passing through all positional and keyword args.

    Args:
        player: The Rats player acting.
        command_type: One of "move", "battle", or "build".
        *args / **kwargs: Forwarded to the underlying command function.

    Raises:
        UnavailableActionError: if not the COMMAND step or budget is exhausted.
        IllegalActionError: if the specific command's validation fails.
    """
    daylight = _validate_command_available(player)

    match command_type:
        case "move":
            _command_move(player, *args, **kwargs)
        case "battle":
            _command_battle(player, *args, **kwargs)
        case "build":
            _command_build(player, *args, **kwargs)
        case _:
            raise IllegalActionError(f"Unknown command type: {command_type!r}")

    daylight.commands_used += 1
    daylight.save()

    _check_commands_finished(player, daylight)


def _check_commands_finished(player: Player, daylight: RatsDaylight) -> None:
    """Advance past COMMAND if the player has used all available commands.

    NOTE: command_value may increase mid-step in the future (e.g. looting a
    Command-track item during battle).  commands_used should never exceed
    command_value — that would mean the budget check in _validate_command_available
    failed to fire, which is a logic error.
    """
    from game.errors import InternalGameError

    command_value = get_command_value(player)
    if daylight.commands_used > command_value:
        raise InternalGameError(
            f"commands_used ({daylight.commands_used}) exceeds command_value "
            f"({command_value}) — budget check should have prevented this"
        )
    if daylight.commands_used == command_value:
        next_step(player)


@transaction.atomic
def end_command(player: Player) -> None:
    """Voluntarily end the COMMAND step even if commands remain.

    Raises:
        UnavailableActionError: if it is not the COMMAND step.
    """
    validate_step(player, RatsDaylight.Steps.COMMAND)
    next_step(player)


@transaction.atomic
def _command_move(
    player: Player,
    origin: Clearing,
    destination: Clearing,
    count: int,
    move_warlord: bool = False,
) -> None:
    """Move *count* pieces from *origin* to *destination*.

    When *move_warlord* is True the Warlord counts as one of the *count*
    pieces and will be moved alongside regular warriors.

    Raises:
        IllegalActionError: if the move is illegal (adjacency, rulership, count).
    """
    move_warriors(player, origin, destination, count, move_warlord=move_warlord)
    phase_log = get_current_phase_log(player.game, player)
    log_move(
        player.game,
        player,
        origin.clearing_number,
        destination.clearing_number,
        count,
        parent=phase_log,
    )


@transaction.atomic
def _command_battle(
    player: Player,
    defender: Faction,
    clearing: Clearing,
    looting: bool = False,
) -> None:
    """Initiate a battle as attacker against *defender* in *clearing*.

    Delegates to the general start_battle transaction.  Logs the battle start.
    If *looting* is True, validates eligibility and declares looting for this battle.

    Raises:
        IllegalActionError: if no valid targets exist, or looting is declared but
            the defender has no items in their Crafted Items box.
    """
    battle_obj = start_battle(
        player.game,
        attacker=Faction(player.faction),
        defender=Faction(defender),
        clearing=clearing,
    )
    if looting:
        from game.models.game_models import Player as PlayerModel
        from game.transactions.rats.looting import declare_looting

        defender_player = PlayerModel.objects.get(game=player.game, faction=defender)
        declare_looting(player, defender_player)
    phase_log = get_current_phase_log(player.game, player)
    log_battle_start(battle_obj, player, parent=phase_log)


@transaction.atomic
def _command_build(
    player: Player,
    card: CardsEP,
    clearing: Clearing,
) -> None:
    """Spend *card* to place a Stronghold in *clearing*.

    Requirements:
    - Player has *card* in hand (card is discarded).
    - The clearing's suit matches the card's suit.
    - The Rats rule *clearing* (determine_clearing_rule).
    - A Stronghold is available in supply.
    - An empty building slot exists in *clearing*.

    Raises:
        IllegalActionError: if any requirement is not met.
    """
    hand_entry = validate_player_has_card_in_hand(player, card)

    if not card_matches_clearing(card, clearing):
        raise IllegalActionError("Clearing suit does not match card suit")

    if determine_clearing_rule(clearing) != player:
        raise IllegalActionError("Rats do not rule this clearing")

    stronghold = Stronghold.objects.filter(
        player=player, building_slot__isnull=True
    ).first()
    if stronghold is None:
        raise IllegalActionError("No Strongholds available in supply")

    slot = available_building_slot(clearing)
    if slot is None:
        raise IllegalActionError("No available building slots in this clearing")

    card_model = hand_entry.card
    discard_card_from_hand(player, hand_entry)

    place_building_from_supply_into_slot(stronghold, slot)

    phase_log = get_current_phase_log(player.game, player)
    log_rats_build(
        player.game,
        player,
        clearing.clearing_number,
        card_model,
        parent=phase_log,
    )


# ---------------------------------------------------------------------------
# ADVANCE step
# ---------------------------------------------------------------------------


def _complete_advance_cycle(player: Player, daylight: RatsDaylight) -> None:
    """Reset the advance tracker, increment prowess_used, and check if done."""
    daylight.advance.reset()
    daylight.prowess_used += 1
    daylight.save()
    _check_advance_finished(player, daylight)


def _check_advance_finished(player: Player, daylight: RatsDaylight) -> None:
    """Advance past ADVANCE step once prowess_used reaches prowess_value.

    prowess_used > prowess_value is a logic error — the budget check in
    advance_move / advance_battle should have prevented it.
    """
    from game.errors import InternalGameError

    prowess_value = get_prowess_value(player)
    if daylight.prowess_used > prowess_value:
        raise InternalGameError(
            f"prowess_used ({daylight.prowess_used}) exceeds prowess_value "
            f"({prowess_value}) — budget check should have prevented this"
        )
    if daylight.prowess_used == prowess_value:
        next_step(player)


def _check_relentless_or_complete(
    player: Player, daylight: RatsDaylight, advance: RatsAdvance
) -> None:
    """After the battle sub-step, decide whether to award the Relentless bonus
    or complete the advance cycle.

    Relentless bonus is awarded only when:
    - Current mood is RELENTLESS, AND
    - Both move_used and battle_used are True (both were taken, not skipped).
    """
    from game.models.rats.player import RatsPlayerState

    state = RatsPlayerState.objects.get(player=player)
    if (
        state.mood_type == RatsPlayerState.MoodType.RELENTLESS
        and advance.move_used
        and advance.battle_used
    ):
        advance.current_step = RatsAdvance.AdvanceStep.RELENTLESS_BONUS
        advance.save()
    else:
        _complete_advance_cycle(player, daylight)


@transaction.atomic
def advance_move(player: Player, destination: Clearing, count: int) -> None:
    """Move the Warlord (and optionally *count* warriors) to *destination*.

    Origin is always the Warlord's current clearing.  count=0 is allowed
    (Warlord moves alone).

    Valid during the MOVE or RELENTLESS_BONUS sub-step of an advance cycle.

    Raises:
        UnavailableActionError: if not the ADVANCE step or advance is not in
            the MOVE or RELENTLESS_BONUS sub-step, or prowess budget exhausted.
        IllegalActionError: if the move is illegal (adjacency, warrior count).
    """
    validate_step(player, RatsDaylight.Steps.ADVANCE)

    daylight = get_phase(player)
    assert isinstance(daylight, RatsDaylight)
    advance = daylight.advance

    if advance.current_step not in (
        RatsAdvance.AdvanceStep.MOVE,
        RatsAdvance.AdvanceStep.RELENTLESS_BONUS,
    ):
        raise UnavailableActionError("Advance move is not available at this sub-step")

    if daylight.prowess_used >= get_prowess_value(player):
        raise UnavailableActionError("No prowess remaining for advance")

    warlord = get_warlord(player)
    if warlord.clearing is None:
        raise IllegalActionError("Warlord is not deployed on the map")

    origin = warlord.clearing

    # Move Warlord + count warriors in one call (Warlord always moves during Advance)
    move_warriors(player, origin, destination, count + 1, move_warlord=True)

    advance.move_used = True

    if advance.current_step == RatsAdvance.AdvanceStep.RELENTLESS_BONUS:
        advance.save()
        _complete_advance_cycle(player, daylight)
    else:
        advance.current_step = RatsAdvance.AdvanceStep.BATTLE
        advance.save()

    phase_log = get_current_phase_log(player.game, player)
    log_move(
        player.game,
        player,
        origin.clearing_number,
        destination.clearing_number,
        count + 1,
        parent=phase_log,
    )


@transaction.atomic
def advance_move_skip(player: Player) -> None:
    """Skip the move sub-step of an advance cycle.

    Valid only during the MOVE sub-step (not RELENTLESS_BONUS, where the
    player must explicitly choose move or battle before skipping via
    advance_relentless_skip).

    Raises:
        UnavailableActionError: if not the ADVANCE step or not in MOVE sub-step.
    """
    validate_step(player, RatsDaylight.Steps.ADVANCE)

    daylight = get_phase(player)
    assert isinstance(daylight, RatsDaylight)
    advance = daylight.advance

    if advance.current_step != RatsAdvance.AdvanceStep.MOVE:
        raise UnavailableActionError(
            "Advance move skip is only available during the MOVE sub-step"
        )

    if daylight.prowess_used >= get_prowess_value(player):
        raise UnavailableActionError("No prowess remaining for advance")

    advance.current_step = RatsAdvance.AdvanceStep.BATTLE
    advance.save()


@transaction.atomic
def advance_battle(player: Player, defender: Faction, looting: bool = False) -> None:
    """Battle in the Warlord's current clearing against *defender*.

    Valid during the BATTLE or RELENTLESS_BONUS sub-step of an advance cycle.
    If *looting* is True, validates eligibility and declares looting for this battle.

    Raises:
        UnavailableActionError: if not the ADVANCE step or advance is not in
            the BATTLE or RELENTLESS_BONUS sub-step, or prowess budget exhausted.
        IllegalActionError: if the battle is illegal (no warriors, etc.), or looting
            is declared but the defender has no items in their Crafted Items box.
    """
    validate_step(player, RatsDaylight.Steps.ADVANCE)

    daylight = get_phase(player)
    assert isinstance(daylight, RatsDaylight)
    advance = daylight.advance

    if advance.current_step not in (
        RatsAdvance.AdvanceStep.BATTLE,
        RatsAdvance.AdvanceStep.RELENTLESS_BONUS,
    ):
        raise UnavailableActionError("Advance battle is not available at this sub-step")

    if daylight.prowess_used >= get_prowess_value(player):
        raise UnavailableActionError("No prowess remaining for advance")

    warlord = get_warlord(player)
    if warlord.clearing is None:
        raise IllegalActionError("Warlord is not deployed on the map")

    warlord_clearing = warlord.clearing

    battle_obj = start_battle(
        player.game,
        attacker=Faction(player.faction),
        defender=Faction(defender),
        clearing=warlord_clearing,
    )
    if looting:
        from game.models.game_models import Player as PlayerModel
        from game.transactions.rats.looting import declare_looting

        defender_player = PlayerModel.objects.get(game=player.game, faction=defender)
        declare_looting(player, defender_player)
    phase_log = get_current_phase_log(player.game, player)
    log_battle_start(battle_obj, player, parent=phase_log)

    advance.battle_used = True

    if advance.current_step == RatsAdvance.AdvanceStep.RELENTLESS_BONUS:
        advance.save()
        _complete_advance_cycle(player, daylight)
    else:
        advance.save()
        _check_relentless_or_complete(player, daylight, advance)


@transaction.atomic
def advance_battle_skip(player: Player) -> None:
    """Skip the battle sub-step of an advance cycle.

    Valid only during the BATTLE sub-step.

    Raises:
        UnavailableActionError: if not the ADVANCE step or not in BATTLE sub-step.
    """
    validate_step(player, RatsDaylight.Steps.ADVANCE)

    daylight = get_phase(player)
    assert isinstance(daylight, RatsDaylight)
    advance = daylight.advance

    if advance.current_step != RatsAdvance.AdvanceStep.BATTLE:
        raise UnavailableActionError(
            "Advance battle skip is only available during the BATTLE sub-step"
        )

    if daylight.prowess_used >= get_prowess_value(player):
        raise UnavailableActionError("No prowess remaining for advance")

    _complete_advance_cycle(player, daylight)


@transaction.atomic
def advance_relentless_skip(player: Player) -> None:
    """Skip the Relentless bonus sub-step, completing the advance cycle.

    Valid only during the RELENTLESS_BONUS sub-step.

    Raises:
        UnavailableActionError: if not in the RELENTLESS_BONUS sub-step.
    """
    daylight = get_phase(player)
    assert isinstance(daylight, RatsDaylight)
    advance = daylight.advance

    if advance.current_step != RatsAdvance.AdvanceStep.RELENTLESS_BONUS:
        raise UnavailableActionError(
            "Advance relentless skip is only available during the RELENTLESS_BONUS sub-step"
        )

    _complete_advance_cycle(player, daylight)


@transaction.atomic
def end_advance(player: Player) -> None:
    """Voluntarily end the ADVANCE step even if prowess remains.

    Can be called at any sub-step of any advance cycle; the current cycle
    state is left as-is (the turn moves on regardless).

    Raises:
        UnavailableActionError: if it is not the ADVANCE step.
    """
    validate_step(player, RatsDaylight.Steps.ADVANCE)
    next_step(player)
