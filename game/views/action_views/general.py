from rest_framework import status
from rest_framework.views import APIView, Response
from rest_framework.exceptions import ValidationError, APIException
from drf_spectacular.utils import extend_schema

from game.queries.general import player_has_warriors_in_clearing
from game.models.game_models import Clearing, Faction, Game, Player
from game.errors import (
    UnavailableActionError,
    IllegalActionError,
    InternalGameError,
)

from game.serializers.general_serializers import (
    GameActionSerializer,
    GameActionStepSerializer,
    OptionSerializer,
    ValidationErrorSerializer,
)



class GameActionView(APIView):
    action_name = None
    first_step: dict = {}
    faction: Faction | None = None
    interceptors: list[dict] = []
    # Each entry: {"view": InterceptorActionView(), "condition": optional_callable}
    # condition override signature: (parent_view, request, game_id) -> bool

    @extend_schema(responses={200: GameActionStepSerializer})
    def get(self, request, *args, **kwargs):
        """Return initial step data."""
        serializer = GameActionStepSerializer(
            self.first_step,
        )
        return Response(serializer.data)

    @extend_schema(
        responses={200: GameActionStepSerializer, 400: ValidationErrorSerializer}
    )
    def post(self, request, game_id: int, route: str, *args, **kwargs):
        try:
            self.validate_player(request, game_id, route, *args, **kwargs)
            self.validate_timing(request, game_id, route, *args, **kwargs)
            for config in self.__class__.interceptors:
                if route in config["view"].interceptor_routes:
                    return self._handle_interceptor_post(config["view"], request, game_id, route)
            return self.route_post(request, game_id, route, *args, **kwargs)
        except (UnavailableActionError, IllegalActionError) as e:
            raise ValidationError({"detail": str(e)})
        except InternalGameError as e:
            raise APIException(detail=str(e))

    def game(self, game_id: int):
        """Return the game. helper method. raises if game not found"""
        try:
            return Game.objects.get(pk=game_id)
        except Game.DoesNotExist:
            raise ValidationError("Game not found")

    def player(self, request, game_id: int):
        """Return the player. helper method. raises if player not found"""
        if self.faction is None:
            return self.player_by_request(request, game_id)
        else:
            return self.player_by_faction(request, game_id)

    def player_by_request(self, request, game_id: int):
        """Return the player according to the request token. helper method. raises if player not found"""
        try:
            return Player.objects.get(game=game_id, user=request.user)
        except Player.DoesNotExist:
            raise ValidationError("Player not found")

    def player_by_faction(self, request, game_id: int):
        """Return the player according to the faction. helper method. raises if player not found"""
        try:
            return Player.objects.get(game=game_id, faction=self.faction)
        except Player.DoesNotExist:
            raise ValidationError("Player not found")

    def validate_player(self, request, game_id: int, route: str, *args, **kwargs):
        """validate that player making a post request is the correct faction"""
        player_requesting = self.player_by_request(request, game_id)

        if self.faction is not None:
            player_of_faction_in_game = self.player_by_faction(request, game_id)
            if player_requesting != player_of_faction_in_game:

                raise ValidationError(
                    "Player is not the correct faction for this action"
                )
        else:
            pass

    def validate_timing(self, request, game_id: int, route: str, *args, **kwargs):
        """raises if not this player's turn or correct step. called in post.
        should be implemented by any subclass with timing dependency"""
        pass

    def route_post(
        self, request, game_id: int, route: str, *args, **kwargs
    ) -> Response:
        """called in post. subclasses handle their known routes and fall through
        to super() for anything unrecognised — this returns 404.
        """
        return Response({"error": f"Unknown route: {route}"}, status=status.HTTP_404_NOT_FOUND)

    # ── Interceptor machinery ────────────────────────────────────────────────

    def _resolve_condition(self, config: dict, request, game_id: int) -> bool:
        if "condition" in config:
            return config["condition"](self, request, game_id)
        return config["view"].condition(self, request, game_id)

    def _handle_interceptor_post(self, interceptor_view, request, game_id: int, route: str) -> Response:
        response = interceptor_view.route_post(request, game_id, route)
        if getattr(response, "data", {}).get("name") == "_interceptor_complete":
            return self._resume_after_interceptor(request, game_id)
        return response

    def _resume_after_interceptor(self, request, game_id: int) -> Response:
        deferred_step = request.data.get("_deferred_step")

        if deferred_step:
            # Mid-flow: return the deferred step, merging all non-internal request fields in
            step = dict(deferred_step)
            acc = dict(step.get("accumulated_payload") or {})
            for k, v in request.data.items():
                if not k.startswith("_"):
                    acc[k] = v
            step["accumulated_payload"] = acc
            return Response(GameActionStepSerializer(step).data)

        # Terminal: dispatch to the execution handler named when generate_completing_step was called
        execution_route = request.data["_execution_route"]
        return self.route_post(request, game_id, execution_route)

    # ── Step generation ──────────────────────────────────────────────────────

    def generate_step(
        self,
        name,
        prompt,
        endpoint,
        payload_details,
        accumulated_payload: dict | None = None,
        faction: Faction | None = None,
        options: list[OptionSerializer] | list[dict] | None = None,
        request=None,
        game_id: int | None = None,
    ):
        if faction is None:
            faction = self.faction.label if self.faction else ""
        step = {
            "faction": self.faction.label if self.faction is not None else "",
            "name": name,
            "prompt": prompt,
            "endpoint": endpoint,
            "payload_details": payload_details,
            "accumulated_payload": accumulated_payload,
            "options": options,
        }
        if request is not None:
            for config in self.__class__.interceptors:
                if self._resolve_condition(config, request, game_id):
                    interceptor = config["view"]
                    enriched = {**(accumulated_payload or {}), "_deferred_step": step}
                    entry = interceptor.entry_step(request, game_id, enriched)
                    entry["accumulated_payload"] = enriched
                    return Response(GameActionStepSerializer(entry).data)
        serializer = GameActionStepSerializer(step)
        return Response(serializer.data)

    def generate_completing_step(
        self,
        accumulated_payload: dict,
        request,
        game_id: int,
        execution_route: str,
    ) -> Response:
        """For terminal steps: check interceptors, then either defer to them or execute directly.

        execution_route names the route_post handler to invoke on execution (e.g. "execute_move").
        If an interceptor condition fires, returns the interceptor's entry step with
        _execution_route embedded in accumulated_payload — absence of _deferred_step is the
        terminal signal; _execution_route tells _resume_after_interceptor which handler to call.
        If no interceptor fires, calls route_post(request, game_id, execution_route) directly.
        """
        for config in self.__class__.interceptors:
            if self._resolve_condition(config, request, game_id):
                interceptor = config["view"]
                acc = dict(accumulated_payload)
                acc["_execution_route"] = execution_route
                entry = interceptor.entry_step(request, game_id, acc)
                entry["accumulated_payload"] = acc
                return Response(GameActionStepSerializer(entry).data)
        return self.route_post(request, game_id, execution_route)

    def generate_completed_step(self):
        step = {"name": "completed"}
        serializer = GameActionStepSerializer(step)
        return Response(serializer.data)

    def generate_redirect_step(self, new_base_route: str):
        step = {"name": "redirect", "new_base_endpoint": new_base_route}
        serializer = GameActionStepSerializer(step)
        return Response(serializer.data)


