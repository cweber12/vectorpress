"""Generate derivatives for one asset: run the selected source through its
recipe's generator, and persist the result with provenance (ADR 0004, §6.1,
§20, §35, §36, issue #23).

The single place that turns a :class:`~vectorpress.catalog.derivatives.DerivativeSelection`
into an actual file: it decides which recipe and generator apply and in what
order, but every byte that crosses the disk boundary -- reading a source,
checking currency, writing output and provenance -- goes through
:mod:`vectorpress.catalog.provenance` (ADR 0006's "catalog... the only layer
touching catalog files"; this module never opens a catalog file itself).
Both ``vpress asset`` and ``vpress generate`` (``cli``) call this module, so
"is this derivative current" is answered in exactly one place.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from vectorpress import __version__
from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.derivatives import (
    DerivativeStateCounts,
    select_derivatives,
    tally_derivative_states,
)
from vectorpress.catalog.provenance import (
    DERIVED_DIRNAME,
    Provenance,
    is_current,
    read_source_bytes,
    recipe_identity_hash,
    sha256_bytes,
    write_derivative,
)
from vectorpress.domain.asset import Asset, Source
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.recipe import RECIPES, Recipe
from vectorpress.pipeline.registry import get_generator


@dataclass(frozen=True)
class DerivativeStatus:
    """One recipe-bearing derivative type's full state for one asset:
    :class:`~vectorpress.catalog.derivatives.DerivativeSelection` upgraded to
    ``CURRENT`` where a matching provenance record and output file already
    exist on disk (issue #23).

    ``output_filename`` is set exactly when ``state`` is
    :attr:`~vectorpress.domain.derivative_state.DerivativeState.CURRENT`.
    """

    derivative_type: DerivativeType
    state: DerivativeState
    source: Source | None
    reason: str | None
    output_filename: str | None


def asset_derivative_statuses(asset: Asset, asset_dir_path: Path) -> list[DerivativeStatus]:
    """One :class:`DerivativeStatus` per recipe-bearing derivative type, for
    one asset, upgrading :func:`~vectorpress.catalog.derivatives.select_derivatives`'s
    ``MISSING`` to ``CURRENT`` where generation has already produced a
    matching, up-to-date file (issue #23).

    A type whose recipe has no generator yet (``silhouette_svg``,
    ``flatcolor_svg`` this slice) can never be ``CURRENT``: it stays
    ``MISSING``, the same as before generation existed at all.
    """
    statuses: list[DerivativeStatus] = []
    for selection in select_derivatives(asset):
        recipe = RECIPES[selection.derivative_type]
        state = selection.state
        output_filename: str | None = None

        if state is DerivativeState.MISSING and recipe.generator is not None:
            assert selection.source is not None  # MISSING always carries a selected source
            candidate = derivative_filename(asset.display_name, recipe.derivative_type)
            if is_current(
                asset_dir_path, candidate, selection.source.file, recipe_identity_hash(recipe)
            ):
                state = DerivativeState.CURRENT
                output_filename = candidate

        statuses.append(
            DerivativeStatus(
                derivative_type=selection.derivative_type,
                state=state,
                source=selection.source,
                reason=selection.reason,
                output_filename=output_filename,
            )
        )
    return statuses


def count_derivative_states(
    assets: list[Asset], root: Path, config: CatalogConfig
) -> DerivativeStateCounts:
    """``vpress status``'s missing/impossible tally, disk-aware: a generated,
    current derivative does not count as missing (issue #23)."""
    return tally_derivative_states(
        status.state
        for asset in assets
        for status in asset_derivative_statuses(asset, asset_dir(root, config, asset.id))
    )


class GenerationOutcome(StrEnum):
    """One derivative's outcome from a ``vpress generate`` run (issue #23)."""

    GENERATED = "generated"
    CURRENT = "current"
    IMPOSSIBLE = "impossible"
    NO_GENERATOR = "no generator"


@dataclass(frozen=True)
class GenerationResult:
    """One reported line of a ``vpress generate`` run: which asset, which
    derivative type, what happened, and the filename (generated/current) or
    reason (impossible) -- empty for ``no generator``."""

    asset_id: str
    derivative_type: DerivativeType
    outcome: GenerationOutcome
    detail: str


def _generate_one(asset: Asset, recipe: Recipe, source: Source, asset_dir_path: Path) -> str:
    """Run ``recipe``'s generator against ``source`` and persist the result
    with provenance (§35, §36). Returns the output filename.

    ``catalog.provenance.read_source_bytes`` is the only source read; the
    generator itself takes those bytes and never touches the filesystem
    (ADR 0006).
    """
    assert recipe.generator is not None
    generator = get_generator(recipe.generator)
    assert generator is not None, f"recipe names an unregistered generator: {recipe.generator!r}"

    source_bytes = read_source_bytes(asset_dir_path, source.file)
    output = generator(source_bytes, recipe.parameters)
    filename = derivative_filename(asset.display_name, recipe.derivative_type)

    provenance = Provenance(
        source_file=source.file,
        source_hash=sha256_bytes(source_bytes),
        derivative_type=recipe.derivative_type.value,
        generator=recipe.generator,
        parameters=dict(recipe.parameters),
        recipe_hash=recipe_identity_hash(recipe),
        generator_versions={"vectorpress": __version__, **output.library_versions},
        output_file=filename,
        output_hash=sha256_bytes(output.output_bytes),
    )
    write_derivative(asset_dir_path / DERIVED_DIRNAME, filename, output.output_bytes, provenance)
    return filename


def generate_asset(asset: Asset, asset_dir_path: Path) -> list[GenerationResult]:
    """Generate every recipe-bearing derivative type for one asset (issue
    #23's ``vpress generate <asset_id>``).

    Current derivatives are skipped without any write (§36); a type with no
    recipe-selectable source is reported ``impossible``; a recipe-bearing
    type with no generator yet is reported ``no generator`` and skipped.
    """
    results: list[GenerationResult] = []
    for status in asset_derivative_statuses(asset, asset_dir_path):
        recipe = RECIPES[status.derivative_type]

        if status.state is DerivativeState.IMPOSSIBLE:
            outcome = GenerationOutcome.IMPOSSIBLE
            detail = status.reason or ""
        elif status.state is DerivativeState.CURRENT:
            outcome = GenerationOutcome.CURRENT
            detail = status.output_filename or ""
        elif recipe.generator is None:
            outcome = GenerationOutcome.NO_GENERATOR
            detail = ""
        else:
            assert status.source is not None  # MISSING always carries a selected source
            outcome = GenerationOutcome.GENERATED
            detail = _generate_one(asset, recipe, status.source, asset_dir_path)

        results.append(
            GenerationResult(
                asset_id=asset.id,
                derivative_type=status.derivative_type,
                outcome=outcome,
                detail=detail,
            )
        )
    return results
