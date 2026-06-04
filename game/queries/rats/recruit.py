from django.db.models import QuerySet

from game.models.game_models import Clearing, Player, Warrior
from game.models.rats.buildings import Stronghold


def get_warrior_supply_count(player: Player) -> int:
    """Return the number of regular (non-Warlord) warriors in supply."""
    return Warrior.objects.filter(
        player=player,
        clearing__isnull=True,
        warlord__isnull=True,
    ).count()


def get_unused_recruit_strongholds(player: Player) -> QuerySet[Stronghold]:
    """Return deployed strongholds not yet used in this RECRUIT step."""
    return Stronghold.objects.filter(
        player=player,
        building_slot__isnull=False,
        recruit_used=False,
    ).select_related("building_slot__clearing")


def get_recruit_clearings(player: Player) -> list[Clearing]:
    """Return the distinct clearings of unused recruit strongholds.

    Used by views to show the player which clearings they may choose from.
    """
    clearing_ids = (
        get_unused_recruit_strongholds(player)
        .values_list("building_slot__clearing_id", flat=True)
        .distinct()
    )
    return list(Clearing.objects.filter(id__in=clearing_ids))


def recruit_needs_choice(player: Player) -> bool:
    """Return True when the player must choose which clearing gets the next warrior.

    A choice is required when:
    - Supply is less than the number of unused strongholds (can't fill all), AND
    - Those strongholds span more than one clearing (so placement is not obvious).

    When all unused strongholds are in the same clearing, supply warriors go there
    automatically regardless of count, so no choice is needed.
    """
    supply = get_warrior_supply_count(player)
    unused = get_unused_recruit_strongholds(player)
    unused_count = unused.count()

    if supply == 0 or unused_count == 0:
        return False  # Nothing left to place
    if supply >= unused_count:
        return False  # Enough for every stronghold

    # supply < unused_count: check if strongholds span multiple clearings
    unique_clearing_count = (
        unused.values("building_slot__clearing").distinct().count()
    )
    return unique_clearing_count > 1
