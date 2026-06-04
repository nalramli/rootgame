from game.models.enums import ItemTypes, Suit
from game.models.game_models import Clearing, Player
from game.models.rats.player import (
    CommandItemEntry,
    ProwessItemEntry,
    RatsPlayerState,
)
from game.models.rats.tokens import Mob
from game.queries.general import get_adjacent_clearings

_TRACK_VALUES = [1, 2, 2, 3, 4]

# Maps each mood to the item type that blocks it (None = never blocked)
_MOOD_ITEM: dict[RatsPlayerState.MoodType, ItemTypes | None] = {
    RatsPlayerState.MoodType.BITTER: ItemTypes.HAMMER,
    RatsPlayerState.MoodType.GRANDIOSE: ItemTypes.TEA,
    RatsPlayerState.MoodType.JUBILANT: ItemTypes.BOOTS,
    RatsPlayerState.MoodType.LAVISH: None,
    RatsPlayerState.MoodType.RELENTLESS: ItemTypes.BAG,
    RatsPlayerState.MoodType.ROWDY: ItemTypes.COIN,
    RatsPlayerState.MoodType.STUBBORN: ItemTypes.CROSSBOW,
    RatsPlayerState.MoodType.WRATHFUL: ItemTypes.SWORD,
}


def get_prowess_value(player: Player) -> int:
    """Return the prowess value based on items on the Prowess track."""
    count = ProwessItemEntry.objects.filter(player=player).count()
    return _TRACK_VALUES[min(count, 4)]


def get_command_value(player: Player) -> int:
    """Return the command value based on items on the Command track."""
    count = CommandItemEntry.objects.filter(player=player).count()
    return _TRACK_VALUES[min(count, 4)]


def _get_hoard_item_types(player: Player) -> set[ItemTypes]:
    """Return the set of item types currently in the hoard (Command + Prowess entries)."""
    command_types = set(
        CommandItemEntry.objects.filter(player=player).values_list(
            "item__item_type", flat=True
        )
    )
    prowess_types = set(
        ProwessItemEntry.objects.filter(player=player).values_list(
            "item__item_type", flat=True
        )
    )
    return command_types | prowess_types


def get_valid_moods(player: Player) -> list[RatsPlayerState.MoodType]:
    """Return the list of moods the player may choose at Choose Mood step.

    Rules:
    - Cannot choose the current mood.
    - Cannot choose a mood whose associated item is already in the hoard.
    - LAVISH has no associated item and is never blocked.
    """
    state = RatsPlayerState.objects.get(player=player)
    current_mood = RatsPlayerState.MoodType(state.mood_type)
    hoard_types = _get_hoard_item_types(player)

    valid: list[RatsPlayerState.MoodType] = []
    for mood, item_type in _MOOD_ITEM.items():
        if mood == current_mood:
            continue
        if item_type is not None and item_type in hoard_types:
            continue
        valid.append(mood)

    # Edge case: if nothing is valid (all non-current moods blocked), fall back to LAVISH
    if not valid:
        valid = [RatsPlayerState.MoodType.LAVISH]

    return valid


def get_mob_spread_targets(player: Player, suit: Suit):
    """Return clearings eligible to receive a Mob token for the given suit.

    A clearing is eligible when:
    1. It matches the given suit.
    2. It does NOT already contain a Mob token owned by this player.
    3. It is adjacent to at least one clearing that already has a Mob token
       owned by this player.
    """
    # Clearings that already have a mob
    mob_clearings = set(
        mob.clearing
        for mob in Mob.objects.filter(player=player, clearing__isnull=False)
    )

    if len(mob_clearings) == 0:  # no mobs, return empty set
        return set()

    result_set: set[Clearing] = set()
    for clearing in mob_clearings:
        adjacents = get_adjacent_clearings(player, clearing)
        correct_suit = set(a for a in adjacents if Suit(a.suit) == suit)
        result_set = result_set.union(correct_suit)
    return result_set - mob_clearings
