from django.urls import reverse
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers

from game.models.birds.setup import BirdsSimpleSetup
from game.models.cats.setup import CatsSimpleSetup
from game.models.cats.turn import CatBirdsong, CatDaylight, CatTurn
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import (
    Clearing,
    DiscardPileEntry,
    Faction,
    Game,
    HandEntry,
    Player,
    CraftableItemEntry,
)
from game.queries.cats.turn import get_phase as get_cat_phase
from game.queries.current_action.setup import get_setup_action
from game.queries.current_action.turns import get_current_turn_action
from game.serializers.general_serializers import (
    CardSerializer,
    CraftableItemSerializer,
    GameStatusSerializer,
    PlayerPublicSerializer,
    GameSessionSerializer,
    ClearingSerializer,
    CurrentActionSerializer,
    DominanceSupplyEntrySerializer,
    ValidationErrorSerializer,
)
from game.serializers.revealed_cards_serializers import RevealedCardSerializer
from game.logic.playback import undo_last_action
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


@extend_schema(responses={200: CardSerializer(many=True)})
@api_view(["GET"])
def get_discard_pile(request, game_id: int):
    # grab game
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return Response(
            {"message": "Game does not exist"}, status=status.HTTP_404_NOT_FOUND
        )
    # add auth: valid player or spectator
    discarded_cards = DiscardPileEntry.objects.filter(game=game)
    serializer = CardSerializer([card.card for card in discarded_cards], many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    responses={200: CardSerializer(many=True), 400: ValidationErrorSerializer}
)
@api_view(["GET"])
def get_player_hand(request, game_id: int):
    # TODO: add auth: valid player or spectator
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        raise ValidationError("Game does not exist")
    try:
        player = Player.objects.get(user=request.user, game=game)
    except Player.DoesNotExist:
        raise ValidationError("Player does not exist")
    hand_cards = HandEntry.objects.filter(player=player)
    serializer = CardSerializer([card.card for card in hand_cards], many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(responses={200: ClearingSerializer(many=True)})
@api_view(["GET"])
def get_clearings(request, game_id: int):
    # grab game
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return Response(
            {"message": "Game does not exist"}, status=status.HTTP_404_NOT_FOUND
        )
    clearings = Clearing.objects.filter(game=game)
    serializer = ClearingSerializer(clearings, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(responses={200: GameStatusSerializer, 400: ValidationErrorSerializer})
@api_view(["GET"])
def get_turn_info(request, game_id: int):
    # grab game
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        raise ValidationError("Game does not exist")
    serializer = GameStatusSerializer.from_game(game)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(responses={200: CurrentActionSerializer, 400: ValidationErrorSerializer})
@api_view(["GET"])
def get_current_action(request, game_id: int):
    """provides the route for the current action"""
    # grab game
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        raise ValidationError("Game does not exist")
    setup_action = get_setup_action(game)
    if setup_action is not None:
        return Response({"route": setup_action})
    # else, move on to turns
    turn_action = get_current_turn_action(game)
    if turn_action is not None:
        return Response({"route": turn_action})
    # else, move on to...
    raise ValidationError("Not yet implemented")


@extend_schema(
    responses={200: PlayerPublicSerializer(many=True), 400: ValidationErrorSerializer}
)
@api_view(["GET"])
def get_players(request, game_id: int):
    """provides information about all players in the game"""
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        raise ValidationError("Game does not exist")
    players = Player.objects.filter(game=game)
    serializer = PlayerPublicSerializer(players, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    responses={
        200: inline_serializer(
            name="UndoResponse", fields={"status": serializers.CharField()}
        )
    }
)
@api_view(["POST"])
def undo_last_action_view(request, game_id: int):
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return Response({"detail": "Game not found"}, status=status.HTTP_404_NOT_FOUND)

    undo_last_action(game)

    # Publish update to WebSocket
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"game_{game.id}", {"type": "game_update", "message": "update"}
        )
    except Exception as e:
        print(f"Failed to send websocket update: {e}")

    return Response({"status": "success"}, status=status.HTTP_200_OK)


@extend_schema(responses={200: GameSessionSerializer})
@api_view(["GET"])
def get_game_session_detail(request, game_id: int):
    """provides detailed information about the game session"""
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return Response({"detail": "Game not found"}, status=status.HTTP_404_NOT_FOUND)

    serializer = GameSessionSerializer(game)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(responses={200: DominanceSupplyEntrySerializer(many=True)})
@api_view(["GET"])
def get_dominance_supply(request, game_id: int):
    """
    Returns the dominance cards currently available in the supply.
    """
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return Response({"detail": "Game not found"}, status=status.HTTP_404_NOT_FOUND)

    from game.models.dominance import DominanceSupplyEntry

    supply_entries = DominanceSupplyEntry.objects.filter(game=game)
    serializer = DominanceSupplyEntrySerializer(supply_entries, many=True)

    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(responses={200: RevealedCardSerializer(many=True)})
@api_view(["GET"])
def get_revealed_cards(request, game_id: int):
    """
    Returns history of revealed cards visible to the requesting player.
    """
    from game.serializers.revealed_cards_serializers import RevealedCardSerializer
    from game.models.events.wa import OutrageEvent
    from game.models.crows.exposure import ExposureRevealedCards
    from game.queries.general import get_current_turn_number
    from game.models.game_models import Card

    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return Response({"detail": "Game not found"}, status=status.HTTP_404_NOT_FOUND)

    try:
        player = Player.objects.get(user=request.user, game=game)
    except Player.DoesNotExist:
        # For spectators maybe empty array
        return Response([], status=status.HTTP_200_OK)
    if game.status in [Game.GameStatus.NOT_STARTED, Game.GameStatus.STARTED]:
        return Response([], status=status.HTTP_200_OK)
    current_turn = get_current_turn_number(game)

    revealed_cards_data = []

    # Add RevealedCardEntry data (visible to all players)
    from game.models.game_models import RevealedCardEntry
    entries = RevealedCardEntry.objects.filter(
        player__game=game
    ).select_related("card", "player")
    for entry in entries:
        # Dynamically determine event_type based on the revealing faction
        if entry.player.faction == Faction.MOLES.value:
            event_type = "Moles Daylight"
        else:
            # Placeholder for future factions
            event_type = "Revealed"

        turns_ago = max(0, current_turn - entry.turn_revealed)
        revealed_cards_data.append(
            {
                "card": entry.card,
                "faction": entry.player.faction,
                "event_type": event_type,
                "turns_ago": turns_ago,
            }
        )

    if player.faction == Faction.WOODLAND_ALLIANCE.value:
        # Fetch outrage events where cards were shown
        outrage_events = OutrageEvent.objects.filter(event__game=game, hand_shown=True)
        for outrage in outrage_events:
            if outrage.hand and outrage.hand.get("cards_in_hand"):
                for hand_card_data in outrage.hand["cards_in_hand"]:
                    try:
                        card_obj = Card.objects.get(id=hand_card_data["id"])
                        turns_ago = max(0, current_turn - outrage.turn_number)
                        revealed_cards_data.append(
                            {
                                "card": card_obj,
                                "faction": outrage.outrageous_player.faction,
                                "event_type": "Outrage",
                                "turns_ago": turns_ago,
                            }
                        )
                    except Card.DoesNotExist:
                        continue

    elif player.faction == Faction.CROWS.value:
        # Fetch cards wagered against crows by incorrect exposures
        exposure_events = ExposureRevealedCards.objects.filter(player__game=game)
        for exposure in exposure_events:
            turns_ago = max(0, current_turn - exposure.turn_number)
            revealed_cards_data.append(
                {
                    "card": exposure.card,
                    "faction": exposure.player.faction,
                    "event_type": "Exposure",
                    "turns_ago": turns_ago,
                }
            )

    # Sort descending by turns_ago (most recent first)
    revealed_cards_data.sort(key=lambda x: x["turns_ago"])

    serializer = RevealedCardSerializer(revealed_cards_data, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(responses={200: CraftableItemSerializer(many=True)})
@api_view(["GET"])
def get_craftable_items(request, game_id: int):
    """
    Returns a list of items that are still available to be crafted in the game.
    """
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return Response({"detail": "Game not found"}, status=status.HTTP_404_NOT_FOUND)

    craftable_items = CraftableItemEntry.objects.filter(game=game).select_related('item')
    serializer = CraftableItemSerializer(craftable_items, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

@extend_schema(responses={204: None})
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_game(request, game_id: int):
    """Delete a game. Only the owner may do this."""
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return Response({"detail": "Game not found"}, status=status.HTTP_404_NOT_FOUND)
    if game.owner != request.user:
        raise PermissionDenied("Only the game owner can delete this game.")
    game.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


from game.serializers.logs import GameLogSerializer
from game.models.game_log import GameLog

@extend_schema(responses={200: GameLogSerializer(many=True)})
@api_view(["GET"])
def get_game_logs(request, game_id: int):
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return Response({"detail": "Game not found"}, status=status.HTTP_404_NOT_FOUND)

    # Flat fetch all logs for this game (highly performant single query)
    all_logs = list(GameLog.objects.filter(game=game).order_by("created_at").select_related("player"))
    
    # Map them by ID
    logs_by_id = {log.id: log for log in all_logs}
    
    # Establish root logs list and attach _children to each instance
    root_logs = []
    
    for log in all_logs:
        log._children = [] # Initialize manual children array
        
    for log in all_logs:
        if log.parent_id:
            parent = logs_by_id.get(log.parent_id)
            if parent:
                parent._children.append(log)
        else:
            root_logs.append(log)

    serializer = GameLogSerializer(root_logs, many=True, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)
