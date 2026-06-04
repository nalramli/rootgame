from game.models.crows import CrowTurn
from game.models.crows.setup import CrowsSimpleSetup
from rest_framework import serializers
from django.contrib.auth.models import User
from game.models.birds.setup import BirdsSimpleSetup
from game.models.birds.turn import BirdTurn
from game.models.cats.setup import CatsSimpleSetup
from game.models.cats.turn import CatTurn
from game.models.events.setup import GameSimpleSetup
from game.queries.cards.active_effects import can_use_card, is_used
from game.models.game_models import (
    Building,
    BuildingSlot,
    Card,
    Clearing,
    Faction,
    FactionChoiceEntry,
    Game,
    HandEntry,
    Player,
    Warrior,
    Token,
    CraftedCardEntry,
    Suit,
    ItemTypes,
    CraftableItemEntry,
    CraftedItemEntry,
)
from game.models.wa.turn import WATurn
from game.models.moles.setup import MolesSimpleSetup
from game.models.moles.turn import MoleTurn
from game.models.rats.setup import RatsSimpleSetup
from game.models.rats.turn import RatsTurn
from game.models.dominance import DominanceSupplyEntry, ActiveDominanceEntry
from drf_spectacular.utils import extend_schema_field, Direction
from drf_spectacular.extensions import OpenApiSerializerFieldExtension


class ValidationErrorSerializer(serializers.Serializer):
    detail = serializers.JSONField(help_text="Error message or object.")


class LabeledChoiceField(serializers.ChoiceField):
    def to_representation(self, value):
        if isinstance(value, dict) and "value" in value:
            return value
        result = super().to_representation(value)
        if result is None:
            return None
        return {"value": result, "label": self.choices.get(result, result)}

    def to_internal_value(self, data):
        if isinstance(data, dict) and "value" in data:
            data = data["value"]
        return super().to_internal_value(data)


class LabeledChoiceFieldExtension(OpenApiSerializerFieldExtension):
    target_class = LabeledChoiceField
    match_subclasses = True

    def map_serializer_field(self, auto_schema, direction):
        if direction == "request":
            return auto_schema._map_serializer_field(
                serializers.ChoiceField(choices=self.target.choices), direction
            )

        labels = []
        for _, label in self.target.choices.items():
            labels.append(str(label))
        labels = sorted(list(set(labels)))

        return {
            "type": "object",
            "properties": {
                "value": auto_schema._map_serializer_field(
                    serializers.ChoiceField(choices=self.target.choices), direction
                ),
                "label": {"type": "string", "enum": labels},
            },
            "required": ["value", "label"],
        }


class CardSerializer(serializers.ModelSerializer):
    card_name = serializers.SerializerMethodField()
    suit = LabeledChoiceField(choices=Suit.choices)
    title = serializers.CharField()
    text = serializers.CharField(allow_blank=True)
    craftable = serializers.BooleanField()
    cost = serializers.ListField(child=LabeledChoiceField(choices=Suit.choices))
    item = LabeledChoiceField(choices=ItemTypes.choices, allow_null=True)
    crafted_points = serializers.IntegerField()
    ambush = serializers.BooleanField()
    dominance = serializers.BooleanField()

    class Meta:
        model = Card
        fields = [
            "id",
            "card_name",
            "suit",
            "title",
            "text",
            "craftable",
            "cost",
            "item",
            "crafted_points",
            "ambush",
            "dominance",
        ]

    def get_card_name(self, card: Card | dict):
        enum = getattr(card, "enum", None)
        if enum:
            return enum.name
        if isinstance(card, dict):
            return card.get("card_name", "")
        return ""


class CraftableItemSerializer(serializers.ModelSerializer):
    item = LabeledChoiceField(choices=ItemTypes.choices, source="item.item_type")

    class Meta:
        model = CraftableItemEntry
        fields = ["item"]


