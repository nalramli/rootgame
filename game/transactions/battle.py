from game.errors.action_errors import UnavailableActionError
from game.errors.system_errors import InternalGameError
from game.models import GameLog
from game.models.game_models import Suit
from game.queries.general import validate_player_has_card_in_hand
from random import randint
from django.db import transaction
from game.errors import IllegalActionError

from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.birds.player import BirdLeader
from game.models.events.battle import Battle
from game.models.events.event import Event, EventType
from game.models.events.crafted_cards import PartisansEvent
from game.models.game_models import (
    Building,
    Card,
    Clearing,
    Faction,
    Game,
    HandEntry,
    Piece,
    Player,
    Token,
    Warrior,
)
from game.models.wa.tokens import WASympathy
from game.queries.general import (
    count_player_pieces_in_clearing,
    player_has_pieces_in_clearing,
    player_has_warriors_in_clearing,
    warrior_count_in_clearing,
    validate_player_has_crafted_card,
)
from game.transactions.general import discard_card_from_hand
from game.transactions.removal import (
    player_removes_building,
    player_removes_token,
    player_removes_warriors,
    start_removal_event,
    cleanup_removal_event,
)


@transaction.atomic
def start_battle(game: Game, attacker: Faction, defender: Faction, clearing: Clearing):
    """starts a battle between the given factions at the given clearing"""
    # check that attacker and defender are not the same faction
    if attacker == defender:
        raise IllegalActionError("Attacker and defender cannot be the same faction")
    # check that attacker has warriors in the clearing
    player = Player.objects.get(game=game, faction=attacker.value)

    if not player_has_warriors_in_clearing(player, clearing):
        raise IllegalActionError("Attacker does not have warriors in that clearing")
    # check that defender has pieces in the clearing
    defender_player = Player.objects.get(game=game, faction=defender.value)
    if not player_has_pieces_in_clearing(defender_player, clearing):
        raise IllegalActionError("Defender does not have pieces in that clearing")

    # create battle
    event = Event.objects.create(game=game, type=EventType.BATTLE)
    battle = Battle(
        attacker=attacker.value, defender=defender.value, clearing=clearing, event=event
    )
    battle.save()
    return battle


@transaction.atomic
def log_battle_start(
    battle: Battle, player: Player, parent: GameLog | None = None
) -> "GameLog":
    from game.serializers.logs.general import log_battle

    log = log_battle(
        battle.event.game,
        player,
        battle.clearing.clearing_number,
        battle.defender,
        battle_id=battle.pk,
        parent=parent,
    )
    return log


@transaction.atomic
def defender_ambush_choice(game: Game, battle: Battle, ambush_card: CardsEP | None):
    """
    if ambush_card is None, defender chooses not to ambush
    else, defender uses this card to ambush.
    """
    # check the timing
    if battle.step != Battle.BattleSteps.DEFENDER_AMBUSH_CHECK:
        raise UnavailableActionError("Not defender ambush check step")
    # if ambush_card is None, defender chooses not to ambush
    if ambush_card is None:
        battle.defender_ambush = False
        _check_bitter_or_roll(game, battle)
        return
    else:
        defender_player = Player.objects.get(game=game, faction=battle.defender)
        # check that card is in hand
        card_in_hand = validate_player_has_card_in_hand(defender_player, ambush_card)
        # check that card is actually an ambush
        if ambush_card.value.ambush is False:
            raise IllegalActionError("Card is not an ambush")
        # check that suit matches clearing
        if (
            card_in_hand.card.suit != battle.clearing.suit
            and card_in_hand.card.suit != Suit.WILD
        ):
            raise IllegalActionError("Card suit does not match clearing suit")
        # flag the battle as ambushed
        battle.defender_ambush = True
        battle.step = Battle.BattleSteps.ATTACKER_AMBUSH_CANCEL_CHECK
        battle.save()
        # spend card
        discard_card_from_hand(defender_player, card_in_hand)

        from game.serializers.logs.general import log_ambush, get_battle_log

        log_ambush(
            game,
            defender_player,
            card_in_hand.card,
            parent=get_battle_log(game, battle.pk),
        )


