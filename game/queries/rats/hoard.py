from game.errors import IllegalActionError
from game.models.enums import ItemTypes
from game.models.events.rats import HoardTooFullEvent

_COMMAND_ITEMS: set[str] = {ItemTypes.BOOTS, ItemTypes.BAG, ItemTypes.COIN}
_PROWESS_ITEMS: set[str] = {
    ItemTypes.HAMMER,
    ItemTypes.TEA,
    ItemTypes.SWORD,
    ItemTypes.CROSSBOW,
}


def get_item_track(item_type: str) -> HoardTooFullEvent.Track:
    """Return which hoard track the item type belongs to.

    Raises:
        IllegalActionError: if the item type does not belong to either track.
    """
    if item_type in _COMMAND_ITEMS:
        return HoardTooFullEvent.Track.COMMAND
    if item_type in _PROWESS_ITEMS:
        return HoardTooFullEvent.Track.PROWESS
    raise IllegalActionError(
        f"Item type '{item_type}' does not belong to either hoard track"
    )
