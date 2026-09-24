"""Recipe-based source selection and derivative state for loaded assets
(ADR 0003, CONTEXT.md "Derivative state").

Pure functions over already-loaded :class:`~vectorpress.domain.asset.Asset`
objects and the domain's fixed :data:`~vectorpress.domain.recipe.RECIPES`:
nothing here touches the filesystem (only ``vectorpress.catalog.assets``
reads asset folders, per CLAUDE.md's layering guardrail), so ``ui`` will be
able to call these directly, without going through ``cli``, once it exists.
"""

from dataclasses import dataclass

from vectorpress.domain.asset import Asset, Source
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import RECIPES, Recipe


@dataclass(frozen=True)
class DerivativeSelection:
    """The outcome of selecting a source for one (asset, derivative type)
    (ADR 0003).

    ``source`` is set exactly when ``state`` is :attr:`DerivativeState.MISSING`
    (every possible derivative, in this PRD slice, since nothing is generated
    yet); ``reason`` is set exactly when ``state`` is
    :attr:`DerivativeState.IMPOSSIBLE`, naming the roles the recipe accepts
    that no declared source has.
    """

    derivative_type: DerivativeType
    state: DerivativeState
    source: Source | None
    reason: str | None


def select_source(asset: Asset, recipe: Recipe) -> DerivativeSelection:
    """Pick the source one asset's derivative of ``recipe``'s type would
    use, or explain why none can be picked (ADR 0003, issue #22).

    Precedence: the asset's pin for this type, if it has one (assumed valid
    here -- :mod:`vectorpress.catalog.assets` rejects an asset whose pin
    names an undeclared file, a file with an unaccepted role, or a type with
    no recipe, so the asset would not have loaded at all); else the recipe's
    accepted roles in preference order, the first declared source with the
    first role present (first-declared source wins a tie within one role).
    """
    pin = asset.derivatives.get(recipe.derivative_type.value)
    if pin is not None:
        pinned_source = next((s for s in asset.sources if s.file == pin.source), None)
        assert pinned_source is not None, (
            "an asset with an invalid pin does not load (vectorpress.catalog.assets)"
        )
        return DerivativeSelection(
            derivative_type=recipe.derivative_type,
            state=DerivativeState.MISSING,
            source=pinned_source,
            reason=None,
        )

    for role in recipe.accepted_roles:
        for source in asset.sources:
            if source.role == role:
                return DerivativeSelection(
                    derivative_type=recipe.derivative_type,
                    state=DerivativeState.MISSING,
                    source=source,
                    reason=None,
                )

    accepted = ", ".join(recipe.accepted_roles)
    return DerivativeSelection(
        derivative_type=recipe.derivative_type,
        state=DerivativeState.IMPOSSIBLE,
        source=None,
        reason=f"no source with an accepted role ({accepted})",
    )


def select_derivatives(asset: Asset) -> list[DerivativeSelection]:
    """One :class:`DerivativeSelection` per recipe-bearing derivative type,
    for one asset, in :class:`~vectorpress.domain.derivative_type.DerivativeType`
    declaration order.

    A derivative type with no recipe yet (PRD 3, PRD 10) has no entry here
    at all: per the PRD it is reported nowhere, neither missing nor
    impossible.
    """
    return [select_source(asset, recipe) for recipe in RECIPES.values()]


@dataclass(frozen=True)
class DerivativeStateCounts:
    """How many (asset, derivative type) pairs are in each state, across a
    set of loaded assets (§34's "missing expected derivatives", issue #22).

    Inventory counts, not metadata problems: they do not affect
    ``vpress status``'s exit code.
    """

    missing: int
    impossible: int


def count_derivative_states(assets: list[Asset]) -> DerivativeStateCounts:
    """Tally derivative states across every loaded asset, for ``vpress
    status``."""
    missing = 0
    impossible = 0
    for asset in assets:
        for selection in select_derivatives(asset):
            if selection.state is DerivativeState.MISSING:
                missing += 1
            elif selection.state is DerivativeState.IMPOSSIBLE:
                impossible += 1
    return DerivativeStateCounts(missing=missing, impossible=impossible)