@transaction.atomic
def attacker_ambush_choice(game: Game, battle: Battle, ambush_card: CardsEP | None):
    """
    if ambush_card is None, attacker chooses not to cancel ambush
    else, attacker uses this card to cancel ambush.
    """
    # check the timing
    if battle.step != Battle.BattleSteps.ATTACKER_AMBUSH_CANCEL_CHECK:
        raise UnavailableActionError("Not attacker ambush cancel check step")
    # if no ambush card, attacker chooses not to cancel ambush
    defending_player = Player.objects.get(game=game, faction=battle.defender)
    attacking_player = Player.objects.get(game=game, faction=battle.attacker)
    if ambush_card is None:
        battle.attacker_cancel_ambush = False
        attacking_player = Player.objects.get(game=game, faction=battle.attacker)
        attacking_warriors = warrior_count_in_clearing(
            attacking_player, battle.clearing
        )
        if attacking_warriors > 2:
            # resolve ambush by removing attacking warriors and proceeding to roll
            from game.serializers.logs.general import get_battle_log

            parent_log = get_battle_log(game, battle.pk)
            player_removes_warriors(
                battle.clearing,
                defending_player,
                attacking_player,
                2,
                parent=parent_log,
            )
            _check_bitter_or_roll(game, battle)
            return
        elif attacking_warriors == 2:
            # resolve ambush by removing attacking warriors and ending the battle
            from game.serializers.logs.general import get_battle_log

            player_removes_warriors(
                battle.clearing,
                defending_player,
                attacking_player,
                2,
                parent=get_battle_log(game, battle.pk),
            )
            end_battle(game, battle)
            return
        else:
            # resolve ambush by removing remaining attacking warrior and moving to attacker choosing their hits
            from game.serializers.logs.general import get_battle_log

            player_removes_warriors(
                battle.clearing,
                defending_player,
                attacking_player,
                1,
                parent=get_battle_log(game, battle.pk),
            )
            # do i need to convey that attacker must choose one hit, or is this kind of guaranteed to only be one?
            start_removal_event(game)
            battle.step = Battle.BattleSteps.ATTACKER_CHOOSE_AMBUSH_HITS
            battle.save()
            return
    # if ambush, check that card is actually an ambush and get the hand entry
    if ambush_card.value.ambush is False:
        raise IllegalActionError("Card is not an ambush")
    if (
        ambush_card.value.suit != battle.clearing.suit
        and ambush_card.value.suit != Suit.WILD
    ):
        raise IllegalActionError("Card suit does not match clearing suit")
    attacker_player = Player.objects.get(game=game, faction=battle.attacker)
    card_in_hand = validate_player_has_card_in_hand(attacker_player, ambush_card)
    # spend card
    discard_card_from_hand(attacker_player, card_in_hand)

    from game.serializers.logs.general import log_ambush, get_battle_log

    log_ambush(
        game, attacker_player, card_in_hand.card, parent=get_battle_log(game, battle.pk)
    )
    # flag the battle as ambushed
    battle.attacker_cancel_ambush = True
    _check_bitter_or_roll(game, battle)


