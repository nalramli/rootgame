from rest_framework import serializers

from game.models.game_log import GameLog, LogType
from game.models.game_models import Game, Player
from game.serializers.logs.general import CardSerializer


# ---------------------------------------------------------------------------
# RATS_BUILD
# ---------------------------------------------------------------------------

class RatsBuildLogDetailsSerializer(serializers.Serializer):
    clearing_number = serializers.IntegerField()
    card = serializers.DictField()

    def get_text(self, obj):
        return f"Built a Stronghold in clearing {obj['clearing_number']} (spent {obj['card']['title']})"


def log_rats_build(
    game: Game,
    player: Player,
    clearing_number: int,
    card,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsBuildLogDetailsSerializer(
        data={
            "clearing_number": clearing_number,
            "card": CardSerializer(card).data,
        }
    )
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_BUILD,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_RAZE
# ---------------------------------------------------------------------------

class RatsRazeLogDetailsSerializer(serializers.Serializer):
    mob_clearing_count = serializers.IntegerField()

    def get_text(self, obj):
        n = obj["mob_clearing_count"]
        if n == 0:
            return "Raze: no Mob clearings — skipped"
        return f"Razed {n} clearing(s) with Mob tokens"


def log_rats_raze(
    game: Game,
    player: Player,
    mob_clearing_count: int,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsRazeLogDetailsSerializer(data={"mob_clearing_count": mob_clearing_count})
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_RAZE,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_MOB_SPREAD
# ---------------------------------------------------------------------------

class RatsMobSpreadLogDetailsSerializer(serializers.Serializer):
    clearing_number = serializers.IntegerField()
    suit = serializers.CharField()

    def get_text(self, obj):
        return f"Spread Mob to clearing {obj['clearing_number']} (rolled {obj['suit']})"


def log_rats_mob_spread(
    game: Game,
    player: Player,
    clearing_number: int,
    suit: str,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsMobSpreadLogDetailsSerializer(
        data={"clearing_number": clearing_number, "suit": suit}
    )
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_MOB_SPREAD,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_RECRUIT
# ---------------------------------------------------------------------------

class RatsRecruitLogDetailsSerializer(serializers.Serializer):
    warriors_placed = serializers.IntegerField()

    def get_text(self, obj):
        return f"Recruited {obj['warriors_placed']} warrior(s)"


def log_rats_recruit(
    game: Game,
    player: Player,
    warriors_placed: int,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsRecruitLogDetailsSerializer(data={"warriors_placed": warriors_placed})
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_RECRUIT,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_ANOINT
# ---------------------------------------------------------------------------

class RatsAnointLogDetailsSerializer(serializers.Serializer):
    clearing_number = serializers.IntegerField()
    consumed_warrior = serializers.BooleanField()

    def get_text(self, obj):
        text = f"Anointed Warlord in clearing {obj['clearing_number']}"
        if obj["consumed_warrior"]:
            text += " — consumed a warrior"
        return text


def log_rats_anoint(
    game: Game,
    player: Player,
    clearing_number: int,
    consumed_warrior: bool,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsAnointLogDetailsSerializer(
        data={"clearing_number": clearing_number, "consumed_warrior": consumed_warrior}
    )
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_ANOINT,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_CHOOSE_MOOD
# ---------------------------------------------------------------------------

class RatsChooseMoodLogDetailsSerializer(serializers.Serializer):
    mood = serializers.CharField()

    def get_text(self, obj):
        return f"Chose {obj['mood'].capitalize()} mood"


def log_rats_choose_mood(
    game: Game,
    player: Player,
    mood: str,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsChooseMoodLogDetailsSerializer(data={"mood": mood})
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_CHOOSE_MOOD,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_INCITE
# ---------------------------------------------------------------------------

class RatsInciteLogDetailsSerializer(serializers.Serializer):
    clearing_number = serializers.IntegerField()
    card = serializers.DictField()

    def get_text(self, obj):
        return f"Incite: placed Mob in clearing {obj['clearing_number']} (spent {obj['card']['title']})"


def log_rats_incite(
    game: Game,
    player: Player,
    clearing_number: int,
    card,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsInciteLogDetailsSerializer(
        data={"clearing_number": clearing_number, "card": CardSerializer(card).data}
    )
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_INCITE,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_OPPRESS
# ---------------------------------------------------------------------------

class RatsOppressLogDetailsSerializer(serializers.Serializer):
    clearing_count = serializers.IntegerField()
    vp = serializers.IntegerField()

    def get_text(self, obj):
        n = obj["clearing_count"]
        vp = obj["vp"]
        if vp == 0:
            return f"Oppress: ruled {n} clearing(s) — scored 0 VP"
        return f"Oppress: ruled {n} clearing(s) — scored {vp} VP"


def log_rats_oppress(
    game: Game,
    player: Player,
    clearing_count: int,
    vp: int,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsOppressLogDetailsSerializer(
        data={"clearing_count": clearing_count, "vp": vp}
    )
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_OPPRESS,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_HOARD_DISCARD
# ---------------------------------------------------------------------------

class RatsHoardDiscardLogDetailsSerializer(serializers.Serializer):
    item_type = serializers.CharField()
    track = serializers.CharField()

    def get_text(self, obj):
        return (
            f"Hoard too full: discarded {obj['item_type']} from {obj['track']} track"
            " — scored 1 VP"
        )


def log_rats_hoard_discard(
    game: Game,
    player: Player,
    item_type: str,
    track: str,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsHoardDiscardLogDetailsSerializer(
        data={"item_type": item_type, "track": track}
    )
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_HOARD_DISCARD,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_LOOT
# ---------------------------------------------------------------------------

class RatsLootLogDetailsSerializer(serializers.Serializer):
    item_type = serializers.CharField()
    looted_faction = serializers.CharField()

    def get_text(self, obj):
        return f"Looted {obj['item_type']} from {obj['looted_faction']} — added to Hoard"


def log_rats_loot(
    game: Game,
    player: Player,
    item_type: str,
    looted_faction: str,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsLootLogDetailsSerializer(
        data={"item_type": item_type, "looted_faction": looted_faction}
    )
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_LOOT,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_BITTER_ABSORB
# ---------------------------------------------------------------------------

class RatsBitterAbsorbLogDetailsSerializer(serializers.Serializer):
    mob_clearing_number = serializers.IntegerField()
    warlord_clearing_number = serializers.IntegerField()

    def get_text(self, obj):
        return (
            f"Bitter: absorbed Mob from clearing {obj['mob_clearing_number']}"
            f" — placed warrior in clearing {obj['warlord_clearing_number']}"
        )


def log_rats_bitter_absorb(
    game: Game,
    player: Player,
    mob_clearing_number: int,
    warlord_clearing_number: int,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsBitterAbsorbLogDetailsSerializer(
        data={
            "mob_clearing_number": mob_clearing_number,
            "warlord_clearing_number": warlord_clearing_number,
        }
    )
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_BITTER_ABSORB,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_LAVISH_LIQUIDATE
# ---------------------------------------------------------------------------

class RatsLavishLiquidateLogDetailsSerializer(serializers.Serializer):
    item_type = serializers.CharField()
    track = serializers.CharField()
    warriors_placed = serializers.IntegerField()
    clearing_number = serializers.IntegerField(allow_null=True)

    def get_text(self, obj):
        if obj["clearing_number"] is None:
            return (
                f"Lavish: liquidated {obj['item_type']} from {obj['track']} track"
                " — Warlord not on map, no warriors placed"
            )
        return (
            f"Lavish: liquidated {obj['item_type']} from {obj['track']} track"
            f" — placed {obj['warriors_placed']} warrior(s) in clearing {obj['clearing_number']}"
        )


def log_rats_lavish_liquidate(
    game: Game,
    player: Player,
    item_type: str,
    track: str,
    warriors_placed: int,
    clearing_number: int | None,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsLavishLiquidateLogDetailsSerializer(
        data={
            "item_type": item_type,
            "track": track,
            "warriors_placed": warriors_placed,
            "clearing_number": clearing_number,
        }
    )
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_LAVISH_LIQUIDATE,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# RATS_JUBILANT_SPREAD
# ---------------------------------------------------------------------------

class RatsJubilantSpreadLogDetailsSerializer(serializers.Serializer):
    clearing_number = serializers.IntegerField()
    rolls_remaining = serializers.IntegerField()

    def get_text(self, obj):
        r = obj["rolls_remaining"]
        return (
            f"Jubilant: placed Mob in clearing {obj['clearing_number']}"
            f" ({r} roll(s) remaining)"
        )


def log_rats_jubilant_spread(
    game: Game,
    player: Player,
    clearing_number: int,
    rolls_remaining: int,
    parent: GameLog | None = None,
) -> GameLog:
    serializer = RatsJubilantSpreadLogDetailsSerializer(
        data={"clearing_number": clearing_number, "rolls_remaining": rolls_remaining}
    )
    serializer.is_valid(raise_exception=True)
    return GameLog.objects.create(
        game=game,
        player=player,
        log_type=LogType.RATS_JUBILANT_SPREAD,
        details=serializer.validated_data,
        parent=parent,
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_SERIALIZER_MAP = {
    LogType.RATS_BUILD:            RatsBuildLogDetailsSerializer,
    LogType.RATS_RAZE:             RatsRazeLogDetailsSerializer,
    LogType.RATS_MOB_SPREAD:       RatsMobSpreadLogDetailsSerializer,
    LogType.RATS_RECRUIT:          RatsRecruitLogDetailsSerializer,
    LogType.RATS_ANOINT:           RatsAnointLogDetailsSerializer,
    LogType.RATS_CHOOSE_MOOD:      RatsChooseMoodLogDetailsSerializer,
    LogType.RATS_INCITE:           RatsInciteLogDetailsSerializer,
    LogType.RATS_OPPRESS:          RatsOppressLogDetailsSerializer,
    LogType.RATS_HOARD_DISCARD:    RatsHoardDiscardLogDetailsSerializer,
    LogType.RATS_LOOT:             RatsLootLogDetailsSerializer,
    LogType.RATS_BITTER_ABSORB:    RatsBitterAbsorbLogDetailsSerializer,
    LogType.RATS_LAVISH_LIQUIDATE: RatsLavishLiquidateLogDetailsSerializer,
    LogType.RATS_JUBILANT_SPREAD:  RatsJubilantSpreadLogDetailsSerializer,
}


def get_serializer_data(log: GameLog, details: dict, request=None):
    serializer_cls = _SERIALIZER_MAP.get(log.log_type)
    if serializer_cls is None:
        return None
    s = serializer_cls(details)
    data = dict(s.data)
    data["text"] = s.get_text(details)
    return data
