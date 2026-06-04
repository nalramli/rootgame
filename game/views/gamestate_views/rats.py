from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view
from drf_spectacular.utils import extend_schema

from game.models.game_models import Faction, Game, Player
from game.serializers.rats_serializers import RatsSerializer


@extend_schema(responses={200: RatsSerializer})
@api_view(["GET"])
def get_rats_player_public(request, game_id: int):
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return Response(
            {"message": "Game does not exist"}, status=status.HTTP_404_NOT_FOUND
        )
    try:
        rats_player = Player.objects.get(game=game, faction=Faction.RATS)
    except Player.DoesNotExist:
        return Response(
            {"message": "Rats player does not exist in this game"},
            status=status.HTTP_404_NOT_FOUND,
        )
    serializer = RatsSerializer.from_player(rats_player)
    return Response(serializer.data, status=status.HTTP_200_OK)