@transaction.atomic
def attacker_choose_ambush_hit(game: Game, battle: Battle, piece: Piece):
    """
    if attacker gets hit by ambush but only had 1 warrior, they must choose
    a building or token to remove for the remaining hit.
    """
    if battle.step != Battle.BattleSteps.ATTACKER_CHOOSE_AMBUSH_HITS:
        raise UnavailableActionError("Not attacker choose ambush hits step")

    attacking_player = Player.objects.get(game=game, faction=battle.attacker)
    defending_player = Player.objects.get(game=game, faction=battle.defender)

    if piece.player != attacking_player:
        raise IllegalActionError("Piece must belong to the attacker")

    if isinstance(piece, Warrior):
        raise IllegalActionError("Cannot choose a warrior")

    # Verify piece is in the battle clearing
    from game.serializers.logs.general import get_battle_log

    parent_log = get_battle_log(game, battle.pk)
    if isinstance(piece, Building):
        if (
            getattr(piece, "building_slot", None) is None
            or getattr(piece.building_slot, "clearing", None) != battle.clearing
        ):
            raise IllegalActionError("Piece is not in the battle clearing")
        player_removes_building(game, piece, defending_player, parent=parent_log)
    elif isinstance(piece, Token):
        if piece.clearing != battle.clearing:
            raise IllegalActionError("Piece is not in the battle clearing")
        player_removes_token(game, piece, defending_player, parent=parent_log)
    else:
        raise IllegalActionError("Piece must be a building or token")

    end_battle(game, battle)


def get_partisan_card_type(suit_str: str) -> CardsEP | None:
    suit_map = {
        "r": CardsEP.FOX_PARTISANS,
        "y": CardsEP.RABBIT_PARTISANS,
        "o": CardsEP.MOUSE_PARTISANS,
    }
    return suit_map.get(suit_str)


def can_use_partisans(player: Player, clearing: Clearing) -> bool:
    card_type = get_partisan_card_type(clearing.suit)
    if not card_type:
        return False
    try:
        validate_player_has_crafted_card(player, card_type)
        return True
    except IllegalActionError:
        return False


def check_for_partisans_and_launch(game: Game, battle: Battle) -> bool:
    """checks for partisans and launches event if needed.
    Returns True if an event was launched, False otherwise.
    """
    # Defender first
    defender_player = Player.objects.get(game=game, faction=battle.defender)
    if can_use_partisans(defender_player, battle.clearing):
        if not PartisansEvent.objects.filter(
            battle=battle, crafted_card_entry__player=defender_player
        ).exists():
            PartisansEvent.create(
                battle,
                validate_player_has_crafted_card(
                    defender_player, get_partisan_card_type(battle.clearing.suit)
                ),
            )
            return True

    # Attacker second
    attacker_player = Player.objects.get(game=game, faction=battle.attacker)
    if can_use_partisans(attacker_player, battle.clearing):
        if not PartisansEvent.objects.filter(
            battle=battle, crafted_card_entry__player=attacker_player
        ).exists():
            PartisansEvent.create(
                battle,
                validate_player_has_crafted_card(
                    attacker_player, get_partisan_card_type(battle.clearing.suit)
                ),
            )
            return True

    return False


def _check_bitter_or_roll(game: Game, battle: Battle) -> None:
    """Transition helper: advance to ROLL_DICE, launching a Bitter event first if applicable.

    The battle step is always set to ROLL_DICE here. If the Bitter mood condition
    is met, a ResolveBitterEvent is created and we return early — the dice roll is
    deferred until end_bitter resumes it. This keeps the battle state machine free
    of any Rats-specific steps.
    """
    from game.queries.rats.bitter import can_trigger_bitter_event

    battle.step = Battle.BattleSteps.ROLL_DICE
    battle.save()

    if can_trigger_bitter_event(game, Faction(battle.attacker), battle.clearing):
        from game.models.rats.player import RatsPlayerState
        from game.models.events.rats import ResolveBitterEvent

        rats_player = Player.objects.get(game=game, faction=Faction.RATS)
        ResolveBitterEvent.create(player=rats_player, battle=battle)
        return

    roll_dice(game, battle)


