from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from game.decorators.transaction_decorator import atomic_game_action
from game.errors import IllegalActionError, UnavailableActionError
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.game_models import Clearing, Faction
from game.models.rats.buildings import Stronghold
from game.models.rats.turn import RatsDaylight, RatsAdvance
from game.queries.general import (
    get_craftable_cards_for_player,
    validate_enemy_pieces_in_clearing,
    validate_has_legal_moves,
    validate_legal_move,
    validate_player_has_card_in_hand,
)
from game.queries.rats.birdsong import get_command_value, get_prowess_value
from game.queries.rats.pieces import get_warlord
from game.queries.rats.daylight import (
    get_craftable_clearings,
    get_unused_stronghold_in_clearing,
    validate_crafting_pieces_satisfy_requirements,
)
from game.queries.rats.turn import validate_phase, validate_step
from game.transactions.rats.daylight import (
    advance_battle,
    advance_battle_skip,
    advance_move,
    advance_move_skip,
    advance_relentless_skip,
    craft_card,
    end_advance,
    end_command,
    end_crafting,
    use_command,
)
from game.views.action_views.general import GameActionView, SubGameActionView
from game.views.action_views.rats.interceptors import WarlordMoveInterceptorView


# ---------------------------------------------------------------------------
# Craft view
# ---------------------------------------------------------------------------


