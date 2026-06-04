from game.decorators.transaction_decorator import atomic_game_action
from game.errors import UnavailableActionError
from game.models.enums import Suit
from game.models.game_models import Clearing, Faction
from game.models.rats.player import RatsPlayerState
from game.models.rats.turn import RatsBirdsong
from game.queries.rats.birdsong import get_mob_spread_targets, get_valid_moods
from game.queries.rats.turn import validate_phase, validate_step
from game.transactions.rats.birdsong import choose_mob_clearing, choose_mood
from ..general import GameActionView
from rest_framework.exceptions import ValidationError


class RatsBirdsongSpreadMobView(GameActionView):
    """Shown when roll_mob_die_and_spread produced multiple valid targets.

    step_effect auto-calls roll_mob_die_and_spread on entering SPREAD_MOB;
    if a choice is required it stores mob_die_suit and pauses here.
    """

    action_name = "RATS_BIRDSONG_SPREAD_MOB"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        birdsong = validate_phase(player, RatsBirdsong)
        assert isinstance(birdsong, RatsBirdsong)
        if birdsong.mob_die_suit is None:
            raise ValidationError({"detail": "No mob spread choice in progress"})
        suit = Suit(birdsong.mob_die_suit)
        targets = get_mob_spread_targets(player, suit)
        options = [
            {"value": c.clearing_number, "label": f"Clearing {c.clearing_number}"}
            for c in sorted(targets, key=lambda c: c.clearing_number)
        ]
        return self.generate_step(
            name="choose_mob_clearing",
            prompt=f"Choose a clearing to place your Mob token (rolled suit: {suit.label}).",
            endpoint="clearing",
            payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
            options=options,
        )

    def route_post(self, request, game_id: int, route: str):
        if route == "clearing":
            return self.post_clearing(request, game_id)
        return super().route_post(request, game_id, route)

    def post_clearing(self, request, game_id: int):
        game = self.game(game_id)
        player = self.player(request, game_id)
        clearing_number = int(request.data["clearing_number"])
        try:
            clearing = Clearing.objects.get(game=game, clearing_number=clearing_number)
        except Clearing.DoesNotExist as e:
            raise ValidationError({"detail": str(e)})
        atomic_game_action(choose_mob_clearing)(player, clearing)
        return self.generate_completed_step()

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        birdsong = validate_phase(player, RatsBirdsong)
        assert isinstance(birdsong, RatsBirdsong)
        validate_step(player, RatsBirdsong.Steps.SPREAD_MOB)
        if birdsong.mob_die_suit is None:
            raise UnavailableActionError("No mob spread choice in progress")


class RatsBirdsongChooseMoodView(GameActionView):
    """Shown at the CHOOSE_MOOD step so the player can select their mood."""

    action_name = "RATS_BIRDSONG_CHOOSE_MOOD"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        valid_moods = get_valid_moods(player)
        options = [
            {"value": m.value, "label": m.label}
            for m in valid_moods
        ]
        return self.generate_step(
            name="choose_mood",
            prompt="Choose your mood for this turn.",
            endpoint="mood",
            payload_details=[{"type": "mood", "name": "mood_type"}],
            options=options,
        )

    def route_post(self, request, game_id: int, route: str):
        if route == "mood":
            return self.post_mood(request, game_id)
        return super().route_post(request, game_id, route)

    def post_mood(self, request, game_id: int):
        player = self.player(request, game_id)
        mood_value = request.data["mood_type"]
        try:
            mood_type = RatsPlayerState.MoodType(mood_value)
        except ValueError as e:
            raise ValidationError({"detail": str(e)})
        atomic_game_action(choose_mood)(player, mood_type)
        return self.generate_completed_step()

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        validate_phase(player, RatsBirdsong)
        validate_step(player, RatsBirdsong.Steps.CHOOSE_MOOD)
