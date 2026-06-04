import random

from django.db import transaction

from game.errors import UnavailableActionError, IllegalActionError
from game.models.enums import Suit
from game.models.game_models import (
    Building,
    Clearing,
    Player,
    Ruin,
    Token,
    Warrior,
)
from game.models.rats.buildings import Stronghold
from game.models.rats.player import RatsPlayerState
from game.models.rats.tokens import Mob
from game.models.rats.turn import RatsBirdsong
from game.queries.rats.birdsong import (
    get_mob_spread_targets,
    get_prowess_value,
    get_valid_moods,
)
from game.queries.rats.pieces import get_warlord
from game.queries.rats.recruit import (
    get_unused_recruit_strongholds,
    get_warrior_supply_count,
    recruit_needs_choice,
)
from game.queries.rats.turn import validate_phase, validate_step
from game.transactions.general import place_piece_from_supply_into_clearing
from game.transactions.rats.hoard import add_item_to_hoard
from game.transactions.rats.turn import next_step
from game.transactions.removal import (
    cleanup_removal_event,
    player_removes_building,
    player_removes_token,
    start_removal_event,
)


@transaction.atomic
def raze(player: Player) -> None:
    """RAZE step: for each clearing with a Mob token, remove enemy pieces
    and loot any ruin present.  Advances the step when done.
    """
    validate_step(player, RatsBirdsong.Steps.RAZE)

    mob_clearings = set(
        Mob.objects.filter(player=player, clearing__isnull=False).select_related(
            "clearing"
        )
    )

    start_removal_event(player.game)
    try:
        for mob in mob_clearings:
            clearing = mob.clearing

            # Remove all enemy buildings in this clearing
            for building in Building.objects.filter(
                building_slot__clearing=clearing
            ).exclude(player=player):
                player_removes_building(player.game, building, player)

            # Remove all enemy tokens in this clearing (excludes our own Mob)
            for token in Token.objects.filter(clearing=clearing).exclude(player=player):
                player_removes_token(player.game, token, player)

            # Loot any ruin present in this clearing (Ruin is not a Building subclass)
            for ruin in Ruin.objects.filter(
                building_slot__clearing=clearing
            ).select_related("item"):
                item = ruin.item
                ruin.building_slot = None
                ruin.save()
                add_item_to_hoard(player, item)
    finally:
        cleanup_removal_event(player.game)

    from game.serializers.logs.general import get_current_phase_log
    from game.serializers.logs.rats import log_rats_raze

    phase_log = get_current_phase_log(player.game, player)
    log_rats_raze(player.game, player, len(mob_clearings), parent=phase_log)

    next_step(player)


@transaction.atomic
def roll_mob_die_and_spread(player: Player) -> None:
    """SPREAD_MOB step: roll the mob die and place a mob token if possible.

    - No mobs in supply → skip.
    - No valid targets → skip.
    - Exactly one target → place automatically.
    - Multiple targets → store the rolled suit and wait for player choice.
    """
    validate_step(player, RatsBirdsong.Steps.SPREAD_MOB)

    # Check supply
    if Mob.objects.filter(player=player, clearing__isnull=True).count() == 0:
        next_step(player)
        return

    # Roll the die (Fox / Rabbit / Mouse only — no Bird face)
    rolled_suit = random.choice([Suit.RED, Suit.YELLOW, Suit.ORANGE])

    targets = get_mob_spread_targets(player, rolled_suit)

    if len(targets) == 0:
        next_step(player)
        return

    if len(targets) == 1:
        clearing = targets.pop()
        _place_mob_in_clearing(player, clearing)
        from game.serializers.logs.general import get_current_phase_log
        from game.serializers.logs.rats import log_rats_mob_spread

        phase_log = get_current_phase_log(player.game, player)
        log_rats_mob_spread(
            player.game, player, clearing.clearing_number, rolled_suit, parent=phase_log
        )
        next_step(player)
        return

    # Multiple targets: record the suit and wait for the player to choose
    birdsong = validate_phase(player, RatsBirdsong)
    assert isinstance(birdsong, RatsBirdsong)
    birdsong.mob_die_suit = rolled_suit
    birdsong.save()
    # Do NOT call next_step — player must now call choose_mob_clearing


def _place_mob_in_clearing(player: Player, clearing: Clearing) -> None:
    """Take one Mob from supply and place it in *clearing*."""
    mob = Mob.objects.filter(player=player, clearing__isnull=True).first()
    if mob is None:
        raise UnavailableActionError("No Mob tokens remaining in supply")
    place_piece_from_supply_into_clearing(mob, clearing)