class RatsDaylightCraftView(GameActionView):
    """CRAFT step: select a card and use Strongholds to craft it."""

    action_name = "RATS_DAYLIGHT_CRAFT"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        return Response(
            self.generate_step(
                name="select_card",
                prompt="Select a card to craft, or Done to end crafting.",
                endpoint="card",
                payload_details=[{"type": "card", "name": "card_to_craft"}],
                options=self._card_options(player),
            ).data
        )

    def _card_options(self, player):
        options = []
        for card_enum in get_craftable_cards_for_player(player):
            options.append({"value": card_enum.name, "label": card_enum.value.title})
        options.append({"value": "", "label": "Done Crafting"})
        return options

    def _clearing_options(self, player):
        return [
            {
                "value": c.clearing_number,
                "label": f"Clearing {c.clearing_number} ({c.suit})",
            }
            for c in get_craftable_clearings(player)
        ]

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "card":
                return self.post_card(request, game_id)
            case "hoard_choice":
                return self.post_hoard_choice(request, game_id)
            case "clearing":
                return self.post_clearing(request, game_id)
        return super().route_post(request, game_id, route)

    def post_card(self, request, game_id: int):
        player = self.player(request, game_id)
        card_name = request.data.get("card_to_craft", "")

        if card_name == "":
            atomic_game_action(end_crafting)(player)
            return self.generate_completed_step()

        try:
            card_enum = CardsEP[card_name]
        except KeyError:
            raise ValidationError({"detail": f"Unknown card: {card_name}"})

        # Contempt for Trade: if this card yields an item, ask hoard or score first.
        if card_enum.value.item is not None:
            return self.generate_step(
                name="hoard_choice",
                prompt=(
                    f"{card_enum.value.title}: Add to hoard (0 VP) "
                    f"or remove permanently to score {card_enum.value.crafted_points} VP?"
                ),
                endpoint="hoard_choice",
                payload_details=[{"type": "choice", "name": "add_to_hoard"}],
                accumulated_payload={"card_to_craft": card_name},
                options=[
                    {"value": True, "label": "Add to Hoard (0 VP)"},
                    {"value": False, "label": f"Score {card_enum.value.crafted_points} VP (remove permanently)"},
                ],
            )

        cost = card_enum.value.cost
        cost_labels = [c.label for c in cost]
        return self.generate_step(
            name="select_clearing",
            prompt=f"Select clearing for {card_enum.value.title} (cost: {cost_labels}).",
            endpoint="clearing",
            payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
            accumulated_payload={"card_to_craft": card_name, "clearing_numbers": [], "add_to_hoard": False},
            options=self._clearing_options(player),
        )

    def post_hoard_choice(self, request, game_id: int):
        player = self.player(request, game_id)
        card_name = request.data.get("card_to_craft", "")
        add_to_hoard = bool(request.data.get("add_to_hoard", False))

        if not card_name:
            raise ValidationError({"detail": "No card selected"})

        try:
            card_enum = CardsEP[card_name]
        except KeyError:
            raise ValidationError({"detail": f"Unknown card: {card_name}"})

        cost = card_enum.value.cost
        cost_labels = [c.label for c in cost]
        return self.generate_step(
            name="select_clearing",
            prompt=f"Select clearing for {card_enum.value.title} (cost: {cost_labels}).",
            endpoint="clearing",
            payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
            accumulated_payload={
                "card_to_craft": card_name,
                "clearing_numbers": [],
                "add_to_hoard": add_to_hoard,
            },
            options=self._clearing_options(player),
        )

    def post_clearing(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        card_name = request.data.get("card_to_craft", "")
        clearing_numbers_so_far = request.data.get("clearing_numbers", [])
        new_clearing_number = request.data.get("clearing_number", "")
        add_to_hoard = request.data.get("add_to_hoard", False)

        if not card_name:
            raise ValidationError({"detail": "No card selected"})

        try:
            card_enum = CardsEP[card_name]
        except KeyError:
            raise ValidationError({"detail": f"Unknown card: {card_name}"})

        cost = card_enum.value.cost
        cost_labels = [c.label for c in cost]

        try:
            clearing_numbers = list(clearing_numbers_so_far) + [int(new_clearing_number)]
        except (ValueError, TypeError):
            raise ValidationError({"detail": "Invalid clearing number"})

        # Resolve strongholds from the selected clearings
        strongholds = []
        for cn in clearing_numbers:
            try:
                clearing = Clearing.objects.get(game=game, clearing_number=cn)
                sh = get_unused_stronghold_in_clearing(player, clearing)
                strongholds.append(sh)
            except (Clearing.DoesNotExist, IllegalActionError) as e:
                raise ValidationError({"detail": str(e)})

        # If we have gathered enough, try to craft
        if len(strongholds) == len(cost):
            atomic_game_action(craft_card)(player, card_enum, strongholds, add_to_hoard=bool(add_to_hoard))
            return self.generate_completed_step()

        # Still gathering — ask for the next clearing
        selected_suits = [
            s.building_slot.clearing.get_suit_display() for s in strongholds
        ]
        return self.generate_step(
            name="select_clearing",
            prompt=(
                f"Select more clearing(s). Need: {cost_labels}. "
                f"Selected so far: {selected_suits}."
            ),
            endpoint="clearing",
            payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
            accumulated_payload={
                "card_to_craft": card_name,
                "clearing_numbers": clearing_numbers,
                "add_to_hoard": add_to_hoard,
            },
            options=self._clearing_options(player),
        )

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        validate_phase(player, RatsDaylight)
        validate_step(player, RatsDaylight.Steps.CRAFT)


# ---------------------------------------------------------------------------
# Command view + sub-views
# ---------------------------------------------------------------------------


class RatsDaylightCommandView(GameActionView):
    """COMMAND step: choose Move / Battle / Build or end the command phase."""

    action_name = "RATS_DAYLIGHT_COMMAND"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    _base_options = [
        {"value": "move", "label": "Move", "info": "Move warriors from the Warlord's clearing."},
        {"value": "battle", "label": "Battle", "info": "Initiate a battle in any clearing."},
        {"value": "build", "label": "Build", "info": "Spend a card to place a Stronghold."},
        {"value": "", "label": "Done", "info": "Finish command phase."},
    ]

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        daylight = validate_phase(player, RatsDaylight)
        commands_remaining = get_command_value(player) - daylight.commands_used
        return self.generate_step(
            name="select_action",
            prompt=f"Choose a command action. ({commands_remaining} remaining)",
            endpoint="select",
            payload_details=[{"type": "action_type", "name": "action"}],
            options=self._base_options,
        )

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "select":
                return self.post_select(request, game_id)
        return super().route_post(request, game_id, route)

    def post_select(self, request, game_id: int):
        player = self.player(request, game_id)
        action = request.data.get("action", "")

        if action == "":
            atomic_game_action(end_command)(player)
            return self.generate_completed_step()

        match action:
            case "move":
                return self.generate_redirect_step(reverse("rats-daylight-command-move"))
            case "battle":
                return self.generate_redirect_step(reverse("rats-daylight-command-battle"))
            case "build":
                return self.generate_redirect_step(reverse("rats-daylight-command-build"))
            case _:
                raise ValidationError({"detail": "Invalid action"})

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        validate_phase(player, RatsDaylight)
        validate_step(player, RatsDaylight.Steps.COMMAND)


class RatsCommandMoveView(SubGameActionView):
    """Command Move sub-action: origin → destination → count.

    If the Warlord is in the origin clearing when count is submitted, the
    WarlordMoveInterceptorView fires automatically to ask whether to move him.
    """

    subroute = "move"
    parent_view = RatsDaylightCommandView
    faction = Faction.RATS
    faction_string = Faction.RATS.label
    interceptors = [{"view": WarlordMoveInterceptorView()}]

    first_step = {
        "faction": Faction.RATS.label,
        "name": "move_origin",
        "prompt": "Select origin clearing.",
        "endpoint": "origin",
        "payload_details": [{"type": "clearing_number", "name": "clearing_number"}],
    }

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "origin":
                return self.post_origin(request, game_id)
            case "destination":
                return self.post_destination(request, game_id)
            case "count":
                return self.post_count(request, game_id)
            case "execute_move":
                return self.post_execute_move(request, game_id)
        return super().route_post(request, game_id, route)

    def post_origin(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        clearing_number = int(request.data["clearing_number"])
        origin = Clearing.objects.get(game=game, clearing_number=clearing_number)
        validate_has_legal_moves(player, origin)
        return self.generate_step(
            name="move_destination",
            prompt="Select destination clearing.",
            endpoint="destination",
            payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
            accumulated_payload={"origin_clearing": clearing_number},
        )

    def post_destination(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        origin_num = request.data["origin_clearing"]
        dest_num = int(request.data["clearing_number"])
        origin = Clearing.objects.get(game=game, clearing_number=origin_num)
        dest = Clearing.objects.get(game=game, clearing_number=dest_num)
        validate_legal_move(player, origin, dest)
        return self.generate_step(
            name="move_count",
            prompt="How many warriors to move?",
            endpoint="count",
            payload_details=[{"type": "number", "name": "count"}],
            accumulated_payload={
                "origin_clearing": origin_num,
                "destination_clearing": dest_num,
            },
        )

    def post_count(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        origin = Clearing.objects.get(game=game, clearing_number=request.data["origin_clearing"])
        dest = Clearing.objects.get(game=game, clearing_number=request.data["destination_clearing"])
        count = int(request.data["count"])
        validate_legal_move(player, origin, dest)
        return self.generate_completing_step(
            accumulated_payload={
                "origin_clearing": origin.clearing_number,
                "destination_clearing": dest.clearing_number,
                "count": count,
            },
            request=request,
            game_id=game_id,
            execution_route="execute_move",
        )

    def post_execute_move(self, request, game_id: int):
        player = self.player(request, game_id)
        game = player.game
        origin = Clearing.objects.get(game=game, clearing_number=int(request.data["origin_clearing"]))
        dest = Clearing.objects.get(game=game, clearing_number=int(request.data["destination_clearing"]))
        count = int(request.data["count"])
        move_warlord = bool(request.data.get("move_warlord", False))
        atomic_game_action(use_command)(player, "move", origin, dest, count, move_warlord=move_warlord)
        return self.generate_completed_step()


class RatsCommandBattleView(SubGameActionView):
    """Command Battle sub-action: clearing → defender faction."""

    subroute = "battle"
    parent_view = RatsDaylightCommandView
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    first_step = {
        "faction": Faction.RATS.label,
        "name": "battle_clearing",
        "prompt": "Select clearing to battle in.",
        "endpoint": "clearing",
        "payload_details": [{"type": "clearing_number", "name": "clearing_number"}],
    }

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "clearing":
                return self.post_clearing(request, game_id)
            case "faction":
                return self.post_faction(request, game_id)
        return super().route_post(request, game_id, route)

    def post_clearing(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        clearing_number = int(request.data["clearing_number"])
        clearing = Clearing.objects.get(game=game, clearing_number=clearing_number)
        enemy_players = validate_enemy_pieces_in_clearing(player, clearing)
        options = [
            {"value": Faction(p.faction).value, "label": Faction(p.faction).label}
            for p in enemy_players
        ]
        return self.generate_step(
            name="battle_faction",
            prompt="Select faction to battle.",
            endpoint="faction",
            payload_details=[{"type": "faction", "name": "defender_faction"}],
            accumulated_payload={"clearing_number": clearing_number},
            options=options,
        )

    def post_faction(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        clearing_number = request.data["clearing_number"]
        defender_faction = Faction(request.data["defender_faction"])
        clearing = Clearing.objects.get(game=game, clearing_number=clearing_number)
        atomic_game_action(use_command)(player, "battle", defender_faction, clearing)
        return self.generate_completed_step()


class RatsCommandBuildView(SubGameActionView):
    """Command Build sub-action: card → clearing."""

    subroute = "build"
    parent_view = RatsDaylightCommandView
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        options = self._card_options(player)
        return self.generate_step(
            name="build_card",
            prompt="Select card to spend for the Stronghold.",
            endpoint="card",
            payload_details=[{"type": "card", "name": "card_name"}],
            options=options,
        )

    def _card_options(self, player):
        from game.models.game_models import HandEntry
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
            case "clearing":
                return self.post_clearing(request, game_id)
        return super().route_post(request, game_id, route)

    def post_card(self, request, game_id: int):
        player = self.player(request, game_id)
        card_name = request.data.get("card_name", "")
        try:
            card_enum = CardsEP[card_name]
        except KeyError:
            raise ValidationError({"detail": f"Unknown card: {card_name}"})
        validate_player_has_card_in_hand(player, card_enum)
        return self.generate_step(
            name="build_clearing",
            prompt="Select clearing to place the Stronghold.",
            endpoint="clearing",
            payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
            accumulated_payload={"card_name": card_name},
        )

    def post_clearing(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        card_name = request.data["card_name"]
        clearing_number = int(request.data["clearing_number"])
        try:
            card_enum = CardsEP[card_name]
        except KeyError:
            raise ValidationError({"detail": f"Unknown card: {card_name}"})
        clearing = Clearing.objects.get(game=game, clearing_number=clearing_number)
        atomic_game_action(use_command)(player, "build", card_enum, clearing)
        return self.generate_completed_step()


# ---------------------------------------------------------------------------
# Advance view + sub-views
# ---------------------------------------------------------------------------


class RatsDaylightAdvanceView(GameActionView):
    """ADVANCE step: each cycle the Warlord may move then battle.

    Shown at the start of every advance cycle (MOVE sub-step), after a move
    (BATTLE sub-step), and for the optional Relentless bonus cycle
    (RELENTLESS_BONUS sub-step).
    """

    action_name = "RATS_DAYLIGHT_ADVANCE"
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        daylight = validate_phase(player, RatsDaylight)
        assert isinstance(daylight, RatsDaylight)
        advance = daylight.advance
        if advance is None:
            raise ValidationError({"detail": "Advance tracker not initialised"})
        prowess_used = daylight.prowess_used
        prowess_total = get_prowess_value(player)
        cycles_left = prowess_total - prowess_used

        match advance.current_step:
            case RatsAdvance.AdvanceStep.MOVE:
                options = [
                    {"value": "move", "label": "Move Warlord"},
                    {"value": "skip_move", "label": "Skip Move"},
                    {"value": "end", "label": "End Advance"},
                ]
                prompt = f"Advance — Move the Warlord or skip. ({cycles_left} cycle(s) remaining)"
            case RatsAdvance.AdvanceStep.BATTLE:
                options = [
                    {"value": "battle", "label": "Battle"},
                    {"value": "skip_battle", "label": "Skip Battle"},
                    {"value": "end", "label": "End Advance"},
                ]
                prompt = f"Advance — Battle in the Warlord's clearing or skip. ({cycles_left} cycle(s) remaining)"
            case RatsAdvance.AdvanceStep.RELENTLESS_BONUS:
                options = [
                    {"value": "move", "label": "Move (Relentless Bonus)"},
                    {"value": "battle", "label": "Battle (Relentless Bonus)"},
                    {"value": "skip_relentless", "label": "Skip"},
                ]
                prompt = "Relentless Bonus: take a free move or battle, then the cycle ends."
            case _:
                raise ValidationError({"detail": "Unexpected advance sub-step"})

        return self.generate_step(
            name="select_action",
            prompt=prompt,
            endpoint="select",
            payload_details=[{"type": "action_type", "name": "action"}],
            options=options,
        )

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "select":
                return self.post_select(request, game_id)
        return super().route_post(request, game_id, route)

    def post_select(self, request, game_id: int):
        player = self.player(request, game_id)
        action = request.data.get("action", "")

        match action:
            case "move":
                return self.generate_redirect_step(reverse("rats-daylight-advance-move"))
            case "skip_move":
                atomic_game_action(advance_move_skip)(player)
                return self.generate_completed_step()
            case "battle":
                return self.generate_redirect_step(reverse("rats-daylight-advance-battle"))
            case "skip_battle":
                atomic_game_action(advance_battle_skip)(player)
                return self.generate_completed_step()
            case "skip_relentless":
                atomic_game_action(advance_relentless_skip)(player)
                return self.generate_completed_step()
            case "end":
                atomic_game_action(end_advance)(player)
                return self.generate_completed_step()
            case _:
                raise ValidationError({"detail": "Invalid action"})

    def validate_timing(self, request, game_id: int, *args, **kwargs):
        player = self.player(request, game_id)
        validate_phase(player, RatsDaylight)
        validate_step(player, RatsDaylight.Steps.ADVANCE)


class RatsAdvanceMoveView(SubGameActionView):
    """Advance Move sub-action: pick destination clearing, then warrior count.

    Origin is always the Warlord's current clearing.
    count=0 is valid (Warlord moves alone).
    """

    subroute = "move"
    parent_view = RatsDaylightAdvanceView
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        warlord = get_warlord(player)
        if warlord.clearing is None:
            raise ValidationError({"detail": "Warlord is not on the map"})
        warlord_clearing_num = warlord.clearing.clearing_number
        return self.generate_step(
            name="advance_destination",
            prompt=f"Select destination clearing (Warlord moves from clearing {warlord_clearing_num}).",
            endpoint="destination",
            payload_details=[{"type": "clearing_number", "name": "clearing_number"}],
        )

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "destination":
                return self.post_destination(request, game_id)
            case "count":
                return self.post_count(request, game_id)
        return super().route_post(request, game_id, route)

    def post_destination(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        dest_num = int(request.data["clearing_number"])
        dest = Clearing.objects.get(game=game, clearing_number=dest_num)
        warlord = get_warlord(player)
        if warlord.clearing is None:
            raise ValidationError({"detail": "Warlord is not on the map"})
        # Pre-validate adjacency before asking for count
        validate_legal_move(player, warlord.clearing, dest)
        return self.generate_step(
            name="advance_count",
            prompt=f"How many warriors to bring to clearing {dest_num}? (0 = Warlord alone)",
            endpoint="count",
            payload_details=[{"type": "number", "name": "count"}],
            accumulated_payload={"destination_clearing": dest_num},
        )

    def post_count(self, request, game_id: int):
        player = self.player(request, game_id)
        game = self.game(game_id)
        dest_num = request.data["destination_clearing"]
        count = int(request.data["count"])
        dest = Clearing.objects.get(game=game, clearing_number=dest_num)
        atomic_game_action(advance_move)(player, dest, count)
        return self.generate_completed_step()


class RatsAdvanceBattleView(SubGameActionView):
    """Advance Battle sub-action: pick defender faction in Warlord's clearing."""

    subroute = "battle"
    parent_view = RatsDaylightAdvanceView
    faction = Faction.RATS
    faction_string = Faction.RATS.label

    def get(self, request, *args, **kwargs):
        game_id = int(request.query_params.get("game_id"))
        player = self.player(request, game_id)
        warlord = get_warlord(player)
        if warlord.clearing is None:
            raise ValidationError({"detail": "Warlord is not on the map"})
        enemy_players = validate_enemy_pieces_in_clearing(player, warlord.clearing)
        options = [
            {"value": Faction(p.faction).value, "label": Faction(p.faction).label}
            for p in enemy_players
        ]
        return self.generate_step(
            name="advance_battle_faction",
            prompt=f"Select faction to battle in clearing {warlord.clearing.clearing_number}.",
            endpoint="faction",
            payload_details=[{"type": "faction", "name": "defender_faction"}],
            options=options,
        )

    def route_post(self, request, game_id: int, route: str):
        match route:
            case "faction":
                return self.post_faction(request, game_id)
        return super().route_post(request, game_id, route)

    def post_faction(self, request, game_id: int):
        player = self.player(request, game_id)
        defender_faction = Faction(request.data["defender_faction"])
        atomic_game_action(advance_battle)(player, defender_faction)
        return self.generate_completed_step()
