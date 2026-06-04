from django.db.models import QuerySet

from game.models.game_models import Player, Warrior
from game.models.rats.tokens import Warlord


def get_warriors(player: Player, exclude_warlord: bool = True) -> QuerySet[Warrior]:
    """Returns warriors for the rats player.
    By default excludes the Warlord, since it is reported separately.
    """
    qs = Warrior.objects.filter(player=player)
    if exclude_warlord:
        qs = qs.filter(warlord__isnull=True)
    return qs


def get_warlord(player: Player) -> Warlord:
    return Warlord.objects.get(player=player)
