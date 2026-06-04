from game.views.action_views.cats.evening import CatsDiscardCardsView
from game.views.gamestate_views.wa import get_wa_player_private
from django.urls import URLPattern, path

from game.views.DevLoginView import DevLoginView
from game.views.action_views.battle import BattleActionView
from game.views.action_views.birds.birdsong import AddToDecreeView, EmergencyDrawingView
from game.views.action_views.birds.daylight import (
    BirdBattleView,
    BirdBuildingView,
    BirdCraftingView,
    BirdMoveView,
    BirdRecruitView,
)
from game.views.action_views.birds.turmoil import TurmoilView
from game.views.action_views.cats.birdsong import CatPlaceWoodView
from game.views.action_views.cats.daylight import CatActionsView, CatCraftStepView
from game.views.action_views.cats.evening import CatsDrawCardsView
from game.views.action_views.cats.field_hospital import FieldHospitalView
from game.views.action_views.setup.birds import (
    BirdsChooseLeaderInitialView,
    BirdsConfirmCompletedSetupView,
    BirdsPickCornerView,
)
from game.views.action_views.wa.birdsong import RevoltView, SpreadSympathyView
from game.views.action_views.wa.daylight import WADaylightActionsView
from game.views.action_views.wa.evening import WAOperationsView
from game.views.action_views.wa.outrage import OutrageView
from game.views.action_views.crows.birdsong import (
    CrowsCraftingView,
    CrowsFlippingView,
    CrowsRecruitingView,
    CrowsManualRecruitView,
)
from game.views.action_views.crows.daylight import CrowsDaylightActionsView
from game.views.action_views.crows.evening import CrowsExertView, CrowsDiscardingView
from game.views.action_views.moles.daylight import (
    MolesDaylightActionsView, MolesMoveView, MolesBattleView,
    MolesDigView, MolesBuildView,
)
from game.views.action_views.moles.minister_actions import (
    MolesMinisterActionsView, MolesMinisterMayorView, MolesMinisterMarshalView, MolesMinisterCaptainView,
    MolesMinisterForemoleView, MolesMinisterBrigadierView, MolesMinisterBankerView,
)
from game.views.action_views.moles.sway_minister import MolesSwayMinisterView
from game.views.action_views.moles.evening import MolesCraftingView, MolesDiscardView
from game.views.action_views.moles.price_of_failure import MolesPriceOfFailureView
from game.views.action_views.setup.crows import (
    CrowsPickClearingView,
    CrowsConfirmCompletedSetupView,
)
from game.views.action_views.setup.moles import (
    MolesPickCornerView,
    MolesConfirmCompletedSetupView,
)
from game.views.action_views.setup.rats import (
    RatsPickCornerView,
    RatsConfirmCompletedSetupView,
)
from game.views.action_views.rats.birdsong import (
    RatsBirdsongSpreadMobView,
    RatsBirdsongChooseMoodView,
)
from game.views.action_views.rats.daylight import (
    RatsDaylightCraftView,
    RatsDaylightCommandView,
    RatsCommandMoveView,
    RatsCommandBattleView,
    RatsCommandBuildView,
    RatsDaylightAdvanceView,
    RatsAdvanceMoveView,
    RatsAdvanceBattleView,
)
from game.views.action_views.rats.evening import (
    RatsEveningInciteView,
    RatsEveningDiscardView,
)
from game.views.action_views.rats.events import (
    RatsHoardTooFullView,
    RatsJubilantMobSpreadView,
    RatsLavishView,
    RatsLootingView,
    RatsResolveBitterView,
)
from game.views.gamestate_views import (
    get_bird_player_public,
    get_cat_player_public,
    get_clearings,
    get_discard_pile,
    get_player_hand,
    get_wa_player_public,
    get_moles_player_public,
    get_rats_player_public,
)
from game.views.gamestate_views.crows import (
    get_crows_player_public,
    get_crows_player_private,
)

from game.views.gamestate_views.general import (
    get_current_action,
    get_players,
    get_turn_info,
    undo_last_action_view,
    get_game_session_detail,
    get_dominance_supply,
    get_revealed_cards,
    get_craftable_items,
    get_game_logs,
    delete_game,
)
from game.views.gamestate_views.cards import GetCraftedCardsView
from game.views.setup_views import (
    create_game,
    create_demo_game,
    join_game,
    pick_faction,
    start_game_view,
    list_active_games,
    list_joinable_games,
    cats,
    birds,
)
from game.views.action_views.setup.cats import (
    CatsConfirmCompletedSetupView,
    CatsPickCornerView,
    CatsPlaceBuildingView,
)