@transaction.atomic
def roll_dice(game: Game, battle: Battle):
    """rolls the dice for the battle and determines base hits"""
    # check the timing
    if battle.step != Battle.BattleSteps.ROLL_DICE:
        raise UnavailableActionError("Not roll dice step")
    die1 = randint(0, 3)
    die2 = randint(0, 3)
    print(f"dice rolled: {die1}, {die2}")
    hi, lo = max(die1, die2), min(die1, die2)
    attacking_player = Player.objects.get(game=game, faction=battle.attacker)
    defending_player = Player.objects.get(game=game, faction=battle.defender)
    attacking_warriors_count = warrior_count_in_clearing(
        attacking_player, battle.clearing
    )
    defending_warriors_count = warrior_count_in_clearing(
        defending_player, battle.clearing
    )
    # Rats Looters: if looting is declared, the attacker deals no rolled hits
    rats_looting = False
    if battle.attacker == Faction.RATS:
        from game.models.rats.player import RatsPlayerState

        state = RatsPlayerState.objects.get(player=attacking_player)
        if state.looting_declared:
            rats_looting = True

    # assign hits, accounting for woodland alliance guerilla warfare
    if battle.defender != Faction.WOODLAND_ALLIANCE:
        # limit hits by warrior count
        hi = min(hi, attacking_warriors_count)
        lo = min(lo, defending_warriors_count)
        if rats_looting:
            hi = 0  # attacker deals no rolled hits
        # assign hits
        battle.defender_hits_taken += hi
        battle.attacker_hits_taken += lo
    else:
        # limit hits by warrior count
        hi = min(hi, defending_warriors_count)
        lo = min(lo, attacking_warriors_count)
        if rats_looting:
            lo = 0  # attacker deals no rolled hits (lo → defender in WA case)
        # assign hits
        battle.attacker_hits_taken += hi
        battle.defender_hits_taken += lo
    # assign other additional hits and reducers...
    # undefended extra hit
    if defending_warriors_count == 0:
        battle.defender_hits_taken += 1
    # birds commander extra hit
    if battle.attacker == Faction.BIRDS:
        birds_player = Player.objects.get(game=game, faction=Faction.BIRDS)
        if (
            BirdLeader.objects.get(player=birds_player, active=True).leader
            == BirdLeader.BirdLeaders.COMMANDER
        ):
            battle.defender_hits_taken += 1

    # crows embedded agents extra hit
    if battle.defender == Faction.CROWS:
        from game.models.crows.tokens import PlotToken

        crows_player = Player.objects.get(game=game, faction=Faction.CROWS)
        if PlotToken.objects.filter(
            player=crows_player, clearing=battle.clearing, is_facedown=True
        ).exists():
            battle.attacker_hits_taken += 1

    # Rats Wrathful: as attacker in Warlord's clearing, deal +1 hit
    if battle.attacker == Faction.RATS:
        from game.models.rats.player import RatsPlayerState
        from game.queries.rats.pieces import get_warlord as get_rats_warlord

        rats_player_wrathful = attacking_player
        wrathful_state = RatsPlayerState.objects.filter(
            player=rats_player_wrathful
        ).first()
        if (
            wrathful_state
            and wrathful_state.mood_type == RatsPlayerState.MoodType.WRATHFUL
        ):
            warlord = get_rats_warlord(rats_player_wrathful)
            if warlord.clearing == battle.clearing:
                battle.defender_hits_taken += 1

    from game.serializers.logs.general import log_dice_roll, get_battle_log

    log_dice_roll(
        game,
        attacking_player,
        die1,
        die2,
        battle.attacker_hits_taken,
        battle.defender_hits_taken,
        parent=get_battle_log(game, battle.pk),
    )
    battle.save()

    # Check for partisans
    if check_for_partisans_and_launch(game, battle):
        return
    apply_dice_hits(game, battle)


@transaction.atomic
def use_partisans(game: Game, battle: Battle, partisans_event: PartisansEvent):
    """resolves a partisans event by dealing an extra hit and discarding"""
    if partisans_event.battle != battle:
        raise InternalGameError("Partisans event does not belong to this battle")
    if partisans_event.event.is_resolved:
        raise UnavailableActionError("Partisans event already resolved")

    player = partisans_event.crafted_card_entry.player
    # extra hit: dealing it to the OTHER player
    if player.faction == battle.attacker:
        battle.defender_hits_taken += 1
    else:
        battle.attacker_hits_taken += 1
    battle.save()

    # discard logic: discard all that DON'T match clearing suit (including birds!)
    clearing_suit = battle.clearing.suit
    hand = HandEntry.objects.filter(player=player)
    for entry in hand:
        if entry.card.suit != clearing_suit:
            discard_card_from_hand(player, entry)

    # resolve event
    partisans_event.event.is_resolved = True
    partisans_event.event.save()

    # check for next partisan event or apply hits
    if not check_for_partisans_and_launch(game, battle):
        apply_dice_hits(game, battle)