class CraftedItemEntrySerializer(serializers.ModelSerializer):
    item = LabeledChoiceField(choices=ItemTypes.choices, source="item.item_type")
    exhausted = serializers.BooleanField()

    class Meta:
        model = CraftedItemEntry
        fields = ["id", "item", "exhausted"]


class DominanceSupplyEntrySerializer(serializers.ModelSerializer):
    card = CardSerializer()

    class Meta:
        model = DominanceSupplyEntry
        fields = ["card"]


class CraftedCardSerializer(serializers.ModelSerializer):
    card = CardSerializer()
    can_be_used = serializers.SerializerMethodField()
    used = serializers.SerializerMethodField()

    action_endpoint = serializers.SerializerMethodField()

    class Meta:
        model = CraftedCardEntry
        fields = [
            "card",
            "can_be_used",
            "used",
            "action_endpoint",
        ]

    def get_can_be_used(self, crafted_card: CraftedCardEntry) -> bool:
        try:
            return can_use_card(crafted_card.player, crafted_card)
        except ValueError:
            return False

    def get_used(self, crafted_card: CraftedCardEntry) -> bool:
        return is_used(crafted_card)

    def get_action_endpoint(self, crafted_card: CraftedCardEntry) -> str | None:
        if can_use_card(crafted_card.player, crafted_card):
            slug = crafted_card.card.enum.name.lower().replace("_", "-")
            return f"api/action/card/{slug}/"
        return None


class WarriorSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(source="player.user.username")
    clearing_number = serializers.SerializerMethodField()

    class Meta:
        model = Warrior
        fields = [
            "player_name",
            "clearing_number",
        ]

    def get_clearing_number(self, warrior: Warrior) -> int | None:
        return (
            warrior.clearing.clearing_number if warrior.clearing is not None else None
        )


class BuildingSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(source="player.user.username")
    clearing_number = serializers.SerializerMethodField()
    building_slot_number = serializers.SerializerMethodField()

    class Meta:
        model = Building
        fields = [
            "player_name",
            "clearing_number",
            "building_slot_number",
        ]

    def get_clearing_number(self, building: Building) -> int | None:
        building_slot = building.building_slot
        return (
            building_slot.clearing.clearing_number
            if building_slot is not None
            else None
        )

    def get_building_slot_number(self, building: Building) -> int | None:
        building_slot = building.building_slot
        return building_slot.building_slot_number if building_slot is not None else None


class TokenSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(source="player.user.username")
    clearing_number = serializers.SerializerMethodField()

    class Meta:
        model = Token
        fields = [
            "player_name",
            "clearing_number",
        ]

    def get_clearing_number(self, token: Token) -> int | None:
        clearing = getattr(token, "clearing", None)
        return clearing.clearing_number if clearing is not None else None


class ClearingSerializer(serializers.ModelSerializer):
    suit = LabeledChoiceField(choices=Suit.choices)
    connected_to = serializers.SerializerMethodField()
    water_connected_to = serializers.SerializerMethodField()
    ruins = serializers.SerializerMethodField()

    class Meta:
        model = Clearing
        fields = [
            "suit",
            "clearing_number",
            "connected_to",
            "water_connected_to",
            "ruins",
        ]

    def get_connected_to(self, clearing: Clearing) -> list[int]:
        return [
            clearing.clearing_number for clearing in clearing.connected_clearings.all()
        ]

    def get_water_connected_to(self, clearing: Clearing) -> list[int]:
        return [
            clearing.clearing_number
            for clearing in clearing.water_connected_clearings.all()
        ]

    def get_ruins(self, clearing: Clearing) -> list[int]:
        from game.models.game_models import Ruin

        return list(
            Ruin.objects.filter(building_slot__clearing=clearing).values_list(
                "building_slot__building_slot_number", flat=True
            )
        )


class PlayerPublicSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username")
    faction = LabeledChoiceField(choices=Faction.choices)
    score = serializers.IntegerField()
    turn_order = serializers.IntegerField()
    card_count = serializers.SerializerMethodField()
    active_dominance = serializers.SerializerMethodField()
    crafted_items = serializers.SerializerMethodField()

    class Meta:
        model = Player
        fields = [
            "username",
            "faction",
            "score",
            "turn_order",
            "card_count",
            "active_dominance",
            "crafted_items",
        ]

    def get_active_dominance(self, player: Player):
        if hasattr(player, "active_dominance") and player.active_dominance:
            return LabeledChoiceField(choices=Suit.choices).to_representation(
                player.active_dominance.card.suit
            )
        return None

    def get_card_count(self, player: Player) -> int:
        return HandEntry.objects.filter(player=player).count()

    @extend_schema_field(serializers.ListField(child=CraftedItemEntrySerializer()))
    def get_crafted_items(self, player: Player):
        crafted_items = CraftedItemEntry.objects.filter(player=player)
        return CraftedItemEntrySerializer(crafted_items, many=True).data


class PlayerPrivateSerializer(serializers.ModelSerializer):
    cards_in_hand = serializers.SerializerMethodField()

    class Meta:
        model = Player
        fields = ["cards_in_hand"]

    def get_cards_in_hand(self, player: Player):
        hand_cards = HandEntry.objects.filter(player=player).select_related("card")
        cards = [hand_card.card for hand_card in hand_cards]
        return CardSerializer(cards, many=True).data


class TextChoiceLabelField(serializers.ChoiceField):
    def to_internal_value(self, data):
        # Accept label or value
        for value, label in self.choices.items():
            if data == label or data == value:
                return value
        self.fail("invalid_choice", input=data)


class FactionChoiceSerializer(serializers.Serializer):
    faction = TextChoiceLabelField(choices=Faction.choices)


class CreateNewGameSerializer(serializers.Serializer):
    map_label = TextChoiceLabelField(
        choices=Game.BoardMaps.choices, required=False, allow_null=True
    )
    faction_options = FactionChoiceSerializer(
        many=True, required=False, allow_null=True
    )


class PayloadEntry(serializers.Serializer):
    type = serializers.CharField()
    name = serializers.CharField()
    value = serializers.SerializerMethodField(allow_null=True, required=False)

    def get_value(self, payload_entry):
        # handle more types as we add them in.
        if payload_entry.get("value") is None:
            return None
        if payload_entry["type"] == "clearing_number":
            try:
                return int(payload_entry["value"])
            except KeyError:
                return None
        try:
            return payload_entry["value"]
        except KeyError:
            return None


class _PassThroughField(serializers.Field):
    """Serializes any JSON-compatible value without type coercion.

    Unlike CharField (which calls str()), this preserves booleans, integers,
    and other JSON-serializable types exactly as provided.
    """
    def to_representation(self, value):
        return value

    def to_internal_value(self, data):
        return data


