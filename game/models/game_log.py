from django.db import models
from game.models.game_models import Game, Player

class LogType(models.TextChoices):
    # General structural logs
    TURN = "TURN", "Turn"
    PHASE = "PHASE", "Phase"
    
    # Generic action logs
    MOVE = "MOVE", "Move"
    BATTLE = "BATTLE", "Battle"
    CRAFT = "CRAFT", "Craft"
    DRAW = "DRAW", "Draw"
    DISCARD = "DISCARD", "Discard"
    AMBUSH = "AMBUSH", "Ambush"
    DICE_ROLL = "DICE_ROLL", "Dice Roll"
    PIECE_REMOVAL = "PIECE_REMOVAL", "Piece Removal"

    # Cats specific action logs
    CATS_BIRDS_FOR_HIRE = "CATS_BIRDS_FOR_HIRE", "Cats Birds for Hire"
    CATS_MARCH = "CATS_MARCH", "Cats March"
    CATS_WOOD_PLACEMENT = "CATS_WOOD_PLACEMENT", "Cats Wood Placement"
    CATS_BUILD = "CATS_BUILD", "Cats Build"
    CATS_OVERWORK = "CATS_OVERWORK", "Cats Overwork"
    CATS_RECRUIT = "CATS_RECRUIT", "Cats Recruit"
    CATS_SETUP_PICK_CORNER = "CATS_SETUP_PICK_CORNER", "Cats Setup Pick Corner"
    CATS_SETUP_PLACE_BUILDING = "CATS_SETUP_PLACE_BUILDING", "Cats Setup Place Building"

    # Birds specific action logs
    BIRDS_ADD_TO_DECREE = "BIRDS_ADD_TO_DECREE", "Birds Add To Decree"
    BIRDS_EMERGENCY_ROOST = "BIRDS_EMERGENCY_ROOST", "Birds Emergency Roost"
    BIRDS_DECREE_ACTION = "BIRDS_DECREE_ACTION", "Birds Decree Action"
    BIRDS_SCORE_ROOSTS = "BIRDS_SCORE_ROOSTS", "Birds Score Roosts"
    BIRDS_TURMOIL = "BIRDS_TURMOIL", "Birds Turmoil"
    BIRDS_NEW_LEADER = "BIRDS_NEW_LEADER", "Birds New Leader"
    BIRDS_SETUP_PICK_CORNER = "BIRDS_SETUP_PICK_CORNER", "Birds Setup Pick Corner"
    BIRDS_SETUP_CHOOSE_LEADER = "BIRDS_SETUP_CHOOSE_LEADER", "Birds Setup Choose Leader"

    # Woodland Alliance specific action logs
    WA_REVOLT = "WA_REVOLT", "Woodland Revolt"
    WA_SPREAD_SYMPATHY = "WA_SPREAD_SYMPATHY", "Woodland Spread Sympathy"
    WA_MOBILIZE = "WA_MOBILIZE", "Woodland Mobilize"
    WA_TRAIN = "WA_TRAIN", "Woodland Train"
    WA_ORGANIZE = "WA_ORGANIZE", "Woodland Organize"
    WA_MILITARY_OPERATION = "WA_MILITARY_OPERATION", "Woodland Military Operation"
    WA_OUTRAGE = "WA_OUTRAGE", "Woodland Outrage"
    WA_BASE_REMOVED = "WA_BASE_REMOVED", "Woodland Base Removed"
    WA_OFFICERS_LOST = "WA_OFFICERS_LOST", "Woodland Officers Lost"
    WA_SUPPORTERS_LOST = "WA_SUPPORTERS_LOST", "Woodland Supporters Lost"

    # Crows specific action logs
    CROWS_PLOT = "CROWS_PLOT", "Crows Plot"
    CROWS_FLIP = "CROWS_FLIP", "Crows Flip"
    CROWS_RECRUIT = "CROWS_RECRUIT", "Crows Recruit"
    CROWS_TRICK = "CROWS_TRICK", "Crows Trick"
    CROWS_EXPOSURE = "CROWS_EXPOSURE", "Crows Exposure"
    CROWS_RAID = "CROWS_RAID", "Crows Raid"
    CROWS_SETUP_PLACE_WARRIOR = "CROWS_SETUP_PLACE_WARRIOR", "Crows Setup Place Warrior"
    CROWS_EXTORTION_STOLE_CARD = "CROWS_EXTORTION_STOLE_CARD", "Crows Extortion Stole Card"

    # Rats specific action logs
    RATS_BUILD             = "RATS_BUILD",             "Rats Build"
    RATS_RAZE              = "RATS_RAZE",              "Rats Raze"
    RATS_MOB_SPREAD        = "RATS_MOB_SPREAD",        "Rats Mob Spread"
    RATS_RECRUIT           = "RATS_RECRUIT",           "Rats Recruit"
    RATS_ANOINT            = "RATS_ANOINT",            "Rats Anoint"
    RATS_CHOOSE_MOOD       = "RATS_CHOOSE_MOOD",       "Rats Choose Mood"
    RATS_INCITE            = "RATS_INCITE",            "Rats Incite"
    RATS_OPPRESS           = "RATS_OPPRESS",           "Rats Oppress"
    RATS_HOARD_DISCARD     = "RATS_HOARD_DISCARD",     "Rats Hoard Discard"
    RATS_LOOT              = "RATS_LOOT",              "Rats Loot"
    RATS_BITTER_ABSORB     = "RATS_BITTER_ABSORB",     "Rats Bitter Absorb"
    RATS_LAVISH_LIQUIDATE  = "RATS_LAVISH_LIQUIDATE",  "Rats Lavish Liquidate"
    RATS_JUBILANT_SPREAD   = "RATS_JUBILANT_SPREAD",   "Rats Jubilant Spread"

    # Moles specific action logs
    MOLES_SETUP_PICK_CORNER = "MOLES_SETUP_PICK_CORNER", "Moles Setup Pick Corner"
    MOLES_BIRDSONG_PLACE_WARRIORS = "MOLES_BIRDSONG_PLACE_WARRIORS", "Moles Birdsong Place Warriors"
    MOLES_BUILD = "MOLES_BUILD", "Moles Build"
    MOLES_RECRUIT = "MOLES_RECRUIT", "Moles Recruit"
    MOLES_DIG = "MOLES_DIG", "Moles Dig"
    MOLES_SWAY_MINISTER = "MOLES_SWAY_MINISTER", "Moles Sway Minister"
    MOLES_MINISTER_MARSHAL = "MOLES_MINISTER_MARSHAL", "Moles Minister Marshal"
    MOLES_MINISTER_CAPTAIN = "MOLES_MINISTER_CAPTAIN", "Moles Minister Captain"
    MOLES_MINISTER_FOREMOLE = "MOLES_MINISTER_FOREMOLE", "Moles Minister Foremole"
    MOLES_MINISTER_BANKER = "MOLES_MINISTER_BANKER", "Moles Minister Banker"
    MOLES_MINISTER_DUCHESS = "MOLES_MINISTER_DUCHESS", "Moles Minister Duchess of Mud"
    MOLES_MINISTER_BARON = "MOLES_MINISTER_BARON", "Moles Minister Baron of Dirt"
    MOLES_MINISTER_EARL = "MOLES_MINISTER_EARL", "Moles Minister Earl of Stone"
    MOLES_MINISTER_BRIGADIER = "MOLES_MINISTER_BRIGADIER", "Moles Minister Brigadier"
    MOLES_MINISTER_MAYOR = "MOLES_MINISTER_MAYOR", "Moles Minister Mayor"
    MOLES_EVENING_PROCESS_REVEALED = "MOLES_EVENING_PROCESS_REVEALED", "Moles Evening Process Revealed Cards"
    MOLES_PRICE_OF_FAILURE = "MOLES_PRICE_OF_FAILURE", "Moles Price of Failure"

    # Event response logs
    CATS_FIELD_HOSPITALS = "CATS_FIELD_HOSPITALS", "Field Hospitals"

    # Crafted Card Actions
    CRAFTED_CARD_ACTION = "CRAFTED_CARD_ACTION", "Crafted Card Action"

class GameLog(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="logs")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    player = models.ForeignKey(
        Player, on_delete=models.CASCADE, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    log_type = models.CharField(choices=LogType.choices, max_length=50)
    details = models.JSONField(default=dict)
    
    # Optional links to events/state
    outrage_event = models.ForeignKey("game.OutrageEvent", on_delete=models.SET_NULL, null=True, blank=True, related_name="logs")

    class Meta:
        ordering = ["created_at"]
