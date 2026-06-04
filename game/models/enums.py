from django.db import models


class Faction(models.TextChoices):
    CATS = "ca", "Cats"
    BIRDS = "bi", "Birds"
    WOODLAND_ALLIANCE = "wa", "Woodland Alliance"
    CROWS = "cr", "Crows"
    MOLES = "mo", "Moles"
    RATS = "ra", "Rats"


class Suit(models.TextChoices):
    RED = "r", "Fox"
    YELLOW = "y", "Rabbit"
    ORANGE = "o", "Mouse"
    WILD = "b", "Bird"


class ItemTypes(models.TextChoices):
    BOOTS = "0", "Boots"
    BAG = "1", "Bag"
    CROSSBOW = "2", "Crossbow"
    HAMMER = "3", "Hammer"
    SWORD = "4", "Sword"
    TEA = "5", "Tea"
    COIN = "6", "Coin"


class DayPhase(models.TextChoices):
    BIRDSONG = "0", "Birdsong"
    DAYLIGHT = "1", "Daylight"
    EVENING = "2", "Evening"