from django.urls import path, include, re_path
from django.views.generic import TemplateView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from rest_framework.views import APIView

from game.views.user_info import get_player_info, get_user_info


def register_action(
    name: str, view: type[APIView], url: str, urlpatterns: list[URLPattern]
):
    get_path = path(url, view.as_view(), name=name)
    post_path = path(url + "<int:game_id>/<str:route>/", view.as_view(), name=name)
    urlpatterns.append(get_path)
    urlpatterns.append(post_path)


urlpatterns = [
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/user/", get_user_info, name="user"),
    path("api/player/<int:game_id>/", get_player_info, name="player"),
    path("api/players/<int:game_id>/", get_players, name="players"),
    path("api/cats/player-info/<int:game_id>/", get_cat_player_public),
    path("api/woodland-alliance/player-info/<int:game_id>/", get_wa_player_public),
    path(
        "api/woodland-alliance/player-private-info/<int:game_id>/",
        get_wa_player_private,
    ),
    path("api/crows/player-info/<int:game_id>/", get_crows_player_public),
    path("api/crows/player-private-info/<int:game_id>/", get_crows_player_private),
    path("api/birds/player-info/<int:game_id>/", get_bird_player_public),
    path("api/moles/player-info/<int:game_id>/", get_moles_player_public),
    path("api/rats/player-info/<int:game_id>/", get_rats_player_public),
    path("api/clearings/<int:game_id>/", get_clearings),
    path("api/discard-pile/<int:game_id>/", get_discard_pile),
    path("api/player-hand/<int:game_id>/", get_player_hand),
    path("api/turn-info/<int:game_id>/", get_turn_info),
    # setup views
    path("api/game/create/", create_game),
    path("api/game/create-demo/", create_demo_game),
    path("api/game/join/<int:game_id>/", join_game),
    path("api/game/pick-faction/<int:game_id>/", pick_faction),
    path("api/game/start/<int:game_id>/", start_game_view),
    path(
        "api/game/current-action/<int:game_id>/",
        get_current_action,
        name="get-current-action",
    ),
    path("api/game/undo/<int:game_id>/", undo_last_action_view, name="undo-action"),
    path(
        "api/game/<int:game_id>/session/",
        get_game_session_detail,
        name="game-session-detail",
    ),
    path(
        "api/crafted-cards/<int:game_id>/<str:faction>/",
        GetCraftedCardsView.as_view(),
        name="get-crafted-cards",
    ),
    path("api/games/active/", list_active_games, name="list-active-games"),
    path("api/games/joinable/", list_joinable_games, name="list-joinable-games"),
    path(
        "api/dominance-supply/<int:game_id>/",
        get_dominance_supply,
        name="get-dominance-supply",
    ),
    path(
        "api/game/revealed-cards/<int:game_id>/",
        get_revealed_cards,
        name="get-revealed-cards",
    ),
    path(
        "api/craftable-items/<int:game_id>/",
        get_craftable_items,
        name="get-craftable-items",
    ),
    path(
        "api/game-log/<int:game_id>/",
        get_game_logs,
        name="get-game-logs",
    ),
    path(
        "api/game/delete/<int:game_id>/",
        delete_game,
        name="delete-game",
    ),
]
register_action(
    "cats-setup-pick-corner",
    CatsPickCornerView,
    "api/cats/setup/pick-corner/",
    urlpatterns,
)
register_action(
    "cats-setup-place-initial-building",
    CatsPlaceBuildingView,
    "api/cats/setup/place-initial-building/",
    urlpatterns,
)
register_action(
    "cats-setup-confirm-completed-setup",
    CatsConfirmCompletedSetupView,
    "api/cats/setup/confirm-completed-setup/",
    urlpatterns,
)
# birds
register_action(
    "birds-setup-pick-corner",
    BirdsPickCornerView,
    "api/birds/setup/pick-corner/",
    urlpatterns,
)