@transaction.atomic
def choose_mob_clearing(player: Player, clearing: Clearing) -> None:
    """Player selects which clearing receives the mob when multiple targets exist."""
    validate_step(player, RatsBirdsong.Steps.SPREAD_MOB)
    birdsong = validate_phase(player, RatsBirdsong)
    assert isinstance(birdsong, RatsBirdsong)

    if birdsong.mob_die_suit is None:
        raise UnavailableActionError("No mob die roll in progress")

    if clearing.suit != birdsong.mob_die_suit:
        raise IllegalActionError(
            f"Clearing suit '{clearing.suit}' does not match rolled suit "
            f"'{birdsong.mob_die_suit}'"
        )

    valid_targets = get_mob_spread_targets(player, Suit(birdsong.mob_die_suit))
    if clearing not in valid_targets:
        raise IllegalActionError("Chosen clearing is not a valid mob spread target")

    suit_rolled = birdsong.mob_die_suit  # capture before clearing
    _place_mob_in_clearing(player, clearing)
    birdsong.mob_die_suit = None
    birdsong.save()

    from game.serializers.logs.general import get_current_phase_log
    from game.serializers.logs.rats import log_rats_mob_spread

    phase_log = get_current_phase_log(player.game, player)
    log_rats_mob_spread(
        player.game, player, clearing.clearing_number, suit_rolled, parent=phase_log
    )

    next_step(player)


def _place_warriors_excluding_warlord(
    player: Player, clearing: Clearing, count: int
) -> None:
    """Place *count* regular (non-Warlord) warriors from supply into *clearing*.

    Uses place_piece_from_supply_into_clearing for proper blocking checks and
    explicitly excludes the Warlord row so it can never be accidentally placed
    as a regular warrior.
    """
    warriors = list(
        Warrior.objects.filter(
            player=player, clearing__isnull=True, warlord__isnull=True
        )[:count]
    )
    for warrior in warriors:
        place_piece_from_supply_into_clearing(warrior, clearing)


def _auto_place_strongholds(player: Player) -> None:
    """Place warriors at unused strongholds automatically (no choice required).

    Iterates unused strongholds and places one warrior per stronghold until
    supply is exhausted, marking each stronghold as recruit_used.
    """
    for stronghold in get_unused_recruit_strongholds(player):
        if get_warrior_supply_count(player) == 0:
            break
        _place_warriors_excluding_warlord(player, stronghold.building_slot.clearing, 1)
        stronghold.recruit_used = True
        stronghold.save()


@transaction.atomic
def recruit(player: Player) -> None:
    """RECRUIT step: place warriors at the Warlord's clearing, then at Strongholds.

    Phase 1 — Warlord: place min(prowess_value, supply) warriors at the Warlord's
    clearing (if on map). Never raises for insufficient supply — places as many as
    are available.

    Phase 2 — Strongholds: if no player choice is required (enough supply, or all
    unused strongholds share one clearing), auto-place and advance. Otherwise pause
    for the player to call recruit_stronghold() one clearing at a time.
    """
    validate_step(player, RatsBirdsong.Steps.RECRUIT)

    prowess_value = get_prowess_value(player)

    # Phase 1: Warlord clearing
    warlord = get_warlord(player)
    warlord_warriors = 0
    if warlord.clearing is not None:
        supply = get_warrior_supply_count(player)
        to_place = min(prowess_value, supply)
        if to_place > 0:
            _place_warriors_excluding_warlord(player, warlord.clearing, to_place)
            warlord_warriors = to_place

    # Phase 2: Strongholds
    if recruit_needs_choice(player):
        if warlord_warriors > 0:
            from game.serializers.logs.general import get_current_phase_log
            from game.serializers.logs.rats import log_rats_recruit

            phase_log = get_current_phase_log(player.game, player)
            log_rats_recruit(player.game, player, warlord_warriors, parent=phase_log)
        return  # Pause — player must call recruit_stronghold()

    supply_before_strongholds = get_warrior_supply_count(player)
    _auto_place_strongholds(player)
    stronghold_warriors = supply_before_strongholds - get_warrior_supply_count(player)
    total_warriors = warlord_warriors + stronghold_warriors

    from game.serializers.logs.general import get_current_phase_log
    from game.serializers.logs.rats import log_rats_recruit

    phase_log = get_current_phase_log(player.game, player)
    log_rats_recruit(player.game, player, total_warriors, parent=phase_log)

    next_step(player)


