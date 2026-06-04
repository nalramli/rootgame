from game.errors.system_errors import InternalGameError
from game.models.game_models import Clearing, Player
from game.queries.general import (
    card_matches_clearing,
    count_player_pieces_in_clearing,
    determine_clearing_rule,
    player_has_pieces_in_clearing,
)


def get_incite_eligible_clearings(player: Player) -> list[Clearing]:
    """Return clearings where the player may incite (place a Mob token).

    A clearing is eligible when:
    - At least one Mob token is in supply (global; if none, returns []).
    - The player has at least one Hundreds warrior (Warrior or Warlord) there.
    - The clearing does not already hold a Mob token for this player.

    Results are ordered by clearing_number.
    """
    from game.models.game_models import Warrior
    from game.models.rats.tokens import Mob

    if not Mob.objects.filter(player=player, clearing__isnull=True).exists():
        return []

    # IDs of clearings that already have a mob
    mob_clearing_ids = set(
        Mob.objects.filter(player=player, clearing__isnull=False).values_list(
            "clearing_id", flat=True
        )
    )
    # IDs of clearings that have at least one Hundreds warrior
    warrior_clearing_ids = set(
        Warrior.objects.filter(player=player, clearing__isnull=False).values_list(
            "clearing_id", flat=True
        )
    )

    eligible_ids = warrior_clearing_ids - mob_clearing_ids
    return list(
        Clearing.objects.filter(pk__in=eligible_ids, game=player.game).order_by(
            "clearing_number"
        )
    )


def get_oppressed_clearing_count(player: Player) -> int:
    """Return the number of clearings eligible for Oppress scoring.

    A clearing qualifies when:
    - The Rats player rules it (determined by standard rulership logic).
    - No other player has any pieces in the clearing.

    (If no enemies are present and Rats have any pieces, they trivially rule;
    the explicit rule-check also handles edge cases like Soup Kitchens.)
    """
    game = player.game
    other_players = list(game.players.exclude(pk=player.pk))
    count = 0
    for clearing in Clearing.objects.filter(game=game):
        if determine_clearing_rule(clearing) != player:
            continue
        if any(
            player_has_pieces_in_clearing(other, clearing) for other in other_players
        ):
            continue
        count += 1
    return count


def get_rowdy_draw_count(player: Player) -> int:
    """Return the number of cards to draw in Evening, factoring in Rowdy mood.

    Base: 1 card.
    Rowdy (coin): draw 1 more; if the Warlord's clearing has 3+ enemy pieces
    (any combination across all enemy factions), draw 2 more instead.
    """
    from game.models.rats.player import RatsPlayerState
    from game.queries.rats.pieces import get_warlord

    base = 1
    state = RatsPlayerState.objects.filter(player=player).first()
    assert state is not None
    if state.mood_type != RatsPlayerState.MoodType.ROWDY:
        return base

    warlord = get_warlord(player)
    if warlord.clearing is None:
        # Warlord not deployed — Rowdy bonus still applies at minimum (+1)
        return base + 1

    enemy_pieces = sum(
        count_player_pieces_in_clearing(other, warlord.clearing)
        for other in player.game.players.exclude(pk=player.pk)
    )
    return base + (2 if enemy_pieces >= 3 else 1)