register_action(
    "birds-setup-choose-leader",
    BirdsChooseLeaderInitialView,
    "api/birds/setup/choose-leader/",
    urlpatterns,
)
register_action(
    "birds-setup-confirm-completed-setup",
    BirdsConfirmCompletedSetupView,
    "api/birds/setup/confirm-completed-setup/",
    urlpatterns,
)


# Crows setup
register_action(
    "crows-setup-pick-clearing",
    CrowsPickClearingView,
    "api/crows/setup/pick-clearing/",
    urlpatterns,
)

register_action(
    "crows-setup-confirm-completed-setup",
    CrowsConfirmCompletedSetupView,
    "api/crows/setup/confirm-completed-setup/",
    urlpatterns,
)

# Moles setup
register_action(
    "moles-setup-pick-corner",
    MolesPickCornerView,
    "api/moles/setup/pick-corner/",
    urlpatterns,
)

register_action(
    "moles-setup-confirm-completed-setup",
    MolesConfirmCompletedSetupView,
    "api/moles/setup/confirm-completed-setup/",
    urlpatterns,
)

# Rats setup
register_action(
    "rats-setup-pick-corner",
    RatsPickCornerView,
    "api/rats/setup/pick-corner/",
    urlpatterns,
)

register_action(
    "rats-setup-confirm-completed-setup",
    RatsConfirmCompletedSetupView,
    "api/rats/setup/confirm-completed-setup/",
    urlpatterns,
)

# Rats birdsong
register_action(
    "rats-birdsong-spread-mob",
    RatsBirdsongSpreadMobView,
    "api/rats/birdsong/spread-mob/",
    urlpatterns,
)
register_action(
    "rats-birdsong-choose-mood",
    RatsBirdsongChooseMoodView,
    "api/rats/birdsong/choose-mood/",
    urlpatterns,
)

# Rats daylight
register_action(
    "rats-daylight-craft",
    RatsDaylightCraftView,
    "api/rats/daylight/craft/",
    urlpatterns,
)
register_action(
    "rats-daylight-command",
    RatsDaylightCommandView,
    "api/rats/daylight/command/",
    urlpatterns,
)
register_action(
    "rats-daylight-command-move",
    RatsCommandMoveView,
    "api/rats/daylight/command/move/",
    urlpatterns,
)
register_action(
    "rats-daylight-command-battle",
    RatsCommandBattleView,
    "api/rats/daylight/command/battle/",
    urlpatterns,
)
register_action(
    "rats-daylight-command-build",
    RatsCommandBuildView,
    "api/rats/daylight/command/build/",
    urlpatterns,
)
register_action(
    "rats-daylight-advance",
    RatsDaylightAdvanceView,
    "api/rats/daylight/advance/",
    urlpatterns,
)
register_action(
    "rats-daylight-advance-move",
    RatsAdvanceMoveView,
    "api/rats/daylight/advance/move/",
    urlpatterns,
)
register_action(
    "rats-daylight-advance-battle",
    RatsAdvanceBattleView,
    "api/rats/daylight/advance/battle/",
    urlpatterns,
)
# Rats evening
register_action(
    "rats-evening-incite",
    RatsEveningInciteView,
    "api/rats/evening/incite/",
    urlpatterns,
)
register_action(
    "rats-evening-discard",
    RatsEveningDiscardView,
    "api/rats/evening/discard/",
    urlpatterns,
)
# Rats events
register_action(
    "rats-hoard-too-full",
    RatsHoardTooFullView,
    "api/rats/events/hoard-too-full/",
    urlpatterns,
)
register_action(
    "rats-bitter-resolve",
    RatsResolveBitterView,
    "api/rats/events/bitter-resolve/",
    urlpatterns,
)
register_action(
    "rats-looting",
    RatsLootingView,
    "api/rats/events/looting/",
    urlpatterns,
)
register_action(
    "rats-jubilant-mob-spread",
    RatsJubilantMobSpreadView,
    "api/rats/events/jubilant-mob-spread/",
    urlpatterns,
)
register_action(
    "rats-lavish",
    RatsLavishView,
    "api/rats/events/lavish/",
    urlpatterns,
)

register_action(
    "cats-birdsong-place-wood",
    CatPlaceWoodView,
    "api/cats/birdsong/place-wood/",
    urlpatterns,
)
register_action(
    "cats-daylight-craft",
    CatCraftStepView,
    "api/cats/daylight/craft/",
    urlpatterns,
)

