from game.transactions.general import next_step
from game.queries.general import get_current_player
from game.models.events.setup import GameSimpleSetup
from game.models.game_models import Game
from django.db import transaction

from game.utility.textchoice import next_choice


@transaction.atomic
def next_player_setup(game: Game):
    """moves along the setup process, and if complete, starts the game"""
    simple_setup = GameSimpleSetup.objects.get(game=game)
    simple_setup.status = next_choice(
        GameSimpleSetup.GameSetupStatus, simple_setup.status
    )
    simple_setup.save()
    if simple_setup.status == GameSimpleSetup.GameSetupStatus.COMPLETED:
        game.status = Game.GameStatus.SETUP_COMPLETED
        game.save()
        # ad hoc, but need the next_step called initially
        first_player = get_current_player(game)
        from game.transactions.general import create_turn

        create_turn(first_player)
        next_step(first_player)
        return

    # Check if the faction for the current setup step is in the game
    from game.models.game_models import Faction, Player

    status_to_faction = {
        GameSimpleSetup.GameSetupStatus.CATS_SETUP: Faction.CATS,
        GameSimpleSetup.GameSetupStatus.BIRDS_SETUP: Faction.BIRDS,
        GameSimpleSetup.GameSetupStatus.WA_SETUP: Faction.WOODLAND_ALLIANCE,
        GameSimpleSetup.GameSetupStatus.CROWS_SETUP: Faction.CROWS,
        GameSimpleSetup.GameSetupStatus.MOLES_SETUP: Faction.MOLES,
        GameSimpleSetup.GameSetupStatus.RATS_SETUP: Faction.RATS,
    }

    # If the step isn't INITIAL_SETUP or COMPLETED, we must verify the faction is present
    if simple_setup.status not in [
        GameSimpleSetup.GameSetupStatus.INITIAL_SETUP,
        GameSimpleSetup.GameSetupStatus.COMPLETED,
    ]:
        current_faction = status_to_faction.get(simple_setup.status)

        # Woodland Alliance setup is fully automatic, so we skip it during setup progression
        if current_faction == Faction.WOODLAND_ALLIANCE:
            next_player_setup(game)
            return

        if (
            not current_faction
            or not Player.objects.filter(game=game, faction=current_faction).exists()
        ):
            # Faction is not in the game or not fully implemented, skip
            next_player_setup(game)