class SubGameActionView(GameActionView):
    """Base class for sub-action views that delegate to parent validators."""
    subroute: str = ""
    parent_view: type[GameActionView] | None = None

    def validate_player(self, request, game_id, route, *args, **kwargs):
        """Inherit player validation from parent view if set."""
        if self.parent_view is not None:
            self.parent_view().validate_player(request, game_id, route, *args, **kwargs)
        else:
            super().validate_player(request, game_id, route, *args, **kwargs)

    def validate_timing(self, request, game_id, route, *args, **kwargs):
        """Inherit timing validation from parent view if set."""
        if self.parent_view is not None:
            self.parent_view().validate_timing(request, game_id, route, *args, **kwargs)
        else:
            super().validate_timing(request, game_id, route, *args, **kwargs)


class InterceptorActionView(GameActionView):
    """Base class for a self-contained sub-flow that can be injected into any parent view.

    The parent view declares instances of InterceptorActionView in its `interceptors` list.
    When an interceptor's condition fires, the parent routes subsequent POSTs to the
    interceptor's route_post until the interceptor calls pass_back(), at which point the
    parent resumes its own flow (either returning a deferred step or executing and completing).

    Subclasses must define:
      - interceptor_name: str          — unique identifier
      - interceptor_routes: list[str]  — routes this interceptor handles (e.g. ["warlord"])
      - condition()                    — when this interceptor should activate
      - entry_step()                   — the first step data dict shown to the player
      - route_post() / post_<route>()  — route handlers (call pass_back() when done)
    """

    interceptor_name: str = ""
    interceptor_routes: list[str] = []

    def condition(self, view: "GameActionView", request, game_id: int) -> bool:
        """Override to define when this interceptor should activate."""
        return False

    def entry_step(self, request, game_id: int, context_payload: dict) -> dict:
        """Return the raw first-step dict (no accumulated_payload — parent sets that).

        context_payload is the accumulated_payload at the moment of interception.
        """
        raise NotImplementedError

    def pass_back(self, request) -> Response:
        """Call from the interceptor's last handler to return flow to the parent.

        All collected data is already in request.data — the parent reads it from there.
        """
        return Response({"name": "_interceptor_complete"})


class MovePiecesView(GameActionView):
    action_name = "MOVE_PIECES"

    steps = [
        {
            "prompt": "Select source clearing",
            "endpoint": "source",
            "payload_type": "clearing",
        },
        {
            "prompt": "Select destination",
            "endpoint": "destination",
            "payload_type": "clearing",
        },
        {"prompt": "Choose number", "endpoint": "count", "payload_type": "number"},
        {"prompt": "Confirm move", "endpoint": "confirm", "payload_type": "confirm"},
    ]

    def post_source(self, request, game_id: int):
        game = self.game(request)
        player = Player.objects.get(game=game, user=request.user)
        clearing_number = request.data["clearing_number"]
        clearing = Clearing.objects.get(game=game, clearing_number=clearing_number)
        if not player_has_warriors_in_clearing(player, clearing):
            raise ValidationError("You do not have warriors in that clearing")
        return Response({"clearing": clearing})

    def post_destination(self, request, *args, **kwargs): ...

    def post_count(self, request, *args, **kwargs): ...
    def post_confirm(self, request, *args, **kwargs): ...
