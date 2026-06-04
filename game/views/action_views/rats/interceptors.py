"""Interceptor views for Rats faction action flows."""

from rest_framework.exceptions import ValidationError

from game.models.game_models import Faction
from game.queries.rats.pieces import get_warlord
from game.views.action_views.general import InterceptorActionView


class WarlordMoveInterceptorView(InterceptorActionView):
    """Asks the Rats player whether to move the Warlord when he is in the origin clearing.

    Fires from any view that calls generate_completing_step (or generate_step) while
    the Rats Warlord is present in the origin clearing. Collects a True/False answer
    via the "warlord" route and returns flow to the parent, which merges move_warlord
    into the execution payload via _execute().
    """

    interceptor_name = "warlord_move"
    interceptor_routes = ["warlord"]
    faction = Faction.RATS

    def condition(self, view, request, game_id: int) -> bool:
        player = view.player(request, game_id)
        if player.faction != Faction.RATS:
            return False
        # Support both key names used across different action views
        origin_num = request.data.get("origin_clearing") or request.data.get("origin_number")
        if not origin_num:
            return False
        warlord = get_warlord(player)
        return (
            warlord.clearing is not None
            and warlord.clearing.clearing_number == int(origin_num)
        )

    def entry_step(self, request, game_id: int, context_payload: dict) -> dict:
        count = request.data.get("count", "?")
        return {
            "faction": Faction.RATS.label,
            "name": "move_warlord_choice",
            "prompt": f"Move the Warlord? (counts as 1 of your {count})",
            "endpoint": "warlord",
            "payload_details": [{"type": "option", "name": "move_warlord"}],
            "options": [
                {"value": True,  "label": "Yes — move Warlord with the group"},
                {"value": False, "label": "No — leave Warlord behind"},
            ],
        }

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "warlord":
                return self.post_warlord(request, game_id)
            case _:
                raise ValidationError({"detail": f"Unknown route: {route}"})

    def post_warlord(self, request, game_id: int):
        # move_warlord arrives as True/False from the client — no conversion needed.
        # All accumulated payload fields (origin_clearing, count, etc.) are also in
        # request.data and will be read by the parent's _resume_after_interceptor.
        return self.pass_back(request)