register_action(
    "cats-daylight-actions",
    CatActionsView,
    "api/cats/daylight/actions/",
    urlpatterns,
)
register_action(
    "cats-evening-draw-cards",
    CatsDrawCardsView,
    "api/cats/evening/draw-cards/",
    urlpatterns,
)
register_action(
    "cats-evening-discard-cards",
    CatsDiscardCardsView,
    "api/cats/evening/discard-cards/",
    urlpatterns,
)

register_action(
    "birds-emergency-draw",
    EmergencyDrawingView,
    "api/birds/birdsong/emergency-draw/",
    urlpatterns,
)
register_action(
    "birds-add-to-decree",
    AddToDecreeView,
    "api/birds/birdsong/add-to-decree/",
    urlpatterns,
)
register_action(
    "birds-craft",
    BirdCraftingView,
    "api/birds/daylight/craft/",
    urlpatterns,
)
register_action(
    "birds-recruit",
    BirdRecruitView,
    "api/birds/daylight/recruit/",
    urlpatterns,
)
register_action(
    "birds-move",
    BirdMoveView,
    "api/birds/daylight/move/",
    urlpatterns,
)
register_action(
    "birds-battle",
    BirdBattleView,
    "api/birds/daylight/battle/",
    urlpatterns,
)
register_action(
    "birds-build",
    BirdBuildingView,
    "api/birds/daylight/building/",
    urlpatterns,
)
register_action(
    "wa-revolt", RevoltView, "api/woodland-alliance/birdsong/revolt/", urlpatterns
)
register_action(
    "wa-spread-sympathy",
    SpreadSympathyView,
    "api/woodland-alliance/birdsong/spread-sympathy/",
    urlpatterns,
)
register_action(
    "wa-daylight",
    WADaylightActionsView,
    "api/woodland-alliance/daylight/actions/",
    urlpatterns,
)
register_action(
    "wa-operations",
    WAOperationsView,
    "api/woodland-alliance/evening/operations/",
    urlpatterns,
)
register_action(
    "battle",
    BattleActionView,
    "api/battle/",
    urlpatterns,
)

# Crows Actions
register_action(
    "crows-crafting",
    CrowsCraftingView,
    "api/crows/action/crafting/",
    urlpatterns,
)
register_action(
    "crows-flipping",
    CrowsFlippingView,
    "api/crows/action/flipping/",
    urlpatterns,
)
register_action(
    "crows-recruiting",
    CrowsRecruitingView,
    "api/crows/action/recruiting/",
    urlpatterns,
)
register_action(
    "crows-manual-recruit",
    CrowsManualRecruitView,
    "api/crows/action/manual-recruit/",
    urlpatterns,
)

from game.views.action_views.crows.raid import CrowsPlaceRaidWarriorsView

register_action(
    "crows-place-raid-warriors",
    CrowsPlaceRaidWarriorsView,
    "api/crows/action/place-raid-warriors/",
    urlpatterns,
)
register_action(
    "crows-daylight",
    CrowsDaylightActionsView,
    "api/crows/action/daylight/",
    urlpatterns,
)
register_action(
    "crows-exert",
    CrowsExertView,
    "api/crows/action/exert/",
    urlpatterns,
)
register_action(
    "crows-discard-cards",
    CrowsDiscardingView,
    "api/crows/action/discard/",
    urlpatterns,
)

register_action(
    "moles-daylight-actions",
    MolesDaylightActionsView,
    "api/moles/daylight/actions/",
    urlpatterns,
)
register_action(
    "moles-daylight-move",
    MolesMoveView,
    "api/moles/daylight/actions/move/",
    urlpatterns,
)
register_action(
    "moles-daylight-battle",
    MolesBattleView,
    "api/moles/daylight/actions/battle/",
    urlpatterns,
)
register_action(
    "moles-daylight-dig",
    MolesDigView,
    "api/moles/daylight/actions/dig/",
    urlpatterns,
)
register_action(
    "moles-daylight-build",
    MolesBuildView,
    "api/moles/daylight/actions/build/",
    urlpatterns,
)

