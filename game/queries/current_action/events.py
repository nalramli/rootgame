from django.urls import reverse
from game.models.events.battle import Battle
from game.models.events.event import Event, EventType
from game.models.game_models import Game


def get_current_event_action(game: Game) -> str | None:
    """returns the current event action for the game, or None if no event"""
    event = get_current_event(game)
    if event is None:
        return None
    match event.type:
        case EventType.BATTLE:
            return reverse("battle")
        case EventType.FIELD_HOSPITAL:
            return reverse("field-hospital")
        case EventType.TURMOIL:
            return reverse("turmoil")
        case EventType.OUTRAGE:
            return reverse("outrage")
        case EventType.INFORMANTS:
            return reverse("informants")
        case EventType.SABOTEURS:
            return reverse("saboteurs")
        case EventType.EYRIE_EMIGRE:
            return reverse("eyrie-emigre")

        case EventType.CHARM_OFFENSIVE:
            return reverse("charm-offensive")
        case EventType.PARTISANS:
            return reverse("partisans")
        case EventType.SWAP_MEET:
            return reverse("swap-meet")
        case EventType.CROW_RECRUIT:
            return reverse("crows-manual-recruit")
        case EventType.PLACE_RAID_WARRIORS:
            return reverse("crows-place-raid-warriors")
        case EventType.PRICE_OF_FAILURE:
            return reverse("moles-price-of-failure")
        case EventType.HOARD_TOO_FULL:
            return reverse("rats-hoard-too-full")
        case EventType.BITTER_RESOLVE:
            return reverse("rats-bitter-resolve")
        case EventType.LOOTING:
            return reverse("rats-looting")
        case EventType.JUBILANT_MOB_SPREAD:
            return reverse("rats-jubilant-mob-spread")
        case EventType.LAVISH:
            return reverse("rats-lavish")
        case _:
            raise ValueError("Invalid event type")


def get_current_event(game: Game) -> Event | None:
    """returns the current event for the game"""
    # get newest event (resolving like a stack)
    event = (
        Event.objects.filter(game=game, is_resolved=False)
        .order_by("-created_at", "-id")
        .first()
    )
    return event
