"""Transactions for the Jubilant mood mob-spread event.

After Incite in the Warlord's clearing (Jubilant mood), the Rats player may roll
the mob die up to four times and place a Mob token in a matching clearing that:
  - matches the rolled suit, and
  - has no existing mob, but
  - is adjacent to any clearing that already has a mob.

The event resolves when:
  - all rolls are used, OR
  - the player ends rolling early, OR
  - no mob tokens remain in supply.
"""

import random

from django.db import transaction

from game.errors import IllegalActionError, UnavailableActionError
from game.models.enums import Suit
from game.models.events.rats import JubilantMobSpreadEvent
from game.models.game_models import Clearing, Player
from game.models.rats.tokens import Mob
from game.queries.rats.birdsong import get_mob_spread_targets
from game.transactions.rats.birdsong import _place_mob_in_clearing


def _get_active_jubilant_event(player: Player) -> JubilantMobSpreadEvent:
    evt = (
        JubilantMobSpreadEvent.objects.filter(player=player, event__is_resolved=False)
        .select_related("event")
        .first()
    )
    if evt is None:
        raise UnavailableActionError("No active Jubilant mob spread event")
    return evt


def _resolve_event(evt: JubilantMobSpreadEvent) -> None:
    evt.event.is_resolved = True
    evt.event.save()


@transaction.atomic
def jubilant_roll(player: Player) -> None:
    """Roll the mob die and either auto-place (one target) or record suit (multiple targets).

    Consumes one roll from rolls_remaining. Auto-resolves when:
      - rolls_remaining drops to 0, OR
      - no mob tokens remain in supply after the roll is consumed, OR
      - no valid targets exist for the rolled suit (roll is wasted).
    """
    evt = _get_active_jubilant_event(player)

    if evt.rolls_remaining <= 0:
        _resolve_event(evt)
        return

    if not Mob.objects.filter(player=player, clearing__isnull=True).exists():
        _resolve_event(evt)
        return

    rolled_suit = random.choice([Suit.RED, Suit.YELLOW, Suit.ORANGE])
    targets = get_mob_spread_targets(player, rolled_suit)

    evt.rolls_remaining -= 1

    if len(targets) == 0:
        # No valid placement — roll is wasted
        if evt.rolls_remaining == 0:
            _resolve_event(evt)
        else:
            evt.current_roll = None
            evt.save()
        return

    if len(targets) == 1:
        # Auto-place the mob
        target_clearing = targets.pop()
        _place_mob_in_clearing(player, target_clearing)
        from game.serializers.logs.general import get_active_phase_log
        from game.serializers.logs.rats import log_rats_jubilant_spread
        phase_log = get_active_phase_log(player.game)
        log_rats_jubilant_spread(
            player.game, player,
            target_clearing.clearing_number, evt.rolls_remaining,
            parent=phase_log,
        )
        evt.current_roll = None
        if evt.rolls_remaining == 0 or not Mob.objects.filter(player=player, clearing__isnull=True).exists():
            _resolve_event(evt)
        else:
            evt.save()
        return

    # Multiple targets — record the rolled suit and wait for player choice
    evt.current_roll = rolled_suit
    evt.save()


@transaction.atomic
def jubilant_choose_clearing(player: Player, clearing: Clearing) -> None:
    """Player selects which clearing receives the mob when multiple targets exist."""
    evt = _get_active_jubilant_event(player)

    if evt.current_roll is None:
        raise UnavailableActionError("No roll in progress — call jubilant_roll first")

    valid_targets = get_mob_spread_targets(player, Suit(evt.current_roll))
    if clearing not in valid_targets:
        raise IllegalActionError("Chosen clearing is not a valid mob spread target")

    _place_mob_in_clearing(player, clearing)

    from game.serializers.logs.general import get_active_phase_log
    from game.serializers.logs.rats import log_rats_jubilant_spread
    phase_log = get_active_phase_log(player.game)
    log_rats_jubilant_spread(
        player.game, player,
        clearing.clearing_number, evt.rolls_remaining,
        parent=phase_log,
    )

    evt.current_roll = None

    if evt.rolls_remaining == 0 or not Mob.objects.filter(player=player, clearing__isnull=True).exists():
        _resolve_event(evt)
    else:
        evt.save()


@transaction.atomic
def jubilant_end(player: Player) -> None:
    """Player voluntarily ends rolling early, resolving the event."""
    evt = _get_active_jubilant_event(player)
    _resolve_event(evt)
