from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from game.models.game_log import GameLog

class GameLogSerializer(serializers.ModelSerializer):
    details = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()
    player_faction = serializers.CharField(source="player.faction", read_only=True, allow_null=True)

    class Meta:
        model = GameLog
        fields = ["id", "parent_id", "player_faction", "created_at", "log_type", "details", "children"]

    @extend_schema_field(OpenApiTypes.ANY)
    def get_details(self, log: GameLog):
        details = dict(log.details)
        request = self.context.get("request")

        # Delegate to submodules
        from .general import get_serializer_data as get_general_data
        from .cats import get_serializer_data as get_cats_data
        from .birds import get_serializer_data as get_birds_data
        from .wa import get_serializer_data as get_wa_data
        from .crows import get_serializer_data as get_crow_data
        from .moles import get_serializer_data as get_moles_data
        from .rats import get_serializer_data as get_rats_data
        from .crafted_cards import get_serializer_data as get_crafted_data

        for getter in [
            get_general_data,
            get_cats_data,
            get_birds_data,
            get_wa_data,
            get_crow_data,
            get_moles_data,
            get_rats_data,
            get_crafted_data,
        ]:
            result = getter(log, details, request=request)
            if result is not None:
                return result

        return details

    def get_children(self, log: GameLog):
        children = getattr(log, "_children", [])
        return GameLogSerializer(children, many=True, context=self.context).data
