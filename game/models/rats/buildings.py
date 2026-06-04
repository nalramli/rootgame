from django.db import models

from game.models.game_models import Building, CraftingPieceMixin


class Stronghold(Building, CraftingPieceMixin):
    # Set to True when this stronghold has already placed its warrior
    # in the current Birdsong RECRUIT step; reset at end of turn.
    recruit_used = models.BooleanField(default=False)