@transaction.atomic
def skip_partisans(game: Game, battle: Battle, partisans_event: PartisansEvent):
    """resolves a partisans event by skipping it"""
    if partisans_event.battle != battle:
        raise InternalGameError("Partisans event does not belong to this battle")
    if partisans_event.event.is_resolved:
        raise UnavailableActionError("Partisans event already resolved")

    # resolve event
    partisans_event.event.is_resolved = True
    partisans_event.event.save()

    # check for next partisan event or apply hits
    if not check_for_partisans_and_launch(game, battle):
        apply_dice_hits(game, battle)


@transaction.atomic
def apply_dice_hits(game: Game, battle: Battle):
    """applies the hits calculated during roll_dice and partisan events"""
    attacking_player = Player.objects.get(game=game, faction=battle.attacker)
    defending_player = Player.objects.get(game=game, faction=battle.defender)

    # Rats Stubborn: in the Warlord's clearing, ignore the first hit taken.
    # Applied here (not in roll_dice) so it covers partisan hits too.
    # Does not combine with other first-hit-ignore abilities.
    if Faction.RATS in (battle.attacker, battle.defender):
        from game.models.rats.player import RatsPlayerState
        from game.queries.rats.pieces import get_warlord as get_rats_warlord

        rats_is_attacker = battle.attacker == Faction.RATS
        rats_player = attacking_player if rats_is_attacker else defending_player
        rats_state = RatsPlayerState.objects.get(player=rats_player)
        if rats_state.mood_type == RatsPlayerState.MoodType.STUBBORN:
            warlord = get_rats_warlord(rats_player)
            if warlord.clearing == battle.clearing:
                if rats_is_attacker:
                    battle.attacker_hits_taken = max(0, battle.attacker_hits_taken - 1)
                else:
                    battle.defender_hits_taken = max(0, battle.defender_hits_taken - 1)
                battle.save()

    attacking_warriors_count = warrior_count_in_clearing(
        attacking_player, battle.clearing
    )
    defending_warriors_count = warrior_count_in_clearing(
        defending_player, battle.clearing
    )

    from game.serializers.logs.general import get_battle_log

    parent_log = get_battle_log(game, battle.pk)

    # assign hits automatically if possible. otherwise, go to choice steps
    if defending_warriors_count >= battle.defender_hits_taken:
        player_removes_warriors(
            battle.clearing,
            attacking_player,
            defending_player,
            battle.defender_hits_taken,
            parent=parent_log,
        )
        battle.defender_hits_assigned = battle.defender_hits_taken
    else:
        # remove warriors and tally assigned hits, and then move on to choice stage if anything else left to hit and more hits to assign
        battle.defender_hits_assigned = defending_warriors_count
        player_removes_warriors(
            battle.clearing,
            attacking_player,
            defending_player,
            defending_warriors_count,
            parent=parent_log,
        )
        pieces_left_to_hit = count_player_pieces_in_clearing(
            defending_player, battle.clearing
        )
        defender_hits_left_to_assign = (
            battle.defender_hits_taken - battle.defender_hits_assigned
        )
        if defender_hits_left_to_assign > 0 and pieces_left_to_hit > 0:
            if pieces_left_to_hit <= defender_hits_left_to_assign:
                start_removal_event(game)
                tokens = Token.objects.filter(
                    clearing=battle.clearing, player=defending_player
                )
                for token in tokens:
                    player_removes_token(
                        game, token, attacking_player, parent=parent_log
                    )
                buildings = Building.objects.filter(
                    building_slot__clearing=battle.clearing, player=defending_player
                )
                for building in buildings:
                    player_removes_building(
                        game, building, attacking_player, parent=parent_log
                    )

            else:  # more pieces than hits, go to choice step
                start_removal_event(game)
                battle.step = Battle.BattleSteps.DEFENDER_CHOOSE_HITS
                battle.save()

    if attacking_warriors_count >= battle.attacker_hits_taken:
        player_removes_warriors(
            battle.clearing,
            defending_player,
            attacking_player,
            battle.attacker_hits_taken,
            parent=parent_log,
        )
        battle.attacker_hits_assigned = battle.attacker_hits_taken
    else:
        # remove warriors and tally assigned hits, and then move on to choice stage if any more hits to assign, and pieces left to hit
        battle.attacker_hits_assigned = attacking_warriors_count
        player_removes_warriors(
            battle.clearing,
            defending_player,
            attacking_player,
            attacking_warriors_count,
            parent=parent_log,
        )
        attacking_pieces_count = count_player_pieces_in_clearing(
            attacking_player, battle.clearing
        )
        attacking_hits_left_to_assign = (
            battle.attacker_hits_taken - battle.attacker_hits_assigned
        )
        if attacking_hits_left_to_assign > 0 and attacking_pieces_count > 0:
            if attacking_pieces_count <= attacking_hits_left_to_assign:
                # remove all pieces, don't need to do choice step
                start_removal_event(game)
                tokens = Token.objects.filter(
                    clearing=battle.clearing, player=attacking_player
                )
                for token in tokens:
                    player_removes_token(
                        game, token, defending_player, parent=parent_log
                    )
                buildings = Building.objects.filter(
                    building_slot__clearing=battle.clearing, player=attacking_player
                )
                for building in buildings:
                    player_removes_building(
                        game, building, defending_player, parent=parent_log
                    )
            else:  # more pieces than hits, go to choice step if not already on defender choice step
                if battle.step != Battle.BattleSteps.DEFENDER_CHOOSE_HITS:
                    start_removal_event(game)
                    battle.step = Battle.BattleSteps.ATTACKER_CHOOSE_HITS

    if battle.step == Battle.BattleSteps.ROLL_DICE:
        # if we havent moved to choice steps, then all needed hits have been assigned and we can move on.
        end_battle(game, battle)
    battle.save()


