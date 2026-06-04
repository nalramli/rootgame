from django.db import models

from game.models.game_models import Item, Player


class RatsPlayerState(models.Model):
    """Persistent per-player state for the Rats faction."""

    class MoodType(models.TextChoices):
        BITTER = "bitter", "Bitter"
        GRANDIOSE = "grandiose", "Grandiose"
        JUBILANT = "jubilant", "Jubilant"
        LAVISH = "lavish", "Lavish"
        RELENTLESS = "relentless", "Relentless"
        ROWDY = "rowdy", "Rowdy"
        STUBBORN = "stubborn", "Stubborn"
        WRATHFUL = "wrathful", "Wrathful"

    player = models.OneToOneField(
        Player, on_delete=models.CASCADE, related_name="rats_state"
    )
    mood_type = models.CharField(
        max_length=10, choices=MoodType.choices, default=MoodType.STUBBORN
    )
    looting_declared = models.BooleanField(default=False)


class CommandItemEntry(models.Model):
    player = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name="command_items"
    )
    item = models.OneToOneField(Item, on_delete=models.CASCADE)


class ProwessItemEntry(models.Model):
    player = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name="prowess_items"
    )
    item = models.OneToOneField(Item, on_delete=models.CASCADE)
