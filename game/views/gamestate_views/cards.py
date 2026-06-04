from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from game.models.game_models import Game, Player, Faction, CraftedCardEntry
from game.serializers.general_serializers import CraftedCardSerializer


class GetCraftedCardsView(APIView):
    def get(self, request, game_id, faction):
        game = get_object_or_404(Game, pk=game_id)
        try:
            # map kebab-case back to short codes if necessary
            mapping = {
                "cats": "ca",
                "birds": "bi",
                "woodland-alliance": "wa",
                "crows": "cr",
                "moles": "mo",
                "rats": "ra",
            }
            faction_code = mapping.get(faction, faction)
            faction_value = Faction(faction_code).value
        except ValueError:
            return Response(
                {"error": "Invalid faction"}, status=status.HTTP_400_BAD_REQUEST
            )
        player = get_object_or_404(Player, game=game, faction=faction_value)

        # Get crafted cards
        crafted_cards = CraftedCardEntry.objects.filter(player=player).select_related(
            "card"
        )

        serializer = CraftedCardSerializer(crafted_cards, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