register_action(
    "moles-minister-actions",
    MolesMinisterActionsView,
    "api/moles/daylight/minister-actions/",
    urlpatterns,
)
register_action(
    "moles-minister-mayor",
    MolesMinisterMayorView,
    "api/moles/daylight/minister-actions/mayor/",
    urlpatterns,
)
register_action(
    "moles-minister-marshal",
    MolesMinisterMarshalView,
    "api/moles/daylight/minister-actions/marshal/",
    urlpatterns,
)
register_action(
    "moles-minister-captain",
    MolesMinisterCaptainView,
    "api/moles/daylight/minister-actions/captain/",
    urlpatterns,
)
register_action(
    "moles-minister-foremole",
    MolesMinisterForemoleView,
    "api/moles/daylight/minister-actions/foremole/",
    urlpatterns,
)
register_action(
    "moles-minister-brigadier",
    MolesMinisterBrigadierView,
    "api/moles/daylight/minister-actions/brigadier/",
    urlpatterns,
)
register_action(
    "moles-minister-banker",
    MolesMinisterBankerView,
    "api/moles/daylight/minister-actions/banker/",
    urlpatterns,
)
register_action(
    "moles-sway-minister",
    MolesSwayMinisterView,
    "api/moles/daylight/sway-minister/",
    urlpatterns,
)

register_action(
    "moles-craft",
    MolesCraftingView,
    "api/moles/evening/craft/",
    urlpatterns,
)

register_action(
    "moles-discard",
    MolesDiscardView,
    "api/moles/evening/discard/",
    urlpatterns,
)

register_action(
    "moles-price-of-failure",
    MolesPriceOfFailureView,
    "api/moles/price-of-failure/",
    urlpatterns,
)

register_action(
    "outrage",
    OutrageView,
    "api/outrage/",
    urlpatterns,
)
register_action(
    "field-hospital",
    FieldHospitalView,
    "api/cats/field-hospital/",
    urlpatterns,
)
register_action(
    "turmoil",
    TurmoilView,
    "api/birds/turmoil/",
    urlpatterns,
)

from game.views.action_views.crafted_cards.propaganda_bureau import PropagandaBureauView
from game.views.action_views.crafted_cards.saboteurs import SaboteursView
from game.views.action_views.crafted_cards.charm_offensive import CharmOffensiveView
from game.views.action_views.crafted_cards.league_of_adventurers import (
    LeagueOfAdventurersView,
)
from game.views.action_views.crafted_cards.informants import InformantsView
from game.views.action_views.crafted_cards.eyrie_emigre import EyrieEmigreView
from game.views.action_views.crafted_cards.partisans import PartisansView
from game.views.action_views.crafted_cards.false_orders import FalseOrdersView
from game.views.action_views.crafted_cards.false_orders import FalseOrdersView


register_action(
    "propaganda-bureau",
    PropagandaBureauView,
    "api/action/card/propaganda-bureau/",
    urlpatterns,
)
register_action(
    "saboteurs",
    SaboteursView,
    "api/action/card/saboteurs/",
    urlpatterns,
)
register_action(
    "charm-offensive",
    CharmOffensiveView,
    "api/action/card/charm-offensive/",
    urlpatterns,
)
register_action(
    "league-of-adventurers",
    LeagueOfAdventurersView,
    "api/action/card/league-of-adventurers/",
    urlpatterns,
)
register_action(
    "informants",
    InformantsView,
    "api/action/card/informants/",
    urlpatterns,
)
register_action(
    "eyrie-emigre",
    EyrieEmigreView,
    "api/action/card/eyrie-emigre/",
    urlpatterns,
)
register_action(
    "partisans",
    PartisansView,
    "api/action/card/partisans/",
    urlpatterns,
)
register_action(
    "false-orders",
    FalseOrdersView,
    "api/action/card/false-orders/",
    urlpatterns,
)

from game.views.action_views.crafted_cards.swap_meet import SwapMeetView

register_action(
    "swap-meet",
    SwapMeetView,
    "api/action/card/swap-meet/",
    urlpatterns,
)

from game.views.action_views.dominance_views import (
    SwapDominanceView,
    ActivateDominanceView,
)

register_action(
    "swap-dominance",
    SwapDominanceView,
    "api/action/dominance/swap/",
    urlpatterns,
)

register_action(
    "activate-dominance",
    ActivateDominanceView,
    "api/action/dominance/activate/",
    urlpatterns,
)

urlpatterns.append(
    re_path(r"^.*$", TemplateView.as_view(template_name="index.html"), name="index")
)
