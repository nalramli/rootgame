from django.db import transaction
from game.models import Piece
from game.models import CatKeep
from game.models.events.battle import Battle
from game.models.game_models import (
    Building,
    Clearing,
    Faction,
    Game,
    Player,
    Token,
    Warrior,
    CoffinWarrior,
)
from game.transactions.cats import create_field_hospital_event
from game.transactions.outrage import create_outrage_event
from game.queries.crafted_cards import get_coffin_makers_player
from game.errors import InternalGameError


def get_piece_name(piece: Piece) -> str:
    """Returns a readable name for the piece"""
    from game.models.wa.tokens import WASympathy
    from game.models.wa.buildings import WABase
    from game.models.birds.buildings import BirdRoost
    from game.models.cats.buildings import Sawmill, Workshop, Recruiter
    from game.models.cats.tokens import CatWood, CatKeep
    from game.models.crows.tokens import PlotToken

    if isinstance(piece, Warrior):
        return "Warrior"
    if hasattr(piece, "wasympathy"):
        return "Sympathy"
    if hasattr(piece, "birdroost"):
        return "Roost"
    if hasattr(piece, "workshop"):
        return "Workshop"
    if hasattr(piece, "sawmill"):
        return "Sawmill"
    if hasattr(piece, "recruiter"):
        return "Recruiter"
    if hasattr(piece, "wabase"):
        return "Base"
    if hasattr(piece, "catkeep"):
        return "Keep"
    if isinstance(piece, Building):
        return "Building"
    if hasattr(piece, "catwood"):
        return "Wood"
    if hasattr(piece, "plottoken"):
        plot = piece.plottoken
        return f"{PlotToken.PlotType(plot.plot_type).label} Plot"
    if isinstance(piece, Token):
        return "Token"

    return piece.__class__.__name__


def return_warrior_to_supply(warrior: Warrior):
    """Returns a warrior to the supply, or to Coffin Makers if it exists."""
    game = warrior.player.game
    coffin_player = get_coffin_makers_player(game)

    if coffin_player:
        CoffinWarrior.warrior_to_coffin(warrior)
    else:
        warrior.clearing = None
        warrior.save()


def battler_removes_all_pieces(game: Game, battle: Battle, defender: bool, **kwargs):
    """removes all pieces of defender (if True) or attacker (if False) from the battle clearing"""
    parent = kwargs.get("parent")
    removing_player = Player.objects.get(
        game=game, faction=battle.attacker if defender else battle.defender
    )
    removed_player = Player.objects.get(
        game=game, faction=battle.defender if defender else battle.attacker
    )
    warrior_count = Warrior.objects.filter(
        clearing=battle.clearing, player=removed_player
    ).count()
    player_removes_warriors(
        battle.clearing, removing_player, removed_player, warrior_count, parent=parent
    )
    tokens = Token.objects.filter(clearing=battle.clearing, player=removed_player)
    for token in tokens:
        player_removes_token(game, token, removing_player, parent=parent)
    buildings = Building.objects.filter(
        building_slot__clearing=battle.clearing, player=removed_player
    )
    for building in buildings:
        player_removes_building(game, building, removing_player, parent=parent)


