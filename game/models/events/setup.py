from django.db import models

from game.models.game_models import Game


class GameSimpleSetup(models.Model):
    class GameSetupStatus(models.TextChoices):
        INITIAL_SETUP = "INIT", "Initial Setup"
        CATS_SETUP = "CAT", "Cats Setup"
        BIRDS_SETUP = "BIRD", "Birds Setup"
        WA_SETUP = "WA", "Woodland Alliance Setup"
        VB_SETUP = "VB", "Vagabond Setup"
        CROWS_SETUP = "CROW", "Crows Setup"
        MOLES_SETUP = "MOL", "Moles Setup"
        RATS_SETUP = "RAT", "Rats Setup"
        COMPLETED = "COMP", "Completed"

    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, related_name="simple_setup"
    )
    status = models.CharField(
        max_length=4,
        choices=GameSetupStatus.choices,
        default=GameSetupStatus.INITIAL_SETUP,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["game"],
                name="unique_game_setup_per_game",
            )
        ]
