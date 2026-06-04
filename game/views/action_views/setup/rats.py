from game.decorators.transaction_decorator import atomic_game_action
from game.models.rats.setup import RatsSimpleSetup
from game.models.game_models import Clearing, Faction
from game.transactions.rats_setup import (
    confirm_completed_setup,
    pick_corner,
)
from ..general import GameActionView
from rest_framework.exceptions import ValidationError
from rest_framework.views import Response
from rest_framework import status


class RatsPickCornerView(GameActionView):
    action_name = "RATS_PICK_CORNER"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        return self.generate_step(
            name="pick_corner",
            prompt="Pick a corner clearing (1–4) for your Warlord and starting pieces.",
            endpoint="corner",
            payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
            faction=Faction.RATS,
        )

    def route_post(self, request, game_id: int, route: str):
        if route == "corner":
            return self.post_corner(request, game_id)
        return Response({"error": "Invalid route"}, status=status.HTTP_400_BAD_REQUEST)

    def post_corner(self, request, game_id: int):
        game = self.game(game_id)
        player = self.player(request, game_id)
        clearing_number = int(request.data["clearing_number"])
        try:
            clearing = Clearing.objects.get(game=game, clearing_number=clearing_number)
        except Clearing.DoesNotExist as e:
            raise ValidationError({"detail": str(e)})

        try:
            atomic_game_action(pick_corner)(player, clearing)
        except ValueError as e:
            raise ValidationError({"detail": str(e)})

        return self.generate_completed_step()

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        setup = RatsSimpleSetup.objects.get(player=player)
        if setup.step != RatsSimpleSetup.Steps.PICKING_CORNER:
            raise ValidationError({"detail": "Not in corner picking step"})


class RatsConfirmCompletedSetupView(GameActionView):
    action_name = "RATS_CONFIRM_COMPLETED_SETUP"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    first_step = {
        "faction": faction_string,
        "name": "confirm",
        "prompt": "Confirm completed setup",
        "endpoint": "confirm",
        "payload_details": [{"type": "confirm", "name": "confirm"}],
        "options": [{"value": True, "label": "Confirm"}],
    }

    def route_post(self, request, game_id: int, route: str):
        if route != "confirm":
            raise ValidationError("Invalid route")
        player = self.player(request, game_id)
        try:
            atomic_game_action(confirm_completed_setup, undoable=False)(player)
        except ValueError as e:
            raise ValidationError({"detail": str(e)})
        return self.generate_completed_step()

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        setup = RatsSimpleSetup.objects.get(player=player)
        if setup.step != RatsSimpleSetup.Steps.PENDING_CONFIRMATION:
            raise ValidationError({"detail": "Setup not complete"})
