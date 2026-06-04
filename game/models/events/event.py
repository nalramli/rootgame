from django.db import models

from game.models.game_models import Game


class EventType(models.TextChoices):
    """Event types."""

    BATTLE = "battle"
    FIELD_HOSPITAL = "field_hospital"
    TURMOIL = "turmoil"
    OUTRAGE = "outrage"
    INFORMANTS = "informants"
    SABOTEURS = "saboteurs"
    EYRIE_EMIGRE = "eyrie_emigre"
    CHARM_OFFENSIVE = "charm_offensive"
    PARTISANS = "partisans"
    SWAP_MEET = "swap_meet"
    CROW_RECRUIT = "crow_recruit"
    PLACE_RAID_WARRIORS = "place_raid_warriors"
    PRICE_OF_FAILURE = "price_of_failure"
    HOARD_TOO_FULL = "hoard_too_full"
    LOOTING = "looting"
    BITTER_RESOLVE = "bitter_resolve"
    JUBILANT_MOB_SPREAD = "jubilant_mob_spread"
    LAVISH = "lavish"


class Event(models.Model):
    """Base class for all events."""

    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    type = models.CharField(max_length=50, choices=EventType.choices)
    is_resolved = models.BooleanField(default=False)