@transaction.atomic
def recruit_stronghold(player: Player, clearing: Clearing) -> None:
    """Player places one warrior at a chosen stronghold clearing during RECRUIT.

    Called when multiple clearings have unused strongholds but not enough warriors
    in supply to fill all of them. After each placement the situation is
    re-evaluated: if it can now be resolved automatically it will be, and the step
    will advance; otherwise the player must call this again.

    Raises:
        IllegalActionError: if the chosen clearing has no unused stronghold.
        UnavailableActionError: if it is not the RECRUIT step or supply is empty.
    """
    validate_step(player, RatsBirdsong.Steps.RECRUIT)

    # Validate there is an unused stronghold in the chosen clearing
    stronghold = (
        get_unused_recruit_strongholds(player)
        .filter(building_slot__clearing=clearing)
        .first()
    )
    if stronghold is None:
        raise IllegalActionError("No unused stronghold in the chosen clearing")

    if get_warrior_supply_count(player) == 0:
        raise UnavailableActionError("No warriors left in supply to place")

    # Place one regular warrior and mark the stronghold used
    _place_warriors_excluding_warlord(player, clearing, 1)
    stronghold.recruit_used = True
    stronghold.save()

    # Re-evaluate: auto-finish if possible, otherwise wait for next choice
    if recruit_needs_choice(player):
        from game.serializers.logs.general import get_current_phase_log
        from game.serializers.logs.rats import log_rats_recruit

        phase_log = get_current_phase_log(player.game, player)
        log_rats_recruit(player.game, player, 1, parent=phase_log)
        return

    supply_before = get_warrior_supply_count(player)
    _auto_place_strongholds(player)
    auto_placed = supply_before - get_warrior_supply_count(player)

    from game.serializers.logs.general import get_current_phase_log
    from game.serializers.logs.rats import log_rats_recruit

    phase_log = get_current_phase_log(player.game, player)
    log_rats_recruit(player.game, player, 1 + auto_placed, parent=phase_log)

    next_step(player)


@transaction.atomic
def anoint(player: Player, clearing: Clearing) -> None:
    """Player places the Warlord onto the map (ANOINT step).

    If warriors are present anywhere on the board, one must be in *clearing*
    and is consumed to anoint the Warlord there.  If no warriors are on the
    board, the Warlord may be placed in any clearing.
    """
    validate_step(player, RatsBirdsong.Steps.ANOINT)

    warlord = get_warlord(player)
    if warlord.clearing is not None:
        raise UnavailableActionError(
            "Warlord is already on the map — Anoint should have been skipped"
        )

    warriors_on_board = Warrior.objects.filter(
        player=player, clearing__isnull=False, warlord__isnull=True
    ).exists()

    consumed_warrior = False
    if warriors_on_board:
        # A warrior must be present in the chosen clearing to be converted
        warrior_in_clearing = Warrior.objects.filter(
            player=player, clearing=clearing, warlord__isnull=True
        ).first()
        if warrior_in_clearing is None:
            raise IllegalActionError(
                "No warrior in the chosen clearing to anoint as Warlord"
            )
        warrior_in_clearing.delete()
        consumed_warrior = True

    warlord.clearing = clearing
    warlord.save()

    from game.serializers.logs.general import get_current_phase_log
    from game.serializers.logs.rats import log_rats_anoint

    phase_log = get_current_phase_log(player.game, player)
    log_rats_anoint(
        player.game,
        player,
        clearing.clearing_number,
        consumed_warrior,
        parent=phase_log,
    )

    next_step(player)


@transaction.atomic
def choose_mood(player: Player, mood_type: RatsPlayerState.MoodType) -> None:
    """Player selects a new mood (CHOOSE_MOOD step)."""
    validate_step(player, RatsBirdsong.Steps.CHOOSE_MOOD)

    valid_moods = get_valid_moods(player)
    if mood_type not in valid_moods:
        raise IllegalActionError(
            f"Mood '{mood_type}' is not available. Valid moods: {valid_moods}"
        )

    state = RatsPlayerState.objects.get(player=player)
    state.mood_type = mood_type
    state.save()

    from game.serializers.logs.general import get_current_phase_log
    from game.serializers.logs.rats import log_rats_choose_mood

    phase_log = get_current_phase_log(player.game, player)
    log_rats_choose_mood(player.game, player, mood_type.value, parent=phase_log)

    next_step(player)