def defender_chooses_hit(game: Game, battle: Battle, piece: Piece):
    if battle.step != Battle.BattleSteps.DEFENDER_CHOOSE_HITS:
        raise UnavailableActionError("Not defender choose hits step")
    defending_player = Player.objects.get(game=game, faction=battle.defender)
    attacking_player = Player.objects.get(game=game, faction=battle.attacker)
    if piece.player != defending_player:
        raise IllegalActionError("Piece must belong to the defender")
    if isinstance(piece, Warrior):
        raise IllegalActionError("Cannot choose a warrior")

    if isinstance(piece, Building):
        from game.serializers.logs.general import get_battle_log

        parent_log = get_battle_log(game, battle.pk)
        if (
            getattr(piece, "building_slot", None) is None
            or getattr(piece.building_slot, "clearing", None) != battle.clearing
        ):
            raise IllegalActionError("Piece is not in the battle clearing")
        player_removes_building(game, piece, attacking_player, parent=parent_log)
    elif isinstance(piece, Token):
        from game.serializers.logs.general import get_battle_log

        parent_log = get_battle_log(game, battle.pk)
        if piece.clearing != battle.clearing:
            raise IllegalActionError("Piece is not in the battle clearing")
        player_removes_token(game, piece, attacking_player, parent=parent_log)
    else:
        raise IllegalActionError("Piece must be a building or token")

    battle.defender_hits_assigned += 1
    if battle.defender_hits_assigned >= battle.defender_hits_taken:
        # Move to attacker choosing hits or end
        attacking_pieces_count = count_player_pieces_in_clearing(
            attacking_player, battle.clearing
        )
        attacking_hits_left_to_assign = (
            battle.attacker_hits_taken - battle.attacker_hits_assigned
        )
        if attacking_hits_left_to_assign > 0 and attacking_pieces_count > 0:
            cleanup_removal_event(game)
            start_removal_event(game)
            battle.step = Battle.BattleSteps.ATTACKER_CHOOSE_HITS
        else:
            end_battle(game, battle)
    battle.save()