def player_removes_warriors(
    clearing: Clearing,
    removing_player: Player,
    removed_player: Player,
    count: int,
    **kwargs,
):
    """removes warriors from the board by player, triggering any relevant events"""
    parent = kwargs.get("parent")
    if count == 0:
        return

    if removed_player.faction == Faction.RATS:
        from game.models.events.event import Event, EventType

        in_battle = Event.objects.filter(
            game=removed_player.game,
            is_resolved=False,
            type=EventType.BATTLE,
        ).exists()

        if not in_battle:
            # Outside battle: Warlord is immune (rule 14.2.2).
            warlord_here = Warrior.objects.filter(
                clearing=clearing, player=removed_player, warlord__isnull=False
            ).exists()
            warrior_count = Warrior.objects.filter(
                player=removed_player, clearing=clearing
            ).count()
            if warlord_here and count == warrior_count:
                # Trying to remove all warriors, including warlord: discount warlord
                count -= 1
            if count == 0:
                return

        # Regular warriors sort first (is_warlord=0); Warlord sorts last (is_warlord=1).
        # In battle this ensures the Warlord is only taken after regulars are exhausted.
        from django.db.models import Case, IntegerField, Value, When

        warriors = list(
            Warrior.objects.filter(clearing=clearing, player=removed_player)
            .annotate(
                is_warlord=Case(
                    When(warlord__isnull=False, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
            .order_by("is_warlord")[:count]
        )
        if len(warriors) != count:
            raise ValueError("Not enough warriors to remove")
    else:
        warriors = list(
            Warrior.objects.filter(clearing=clearing, player=removed_player)[:count]
        )
        if len(warriors) != count:
            raise ValueError("Not enough warriors to remove")

    # For Cats, we launch Field Hospital event if keep is not destroyed.
    # Warriors are temporarily moved to clearing=None (supply) so they can be saved to keep.
    # If not saved, they will eventually go to Coffin/Supply via return_warrior_to_supply.

    keep = CatKeep.objects.filter(player=removed_player).first()
    if removed_player.faction == Faction.CATS and keep and not keep.destroyed:
        for warrior in warriors:
            warrior.clearing = None
            warrior.save()
        create_field_hospital_event(clearing, removed_player, count)
    else:
        # Non-cat warriors go through the coffin check immediately
        for warrior in warriors:
            return_warrior_to_supply(warrior)

    if not kwargs.get("skip_log", False):
        from game.serializers.logs.general import log_piece_removal

        log_piece_removal(
            clearing.game,
            removing_player if removing_player else removed_player,
            removed_player.faction,
            "Warrior",
            clearing.clearing_number,
            count=count,
            parent=parent,
        )


def player_removes_token(game: Game, token: Token, removing_player: Player, **kwargs):
    """removes a token from the board by player, scoring points and triggering any relevant events"""
    parent = kwargs.get("parent")
    clearing = token.clearing
    is_exposure = kwargs.get("is_exposure", False)

    # check for Crow Raid effect
    from game.models.crows.tokens import PlotToken

    plot_token = PlotToken.objects.filter(pk=token.pk).first()
    if (
        plot_token
        and plot_token.plot_type == PlotToken.PlotType.RAID
        and not is_exposure
    ):
        from game.transactions.crows.raid import trigger_raid_effect

        trigger_raid_effect(token.player, clearing, parent=parent)

    # check faction relevant events
    # check if token is a sympathy token
    wa_player = Player.objects.filter(
        game=game, faction=Faction.WOODLAND_ALLIANCE
    ).first()
    from game.models.wa.tokens import WASympathy

    if wa_player and WASympathy.objects.filter(pk=token.pk).exists():
        # launch Outrage event
        create_outrage_event(
            token.clearing, removing_player, wa_player, trigger_type="remove"
        )
    # if token is the keep, mark as destroyed
    cat_player = Player.objects.filter(game=game, faction=Faction.CATS).first()
    if cat_player:
        keep = CatKeep.objects.filter(player=cat_player).first()
        if keep and token.pk == keep.pk:
            keep.destroyed = True
            keep.save()

    # remove token
    token.clearing = None
    token.save()
    # remover scores a point
    removing_player.score += 1
    removing_player.save()

    if not kwargs.get("skip_log", False):
        from game.serializers.logs.general import log_piece_removal

        log_piece_removal(
            game,
            removing_player,
            token.player.faction,
            get_piece_name(token),
            clearing.clearing_number,
            count=1,
            parent=parent,
        )


def player_removes_building(
    game: Game, building: Building, removing_player: Player, **kwargs
):
    """removes a building from the board by player, scoring points and triggering any relevant events"""
    parent = kwargs.get("parent")
    clearing = building.building_slot.clearing
    building.building_slot = None
    building.save()
    # remover scores a point
    removing_player.score += 1
    removing_player.save()

    if not kwargs.get("skip_log", False):
        from game.serializers.logs.general import log_piece_removal

        log_piece_removal(
            game,
            removing_player,
            building.player.faction,
            get_piece_name(building),
            clearing.clearing_number,
            count=1,
            parent=parent,
        )
    # check faction relevant events
    from game.models.wa.buildings import WABase

    wa_base = WABase.objects.filter(pk=building.pk).first()
    if wa_base:
        from game.transactions.wa import resolve_wa_base_removal

        resolve_wa_base_removal(
            game, building.player, clearing, building, parent=parent
        )

    # Check for Moles price of failure
    from game.models.moles.buildings import Citadel, Market

    if (
        Citadel.objects.filter(pk=building.pk).exists()
        or Market.objects.filter(pk=building.pk).exists()
    ):
        from game.transactions.moles.price_of_failure import trigger_price_of_failure

        trigger_price_of_failure(building.player)


@transaction.atomic
def start_removal_event(game: Game):
    """Create a RemovalEventTracker for the current removal event.

    Raises InternalGameError if one already exists.
    """
    from game.models.removal_tracker import RemovalEventTracker

    if RemovalEventTracker.objects.filter(game=game).exists():
        raise InternalGameError("RemovalEventTracker already exists for this game")
    RemovalEventTracker.objects.create(game=game)


@transaction.atomic
def cleanup_removal_event(game: Game):
    """Delete the RemovalEventTracker after a removal event ends.

    Safe to call even if no tracker exists (no-op in that case).
    """
    from game.models.removal_tracker import RemovalEventTracker

    tracker = RemovalEventTracker.objects.filter(game=game).first()
    if tracker:
        tracker.delete()