class OptionSerializer(serializers.Serializer):
    value = _PassThroughField()
    label = serializers.CharField(required=False)
    info = serializers.CharField(required=False, allow_null=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not data.get("label"):
            data["label"] = data["value"]
        return data


class GameActionStepSerializer(serializers.Serializer):
    faction = LabeledChoiceField(choices=Faction.choices, required=False)
    name = serializers.CharField()
    prompt = serializers.CharField(required=False)
    endpoint = serializers.CharField(required=False)
    payload_details = serializers.ListField(
        child=PayloadEntry(), allow_empty=True, required=False
    )
    accumulated_payload = serializers.JSONField(required=False)
    options = OptionSerializer(many=True, required=False)
    new_base_endpoint = serializers.CharField(required=False, allow_null=True)


class GameActionSerializer(serializers.Serializer):
    name = serializers.CharField()
    route = serializers.CharField()


class CurrentActionSerializer(serializers.Serializer):
    route = serializers.CharField()


class GameStatusSerializer(serializers.Serializer):
    """
    Serializer for information on the current game status
    This includes the current turn information as well as any relevant events
    """

    game_status = LabeledChoiceField(choices=Game.GameStatus.choices)
    setup_status = LabeledChoiceField(
        choices=GameSimpleSetup.GameSetupStatus.choices, required=False
    )
    current_turn_player = serializers.CharField(required=False)
    # current_setup_object = serializers.SerializerMethodField(required=False)
    # current_event_object = GameEventSerializer(required=False)
    # current_event_object = GameEventSerializer(required=False)

    # TODO: event queue serializer (or just one event at a time?)
    @classmethod
    def from_game(cls, game: Game):
        setup_status = GameSimpleSetup.objects.get(game=game).status
        current_player = Player.objects.get(game=game, turn_order=game.current_turn)

        # if in setup, use setup turn objects
        if game.status == Game.GameStatus.STARTED:
            turn_object_dict = {
                Faction.CATS: CatsSimpleSetup,
                Faction.BIRDS: BirdsSimpleSetup,
                Faction.WOODLAND_ALLIANCE: None,  #
                Faction.CROWS: CrowsSimpleSetup,
                Faction.MOLES: MolesSimpleSetup,
                Faction.RATS: RatsSimpleSetup,
            }
        elif game.status == Game.GameStatus.SETUP_COMPLETED:
            turn_object_dict = {
                Faction.CATS: CatTurn,
                Faction.BIRDS: BirdTurn,
                Faction.WOODLAND_ALLIANCE: WATurn,
                Faction.CROWS: CrowTurn,
                Faction.MOLES: MoleTurn,
                Faction.RATS: RatsTurn,
            }
        if current_player is not None:
            faction = Faction(current_player.faction)
            turn_object = (
                turn_object_dict[faction]
                .objects.filter(player=current_player)
                .order_by("-turn_number")
                .first()
            )
            player_name = current_player.user.username
        else:
            turn_object = None
            player_name = None

        return cls(
            instance={
                "game_status": game.status,
                "setup_status": setup_status,
                "current_turn_player": player_name,
                "current_turn_object": turn_object,
            }
        )


class UserSerializer(serializers.ModelSerializer):
    username = serializers.CharField()

    class Meta:
        model = User
        fields = ["username"]


class PlayerSerializer(serializers.Serializer):
    faction = LabeledChoiceField(choices=Faction.choices)
    score = serializers.IntegerField()
    active_dominance = serializers.SerializerMethodField()

    def get_active_dominance(self, player: Player):
        if hasattr(player, "active_dominance") and player.active_dominance:
            return LabeledChoiceField(choices=Suit.choices).to_representation(
                player.active_dominance.card.suit
            )
        return None


class GameListSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source="owner.username")
    player_count = serializers.SerializerMethodField()
    status = LabeledChoiceField(choices=Game.GameStatus.choices)
    user_faction = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = [
            "id",
            "owner_username",
            "player_count",
            "status",
            "user_faction",
        ]

    def get_player_count(self, game: Game) -> int:
        return game.players.count()

    @extend_schema_field(LabeledChoiceField(choices=Faction.choices, allow_null=True))
    def get_user_faction(self, game: Game) -> dict | None:
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            try:
                player = game.players.get(user=request.user)
                return LabeledChoiceField(choices=Faction.choices).to_representation(
                    player.faction
                )
            except Player.DoesNotExist:
                return None
        return None


class FactionChoiceEntrySerializer(serializers.ModelSerializer):
    faction = LabeledChoiceField(choices=Faction.choices)

    class Meta:
        model = FactionChoiceEntry
        fields = ["faction", "chosen"]


class GameSessionSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source="owner.username")
    players = PlayerPublicSerializer(many=True, read_only=True)
    faction_choices = FactionChoiceEntrySerializer(many=True, read_only=True)
    status = LabeledChoiceField(choices=Game.GameStatus.choices)

    player_count = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = [
            "id",
            "owner_username",
            "player_count",
            "status",
            "players",
            "faction_choices",
        ]

    def get_player_count(self, game: Game) -> int:
        return game.players.count()
