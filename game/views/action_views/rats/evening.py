from rest_framework.exceptions import ValidationError

from game.decorators.transaction_decorator import atomic_game_action
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.game_models import Clearing, Faction, HandEntry
from game.models.rats.turn import RatsEvening
from game.queries.general import get_cards_matching_clearing, get_player_hand_size, validate_player_has_card_in_hand
from game.queries.rats.evening import get_incite_eligible_clearings
from game.queries.rats.turn import validate_phase, validate_step
from game.transactions.rats.evening import (
    discard_card,
    end_incite_step,
    incite,
)
from game.views.action_views.general import GameActionView


# ---------------------------------------------------------------------------
# Incite view
# ---------------------------------------------------------------------------


class RatsEveningInciteView(GameActionView):
    """INCITE step: optionally spend a card to place a Mob token.

    Two-step flow:
      GET  → show eligible clearings + Skip option
      POST clearing → show matching hand cards
      POST card     → call incite(player, clearing, card)  or  end_incite_step
    """

    action_name = "RATS_EVENING_INCITE"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        options = self._clearing_options(player)
        return self.generate_step(
            name="select_clearing",
            prompt="Incite: select a clearing to place a Mob token, or Skip.",
            endpoint="clearing",
            payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
            options=options,
        )

    def _clearing_options(self, player):
        options = [
            {
                "value": c.clearing_number,
                "label": f"Clearing {c.clearing_number} ({c.suit})",
            }
            for c in get_incite_eligible_clearings(player)
        ]
        options.append({"value": "", "label": "Skip"})
        return options

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "clearing":
                return self.post_clearing(request, game_id)
            case "card":
                return self.post_card(request, game_id)
        return super().route_post(request, game_id, route)

    def post_clearing(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        clearing_number = request.data.get("clearing_number", "")

        if clearing_number == "" or clearing_number is None:
            # Player chose Skip
            atomic_game_action(end_incite_step)(player)
            return self.generate_completed_step()

        try:
            cn = int(clearing_number)
        except (ValueError, TypeError):
            raise ValidationError({"detail": "Invalid clearing number"})

        clearing = Clearing.objects.get(game=game, clearing_number=cn)
        card_options = self._card_options(player, clearing)
        if not card_options:
            raise ValidationError({"detail": "No matching cards in hand for this clearing"})

        return self.generate_step(
            name="select_card",
            prompt=f"Select a card matching clearing {cn} ({clearing.suit}) to spend.",
            endpoint="card",
            payload_details=[{"type": "card", "name": "card_name"}],
            accumulated_payload={"clearing_number": cn},
            options=card_options,
        )

    def _card_options(self, player, clearing: Clearing):
        options = []
        for entry in get_cards_matching_clearing(player, clearing):
            try:
                card_enum = CardsEP[entry.card.card_type]
                options.append({"value": card_enum.name, "label": card_enum.value.title})
            except KeyError:
                pass
        return options

    def post_card(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        card_name = request.data.get("card_name", "")
        clearing_number = request.data.get("clearing_number")

        try:
            card_enum = CardsEP[card_name]
        except KeyError:
            raise ValidationError({"detail": f"Unknown card: {card_name}"})

        try:
            cn = int(clearing_number)
        except (ValueError, TypeError):
            raise ValidationError({"detail": "Invalid clearing number"})

        clearing = Clearing.objects.get(game=game, clearing_number=cn)
        atomic_game_action(incite)(player, clearing, card_enum)
        return self.generate_completed_step()

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        validate_phase(player, RatsEvening)
        validate_step(player, RatsEvening.Steps.INCITE)


# ---------------------------------------------------------------------------
# Discard view
# ---------------------------------------------------------------------------


class RatsEveningDiscardView(GameActionView):
    """DISCARD step: discard cards until hand has 5 or fewer.

    step_effect auto-advances past DISCARD when hand ≤ 5 on entry,
    so this view only fires when the player genuinely has excess cards.
    """

    action_name = "RATS_EVENING_DISCARD"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        hand_size = get_player_hand_size(player)
        need_to_discard = max(0, hand_size - 5)
        return self.generate_step(
            name="select_card",
            prompt=f"Discard {need_to_discard} card(s) to bring hand to 5.",
            endpoint="card",
            payload_details=[{"type": "card", "name": "card_name"}],
            options=self._card_options(player),
        )

    def _card_options(self, player):
        options = []
        for entry in HandEntry.objects.filter(player=player).select_related("card"):
            try:
                card_enum = CardsEP[entry.card.card_type]
                options.append({"value": card_enum.name, "label": card_enum.value.title})
            except KeyError:
                pass
        return options

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "card":
                return self.post_card(request, game_id)
        return super().route_post(request, game_id, route)

    def post_card(self, request, game_id: int):
        player = self.player(request, game_id)
        card_name = request.data.get("card_name", "")
        if not card_name:
            raise ValidationError({"detail": "No card selected"})

        try:
            card_enum = CardsEP[card_name]
        except KeyError:
            raise ValidationError({"detail": f"Unknown card: {card_name}"})

        card_entry = validate_player_has_card_in_hand(player, card_enum)
        atomic_game_action(discard_card)(player, card_entry)

        if get_player_hand_size(player) <= 5:
            return self.generate_completed_step()

        need_to_discard = get_player_hand_size(player) - 5
        return self.generate_step(
            name="select_card",
            prompt=f"Discard {need_to_discard} more card(s) to bring hand to 5.",
            endpoint="card",
            payload_details=[{"type": "card", "name": "card_name"}],
            options=self._card_options(player),
        )

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        validate_phase(player, RatsEvening)
        validate_step(player, RatsEvening.Steps.DISCARD)
