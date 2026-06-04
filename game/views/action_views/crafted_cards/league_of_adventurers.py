from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from game.views.action_views.general import GameActionView
from game.views.action_views.rats.interceptors import WarlordMoveInterceptorView
from game.models.game_models import (
    CraftedItemEntry,
    Faction,
    Player,
    Clearing,
    Warrior,
    CraftedCardEntry,
)
from game.transactions.crafted_cards.league_of_adventurers import (
    use_league_of_adventurers,
)
from game.queries.general import (
    warrior_count_in_clearing,
    player_has_warriors_in_clearing,
    player_has_pieces_in_clearing,
    determine_clearing_rule,
    get_enemy_factions_in_clearing,
)
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.decorators.transaction_decorator import atomic_game_action


class LeagueOfAdventurersView(GameActionView):
    interceptors = [{"view": WarlordMoveInterceptorView()}]
    def get(self, request, *args, **kwargs):
        game_id = kwargs.get("game_id") or request.query_params.get("game_id")
        player = self.player(request, game_id)

        # Step 1: Pick an item to exhaust
        items = CraftedItemEntry.objects.filter(
            player=player, exhausted=False
        ).select_related("item")
        options = [
            {"value": str(entry.id), "label": entry.item.get_item_type_display()}
            for entry in items
        ]

        if not options:
            raise ValidationError({"detail": "No items available to exhaust."})

        return self.generate_step(
            name="pick_item",
            prompt="Pick an item to exhaust for League of Adventurers",
            endpoint="pick_item",
            payload_details=[{"type": "select", "name": "item_id"}],
            options=options,
            faction=Faction(player.faction),
        )

    def route_post(self, request, game_id: int, route: str, *args, **kwargs):
        match route:
            case "pick_item":
                return self.post_pick_item(request, game_id)
            case "pick_action":
                return self.post_pick_action(request, game_id)
            case "pick_origin":
                return self.post_pick_origin(request, game_id)
            case "pick_destination":
                return self.post_pick_destination(request, game_id)
            case "pick_count":
                return self.post_pick_count(request, game_id)
            case "execute_move":
                return self.post_execute_move(request, game_id)
            case "pick_clearing":
                return self.post_pick_clearing(request, game_id)
            case "pick_opponent":
                return self.post_pick_opponent(request, game_id)
            case _:
                raise ValidationError("Invalid route")

    def post_pick_item(self, request, game_id):
        player = self.player(request, game_id)
        item_id = request.data["item_id"]

        # Verify item exists and belongs to player
        get_object_or_404(CraftedItemEntry, pk=item_id, player=player, exhausted=False)

        options = [
            {"value": "move", "label": "Move", "info": "Perform a Move action."},
            {"value": "battle", "label": "Battle", "info": "Perform a Battle action."},
        ]

        return self.generate_step(
            name="pick_action",
            prompt="Choose an action to perform",
            endpoint="pick_action",
            payload_details=[{"type": "choice", "name": "action_type"}],
            accumulated_payload={"item_id": item_id},
            options=options,
            faction=Faction(player.faction),
        )

    def post_pick_action(self, request, game_id):
        player = self.player(request, game_id)
        item_id = request.data["item_id"]
        action_type = request.data["action_type"]

        if action_type == "move":
            # Get clearings where player has warriors
            clearings = Clearing.objects.filter(game_id=game_id)
            options = []
            for c in clearings:
                if player_has_warriors_in_clearing(player, c):
                    options.append(
                        {
                            "value": str(c.clearing_number),
                            "label": f"Clearing {c.clearing_number} ({c.get_suit_display()})",
                        }
                    )

            return self.generate_step(
                name="pick_origin",
                prompt="Select origin clearing",
                endpoint="pick_origin",
                payload_details=[{"type": "clearing_number", "name": "origin_number"}],
                accumulated_payload={"item_id": item_id, "action_type": action_type},
                options=options,
                faction=Faction(player.faction),
            )
        else:
            # Battle
            clearings = Clearing.objects.filter(game_id=game_id)
            options = []
            for c in clearings:
                if player_has_warriors_in_clearing(player, c):
                    enemies = get_enemy_factions_in_clearing(player, c)
                    if enemies:
                        options.append(
                            {
                                "value": str(c.clearing_number),
                                "label": f"Clearing {c.clearing_number} ({c.get_suit_display()})",
                            }
                        )

            return self.generate_step(
                name="pick_clearing",
                prompt="Select clearing for battle",
                endpoint="pick_clearing",
                payload_details=[
                    {"type": "clearing_number", "name": "clearing_number"}
                ],
                accumulated_payload={"item_id": item_id, "action_type": action_type},
                options=options,
                faction=Faction(player.faction),
            )

    def post_pick_origin(self, request, game_id):
        player = self.player(request, game_id)
        origin_number = int(request.data["origin_number"])
        origin = get_object_or_404(
            Clearing, game=self.game(game_id), clearing_number=origin_number
        )

        adjacents = origin.connected_clearings.all()
        options = []
        origin_rule = determine_clearing_rule(origin)

        for dest in adjacents:
            dest_rule = determine_clearing_rule(dest)
            if origin_rule == player or dest_rule == player:
                options.append(
                    {
                        "value": str(dest.clearing_number),
                        "label": f"Clearing {dest.clearing_number} ({dest.get_suit_display()})",
                    }
                )

        return self.generate_step(
            name="pick_destination",
            prompt="Select destination clearing",
            endpoint="pick_destination",
            payload_details=[{"type": "clearing_number", "name": "destination_number"}],
            accumulated_payload=request.data,
            options=options,
            faction=Faction(player.faction),
        )

    def post_pick_destination(self, request, game_id):
        player = self.player(request, game_id)
        origin_number = int(request.data["origin_number"])
        origin = get_object_or_404(
            Clearing, game=self.game(game_id), clearing_number=origin_number
        )
        count = warrior_count_in_clearing(player, origin)

        options = [{"value": str(i), "label": str(i)} for i in range(1, count + 1)]

        return self.generate_step(
            name="pick_count",
            prompt="Select number of warriors to move",
            endpoint="pick_count",
            payload_details=[{"type": "number", "name": "count"}],
            accumulated_payload=request.data,
            options=options,
            faction=Faction(player.faction),
        )

    def post_pick_count(self, request, game_id):
        count = int(request.data["count"])
        return self.generate_completing_step(
            accumulated_payload={
                "item_id": request.data["item_id"],
                "origin_number": int(request.data["origin_number"]),
                "destination_number": int(request.data["destination_number"]),
                "count": count,
            },
            request=request,
            game_id=game_id,
            execution_route="execute_move",
        )

    def post_execute_move(self, request, game_id):
        player = self.player(request, game_id)
        item_id = request.data["item_id"]
        count = int(request.data["count"])
        move_warlord = bool(request.data.get("move_warlord", False))
        card_entry = get_object_or_404(
            CraftedCardEntry,
            player=player,
            card__card_type=CardsEP.LEAGUE_OF_ADVENTURERS.name,
        )
        item_entry = get_object_or_404(CraftedItemEntry, pk=item_id)
        origin = get_object_or_404(
            Clearing, game=self.game(game_id), clearing_number=int(request.data["origin_number"])
        )
        destination = get_object_or_404(
            Clearing, game=self.game(game_id), clearing_number=int(request.data["destination_number"])
        )
        move_data = {
            "origin_clearing": origin,
            "target_clearing": destination,
            "number": count,
            "move_warlord": move_warlord,
        }
        try:
            atomic_game_action(use_league_of_adventurers)(
                card_entry, item_entry, move_data=move_data
            )
        except ValueError as e:
            raise ValidationError({"detail": str(e)})
        return self.generate_completed_step()

    def post_pick_clearing(self, request, game_id):
        player = self.player(request, game_id)
        clearing_number = int(request.data["clearing_number"])
        clearing = get_object_or_404(
            Clearing, game=self.game(game_id), clearing_number=clearing_number
        )

        enemies = get_enemy_factions_in_clearing(player, clearing)
        options = [
            {
                "value": enemy_faction.value,
                "label": enemy_faction.label,
                "info": f"Initiate battle against the {enemy_faction.label}.",
            }
            for enemy_faction in enemies
        ]

        return self.generate_step(
            name="pick_opponent",
            prompt="Select opponent to battle",
            endpoint="pick_opponent",
            payload_details=[{"type": "faction", "name": "opponent_faction"}],
            accumulated_payload=request.data,
            options=options,
            faction=Faction(player.faction),
        )

    def post_pick_opponent(self, request, game_id):
        player = self.player(request, game_id)
        item_id = request.data["item_id"]
        clearing_number = int(request.data["clearing_number"])
        opponent_faction_code = request.data["opponent_faction"]

        card_entry = get_object_or_404(
            CraftedCardEntry,
            player=player,
            card__card_type=CardsEP.LEAGUE_OF_ADVENTURERS.name,
        )
        item_entry = get_object_or_404(CraftedItemEntry, pk=item_id)
        clearing = get_object_or_404(
            Clearing, game=self.game(game_id), clearing_number=clearing_number
        )

        battle_data = {"clearing": clearing, "opponent_faction": opponent_faction_code}

        try:
            atomic_game_action(use_league_of_adventurers)(
                card_entry, item_entry, battle_data=battle_data
            )
        except ValueError as e:
            raise ValidationError({"detail": str(e)})

        return self.generate_completed_step()
