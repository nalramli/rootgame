from game.errors import IllegalActionError
from game.game_data.cards.exiles_and_partisans import CardsEP
from game.models.game_models import Clearing, Player, Suit
from game.models.rats.buildings import Stronghold


def get_craftable_clearings(player: Player) -> list[Clearing]:
    """Return clearings where the Rats have a Stronghold with crafted_with=False."""
    strongholds = Stronghold.objects.filter(
        player=player,
        crafted_with=False,
        building_slot__isnull=False,
    ).select_related("building_slot__clearing")
    seen: set[int] = set()
    clearings: list[Clearing] = []
    for sh in strongholds:
        clearing = sh.building_slot.clearing
        if clearing.pk not in seen:
            seen.add(clearing.pk)
            clearings.append(clearing)
    return clearings


def get_unused_stronghold_in_clearing(player: Player, clearing: Clearing) -> Stronghold:
    """Return an unused Stronghold in the given clearing.

    Raises IllegalActionError if none is available.
    """
    stronghold = Stronghold.objects.filter(
        player=player,
        crafted_with=False,
        building_slot__clearing=clearing,
    ).first()
    if stronghold is None:
        raise IllegalActionError(
            f"No unused Stronghold in clearing {clearing.clearing_number}"
        )
    return stronghold


def validate_crafting_pieces_satisfy_requirements(
    player: Player, card: CardsEP, strongholds: list[Stronghold]
) -> bool:
    """Validate that the given strongholds satisfy the card's crafting cost.

    Suit is derived from the Stronghold's building_slot clearing suit.
    Raises IllegalActionError if pieces don't satisfy card requirements.
    """
    suits_needed = card.value.cost
    if len(strongholds) != len(suits_needed):
        raise IllegalActionError(
            f"Card requires {len(suits_needed)} crafting piece(s), got {len(strongholds)}"
        )

    if len(strongholds) != len(set(sh.id for sh in strongholds)):
        raise IllegalActionError("Duplicate crafting pieces provided")

    satisfied = [False for _ in suits_needed]
    for stronghold in strongholds:
        if stronghold.crafted_with:
            raise IllegalActionError(
                "A Stronghold has already been used for crafting this turn"
            )
        sh_suit = Suit(stronghold.building_slot.clearing.suit)
        matched = False
        first_wild_idx: int | None = None
        for i, suit_needed in enumerate(suits_needed):
            if satisfied[i]:
                continue
            if suit_needed.value == sh_suit.value:
                satisfied[i] = True
                matched = True
                break
            elif suit_needed.value == Suit.WILD.value and first_wild_idx is None:
                first_wild_idx = i
        if not matched:
            if first_wild_idx is None:
                raise IllegalActionError(
                    f"Stronghold in {sh_suit} clearing does not satisfy any remaining requirement"
                )
            satisfied[first_wild_idx] = True

    if not all(satisfied):
        raise IllegalActionError("Strongholds do not satisfy the card's crafting cost")

    return True
