from django.db import models

from game.models.events.battle import Battle
from game.models.events.event import Event, EventType
from game.models.enums import Suit
from game.models.game_models import Player, Item


class HoardTooFullEvent(models.Model):
    class Track(models.TextChoices):
        COMMAND = "command", "Command"
        PROWESS = "prowess", "Prowess"

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="hoard_too_full"
    )
    player = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name="hoard_too_full_events"
    )
    track = models.CharField(max_length=10, choices=Track.choices)

    @classmethod
    def create(cls, player: Player, track: "HoardTooFullEvent.Track") -> "HoardTooFullEvent":
        event = Event.objects.create(
            game=player.game, type=EventType.HOARD_TOO_FULL
        )
        return cls.objects.create(event=event, player=player, track=track)


class LootingEvent(models.Model):
    """Created when the Rats have declared looting and the defender has multiple
    items in their Crafted Items box — the Rats player must choose which to take."""

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="looting"
    )
    looting_player = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name="looting_events"
    )
    looted_player = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name="being_looted_events"
    )

    @classmethod
    def create(
        cls, looting_player: Player, looted_player: Player
    ) -> "LootingEvent":
        event = Event.objects.create(
            game=looting_player.game, type=EventType.LOOTING
        )
        return cls.objects.create(
            event=event,
            looting_player=looting_player,
            looted_player=looted_player,
        )


class ResolveBitterEvent(models.Model):
    """Launched before dice roll when the Rats have the Bitter mood and their
    Warlord is in the battle clearing with Mob tokens nearby.  The Rats player
    may call absorb_mob() one or more times, then end_bitter() to proceed."""

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="bitter"
    )
    player = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name="bitter_events"
    )
    battle = models.ForeignKey(
        Battle, on_delete=models.CASCADE, related_name="bitter_events"
    )

    @classmethod
    def create(cls, player: Player, battle: Battle) -> "ResolveBitterEvent":
        event = Event.objects.create(
            game=player.game, type=EventType.BITTER_RESOLVE
        )
        return cls.objects.create(event=event, player=player, battle=battle)


class LavishEvent(models.Model):
    """Created at the BEFORE_END step of Birdsong when the player is Lavish and
    has at least one Hoard item.  The player may liquidate items one at a time
    (each yields 2 warriors in the Warlord's clearing) then end voluntarily or
    when the Hoard is empty."""

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="lavish"
    )
    player = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name="lavish_events"
    )

    @classmethod
    def create(cls, player: Player) -> "LavishEvent":
        event = Event.objects.create(game=player.game, type=EventType.LAVISH)
        return cls.objects.create(event=event, player=player)


class JubilantMobSpreadEvent(models.Model):
    """Created after Incite in the Warlord's clearing when the Rats have Jubilant mood.

    The player may roll the mob die up to four times and place a Mob token in a
    matching clearing adjacent to any clearing that already has a mob.
    """

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="jubilant_mob_spread"
    )
    player = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name="jubilant_mob_spread_events"
    )
    rolls_remaining = models.PositiveSmallIntegerField(default=4)
    current_roll = models.CharField(
        max_length=10, choices=Suit.choices, null=True, blank=True
    )

    @classmethod
    def create(cls, player: Player) -> "JubilantMobSpreadEvent":
        event = Event.objects.create(
            game=player.game, type=EventType.JUBILANT_MOB_SPREAD
        )
        return cls.objects.create(event=event, player=player)