def attacker_chooses_hit(game: Game, battle: Battle, piece: Piece):
    if battle.step != Battle.BattleSteps.ATTACKER_CHOOSE_HITS:
        raise UnavailableActionError("Not attacker choose hits step")
    attacking_player = Player.objects.get(game=game, faction=battle.attacker)
    defending_player = Player.objects.get(game=game, faction=battle.defender)
    if piece.player != attacking_player:
        raise IllegalActionError("Piece must belong to the attacker")
    if isinstance(piece, Warrior):
        raise IllegalActionError("Cannot choose a warrior")

    if isinstance(piece, Building):
        from game.serializers.logs.general import get_battle_log

        parent_log = get_battle_log(game, battle.pk)
        if (
            getattr(piece, "building_slot", None) is None
            or getattr(piece.building_slot, "clearing", None) != battle.clearing
        ):
            raise IllegalActionError("Piece is not in the battle clearing")
        player_removes_building(game, piece, defending_player, parent=parent_log)
    elif isinstance(piece, Token):
        from game.serializers.logs.general import get_battle_log

        parent_log = get_battle_log(game, battle.pk)
        if piece.clearing != battle.clearing:
            raise IllegalActionError("Piece is not in the battle clearing")
        player_removes_token(game, piece, defending_player, parent=parent_log)
    else:
        raise IllegalActionError("Piece must be a building or token")

    battle.attacker_hits_assigned += 1
    if battle.attacker_hits_assigned >= battle.attacker_hits_taken:
        end_battle(game, battle)
    battle.save()


def end_battle(game: Game, battle: Battle):
    """ends the battle and updates the battle and event objects"""
    cleanup_removal_event(game)
    # update battle
    battle.step = Battle.BattleSteps.COMPLETED
    battle.save()
    # update event
    event = battle.event
    event.is_resolved = True
    event.save()
    # Rats Looters: resolve looting if declared
    if battle.attacker == Faction.RATS:
        _resolve_looting_after_battle(game, battle)


def _resolve_looting_after_battle(game: Game, battle: Battle) -> None:
    """Check looting declaration and resolve: auto-loot, create choice event, or reset."""
    from game.models.rats.player import RatsPlayerState
    from game.models.game_models import CraftedItemEntry
    from game.queries.general import determine_clearing_rule

    rats_player = Player.objects.get(game=game, faction=Faction.RATS)
    state = RatsPlayerState.objects.filter(player=rats_player).first()
    if state is None or not state.looting_declared:
        return

    # Did the Rats earn the loot? They must rule the clearing.
    if determine_clearing_rule(battle.clearing) != rats_player:
        state.looting_declared = False
        state.save()
        return

    defender_player = Player.objects.get(game=game, faction=battle.defender)
    items = list(
        CraftedItemEntry.objects.filter(player=defender_player).select_related("item")
    )

    if not items:
        # not sure how they wouldnt have items, but in case of future fan factions
        state.looting_declared = False
        state.save()
        return

    if len(items) == 1:
        # Auto-loot: only one item available.
        from game.transactions.rats.hoard import add_item_to_hoard

        entry = items[0]
        item = entry.item
        entry.delete()
        add_item_to_hoard(rats_player, item)
        state.looting_declared = False
        state.save()
    else:
        # Multiple items: create choice event (looting_declared stays True until resolved).
        from game.models.events.rats import LootingEvent

        LootingEvent.create(looting_player=rats_player, looted_player=defender_player)
