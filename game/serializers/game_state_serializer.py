from rest_framework import serializers
from game.models.game_models import (
    Game,
    DeckEntry,
    DiscardPileEntry,
    Item,
    Ruin,
    CraftableItemEntry,
    CraftedItemEntry,
    Player,
    HandEntry,
    Faction,
)
from game.models.dominance import DominanceSupplyEntry, ActiveDominanceEntry
from game.models.wa.player import SupporterStackEntry, OfficerEntry

from game.serializers.bird_serializers import BirdSerializer, BirdTurnSerializer
from game.serializers.cat_serializers import CatSerializer, CatTurnSerializer
from game.serializers.wa_serializers import WASerializer, WATurnSerializer
from game.serializers.crows_serializers import CrowsSerializer, CrowTurnSerializer
from game.serializers.moles_serializers import MolesSerializer, MoleTurnSerializer
from game.serializers.rats_serializers import RatsSerializer, RatsTurnSerializer
from game.serializers.general_serializers import (
    CardSerializer,
    DominanceSupplyEntrySerializer,
)
from game.serializers.event_serializers import EventSerializer


class DeckEntrySerializer(serializers.ModelSerializer):
    card = serializers.IntegerField(source="card.id")

    class Meta:
        model = DeckEntry
        fields = ["card", "spot"]


class DiscardPileEntrySerializer(serializers.ModelSerializer):
    card = serializers.IntegerField(source="card.id")

    class Meta:
        model = DiscardPileEntry
        fields = ["card", "spot"]


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = ["item_type", "exhausted"]


class RuinSerializer(serializers.ModelSerializer):
    item = ItemSerializer()
    building_slot_number = serializers.SerializerMethodField()
    clearing_number = serializers.SerializerMethodField()

    class Meta:
        model = Ruin
        fields = ["item", "building_slot_number", "clearing_number"]

    def get_building_slot_number(self, obj):
        return obj.building_slot.building_slot_number if obj.building_slot else None

    def get_clearing_number(self, obj):
        return obj.building_slot.clearing.clearing_number if obj.building_slot else None


class CraftableItemEntrySerializer(serializers.ModelSerializer):
    item = ItemSerializer()

    class Meta:
        model = CraftableItemEntry
        fields = ["item"]


class CraftedItemEntrySerializer(serializers.ModelSerializer):
    item = ItemSerializer()
    player_id = serializers.IntegerField(source="player.id")

    class Meta:
        model = CraftedItemEntry
        fields = ["item", "player_id"]


# WA Extras
class SupporterStackEntrySerializer(serializers.ModelSerializer):
    card = serializers.IntegerField(source="card.id")

    class Meta:
        model = SupporterStackEntry
        fields = ["card"]


class OfficerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = OfficerEntry
        fields = ["used"]


class HandEntrySerializer(serializers.ModelSerializer):
    card = serializers.IntegerField(source="card.id")

    class Meta:
        model = HandEntry
        fields = ["card"]


class GameStateSerializer(serializers.ModelSerializer):
    deck = DeckEntrySerializer(source="deckentry_set", many=True)
    discard = DiscardPileEntrySerializer(source="discardpileentry_set", many=True)
    ruins = RuinSerializer(source="ruin_set", many=True)
    craftable_items = CraftableItemEntrySerializer(
        source="craftableitementry_set", many=True
    )
    dominance_supply = DominanceSupplyEntrySerializer(
        source="dominancesupplyentry_set", many=True
    )
    crafted_items = serializers.SerializerMethodField()
    players = serializers.SerializerMethodField()
    turn_state = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = [
            "id",
            "current_turn",
            "boardmap",
            "deck",
            "discard",
            "ruins",
            "craftable_items",
            "dominance_supply",
            "crafted_items",
            "players",
            "turn_state",
            "events",
        ]

    def get_events(self, game):
        from game.models.events.event import Event

        events = Event.objects.filter(game=game, is_resolved=False).order_by(
            "created_at"
        )
        return EventSerializer(events, many=True).data

    def get_turn_state(self, game):
        # Find current player based on game.current_turn
        try:
            player = Player.objects.get(game=game, turn_order=game.current_turn)
        except Player.DoesNotExist:
            return None

        # Determine faction and retrieve the corresponding Turn model
        from game.models.birds.turn import BirdTurn
        from game.models.cats.turn import CatTurn
        from game.models.wa.turn import WATurn
        from game.models.crows.turn import CrowTurn
        from game.models.moles.turn import MoleTurn
        from game.models.rats.turn import RatsTurn

        if player.faction == Faction.BIRDS:
            turn_obj = BirdTurn.objects.filter(player=player).last()
            if turn_obj:
                return BirdTurnSerializer(turn_obj).data

        elif player.faction == Faction.CATS:
            turn_obj = CatTurn.objects.filter(player=player).last()
            if turn_obj:
                return CatTurnSerializer(turn_obj).data

        elif player.faction == Faction.WOODLAND_ALLIANCE:
            turn_obj = WATurn.objects.filter(player=player).last()
            if turn_obj:
                return WATurnSerializer(turn_obj).data

        elif player.faction == Faction.CROWS:
            turn_obj = CrowTurn.objects.filter(player=player).last()
            if turn_obj:
                return CrowTurnSerializer(turn_obj).data

        elif player.faction == Faction.MOLES:
            turn_obj = MoleTurn.objects.filter(player=player).last()
            if turn_obj:
                return MoleTurnSerializer(turn_obj).data

        elif player.faction == Faction.RATS:
            turn_obj = RatsTurn.objects.filter(player=player).last()
            if turn_obj:
                return RatsTurnSerializer(turn_obj).data

        return None

    def get_crafted_items(self, game):
        return CraftedItemEntrySerializer(
            CraftedItemEntry.objects.filter(player__game=game), many=True
        ).data

    def get_players(self, game):
        players_data = []
        for player in game.players.all().order_by("turn_order"):
            p_data = {
                "id": player.id,
                "faction": player.faction,
                "score": player.score,
                "turn_order": player.turn_order,
            }

            # Serialize Hand (Private State)
            p_data["hand"] = HandEntrySerializer(
                HandEntry.objects.filter(player=player), many=True
            ).data

            # Serialize Active Dominance
            try:
                p_data["active_dominance"] = player.active_dominance.card.suit
            except ActiveDominanceEntry.DoesNotExist:
                p_data["active_dominance"] = None

            # Faction Logic
            if player.faction == Faction.BIRDS:
                p_data["faction_state"] = BirdSerializer.from_player(player).data
            elif player.faction == Faction.CATS:
                p_data["faction_state"] = CatSerializer.from_player(player).data
            elif player.faction == Faction.WOODLAND_ALLIANCE:
                base_data = WASerializer.from_player(player).data
                supporters = SupporterStackEntry.objects.filter(player=player)
                officers = OfficerEntry.objects.filter(player=player)
                base_data["supporters"] = SupporterStackEntrySerializer(
                    supporters, many=True
                ).data
                base_data["officers"] = OfficerEntrySerializer(officers, many=True).data
                p_data["faction_state"] = base_data
            elif player.faction == Faction.CROWS:
                p_data["faction_state"] = CrowsSerializer.from_player(player).data
            elif player.faction == Faction.MOLES:
                p_data["faction_state"] = MolesSerializer.from_player(player).data
            elif player.faction == Faction.RATS:
                p_data["faction_state"] = RatsSerializer.from_player(player).data

            players_data.append(p_data)

        return players_data
