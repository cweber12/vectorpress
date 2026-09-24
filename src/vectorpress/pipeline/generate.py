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
    derivative_currency,
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
    ``CURRENT`` or ``STALE`` where a provenance record and output file
    already exist on disk (issue #23, issue #26).

    ``output_filename`` is set exactly when ``state`` is ``CURRENT`` or
    ``STALE`` (both mean the file exists on disk; ``STALE`` just means it no
    longer matches). ``reason`` is set exactly when ``state`` is
    ``IMPOSSIBLE`` (why no source qualifies -- see
    :func:`~vectorpress.catalog.derivatives.select_source`) or ``STALE``
    (one of :data:`~vectorpress.catalog.provenance.SOURCE_CHANGED`,
    :data:`~vectorpress.catalog.provenance.RECIPE_CHANGED`,
    :data:`~vectorpress.catalog.provenance.OUTPUT_CHANGED_ON_DISK`).
    """

    derivative_type: DerivativeType
    state: DerivativeState
    source: Source | None
    reason: str | None
    output_filename: str | None


def asset_derivative_statuses(asset: Asset, asset_dir_path: Path) -> list[DerivativeStatus]:
    """One :class:`DerivativeStatus` per recipe-bearing derivative type, for
    one asset, upgrading :func:`~vectorpress.catalog.derivatives.select_derivatives`'s
    ``MISSING`` to ``CURRENT`` or ``STALE`` where generation has already
    produced a file for it (issue #23, issue #26).

    A type whose recipe has no generator yet can never be ``CURRENT`` or
    ``STALE``: it stays ``MISSING``, the same as before generation existed
    at all. Every type this PRD covers (``transparent_png``,
    ``silhouette_svg``, ``flatcolor_svg``) now has one; a later PRD's types
    are the ones this still applies to.
    """
    statuses: list[DerivativeStatus] = []
    for selection in select_derivatives(asset):
        recipe = RECIPES[selection.derivative_type]
        state = selection.state
        reason = selection.reason
        output_filename: str | None = None

        if state is DerivativeState.MISSING and recipe.generator is not None:
            assert selection.source is not None  # MISSING always carries a selected source
            candidate = derivative_filename(asset.display_name, recipe.derivative_type)
            currency = derivative_currency(
                asset_dir_path, candidate, selection.source.file, recipe_identity_hash(recipe)
            )
            state = currency.state
            if state is DerivativeState.STALE:
                reason = currency.reason
                output_filename = candidate
            elif state is DerivativeState.CURRENT:
                output_filename = candidate

        statuses.append(
            DerivativeStatus(
                derivative_type=selection.derivative_type,
                state=state,
                source=selection.source,
                reason=reason,
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
    """One derivative's outcome from a ``vpress generate`` run (issue #23,
    issue #24 review fix round 1, issue #26).

    ``MISSING`` is reported only under ``vpress generate --stale``: a
    derivative that has never been generated is left untouched (``--stale``
    regenerates stale derivatives, not missing ones), so it is reported
    ``missing`` rather than silently omitted.
    """

    GENERATED = "generated"
    CURRENT = "current"
    MISSING = "missing"
    IMPOSSIBLE = "impossible"
    NO_GENERATOR = "no generator"
    FAILED = "failed"


@dataclass(frozen=True)
class GenerationResult:
    """One reported line of a ``vpress generate`` run: which asset, which
    derivative type, what happened, and the filename (generated/current),
    reason (impossible/failed) -- empty for ``no generator``."""

    asset_id: str
    derivative_type: DerivativeType
    outcome: GenerationOutcome
    detail: str


class GeneratorError(Exception):
    """A generator raised while producing one derivative (issue #24 review
    fix round 1: e.g. a fully transparent silhouette source, or one made
    only of specks below ``speckle_size``, leaves ``silhouette_svg`` with no
    geometry to render).

    Deliberately wraps only a failure from the generator call itself, never
    from reading the source or writing the output: this is CONTEXT.md's
    "a derivative that exists" case gone wrong at generation time, not the
    "no acceptable source" case (``impossible``) -- §35's broader failure
    handling (undecodable sources, cleanup) is a later slice's job, not
    widened here.
    """


def _generate_one(asset: Asset, recipe: Recipe, source: Source, asset_dir_path: Path) -> str:
    """Run ``recipe``'s generator against ``source`` and persist the result
    with provenance (§35, §36). Returns the output filename.

    ``catalog.provenance.read_source_bytes`` is the only source read; the
    generator itself takes those bytes and never touches the filesystem
    (ADR 0006).

    Raises :class:`GeneratorError` if the generator itself raises --
    caught by :func:`generate_asset` so one failing derivative does not stop
    generation for the rest of the asset or catalog.
    """
    assert recipe.generator is not None
    generator = get_generator(recipe.generator)
    assert generator is not None, f"recipe names an unregistered generator: {recipe.generator!r}"

    source_bytes = read_source_bytes(asset_dir_path, source.file)
    try:
        output = generator(source_bytes, recipe.parameters)
    except Exception as exc:
        raise GeneratorError(str(exc)) from exc
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


def generate_asset(
    asset: Asset,
    asset_dir_path: Path,
    *,
    stale_only: bool = False,
    force: bool = False,
) -> list[GenerationResult]:
    """Generate every recipe-bearing derivative type for one asset (issue
    #23's ``vpress generate <asset_id>``; ``stale_only`` and ``force`` are
    issue #26's ``--stale`` and ``--force``, never both true at once -- the
    caller, ``cli.app.generate``, enforces that as a usage error).

    Default (``stale_only=False``, ``force=False``): every ``MISSING`` or
    ``STALE`` derivative is generated; ``CURRENT`` is reported and skipped
    without any write (§36); a type with no recipe-selectable source is
    reported ``impossible``; a recipe-bearing type with no generator yet is
    reported ``no generator`` and skipped.

    ``stale_only``: only ``STALE`` derivatives are generated -- ``MISSING``
    is reported (``GenerationOutcome.MISSING``) and left untouched, same as
    ``CURRENT``.

    ``force``: ``CURRENT`` derivatives are generated too (still a no-op on
    disk when the freshly generated bytes equal the recorded output hash,
    per :func:`~vectorpress.catalog.provenance.write_derivative`'s
    idempotence).

    A generator that raises (issue #24 review fix round 1) is reported
    ``failed`` with the exception's message, nothing is written for that
    derivative, and the loop continues with the next derivative type --
    one failing derivative never stops the rest of this asset, and (since
    ``cli.app.generate`` calls this per asset) never stops the rest of
    ``--all``/``--stale`` either.
    """
    results: list[GenerationResult] = []
    for status in asset_derivative_statuses(asset, asset_dir_path):
        recipe = RECIPES[status.derivative_type]

        if status.state is DerivativeState.IMPOSSIBLE:
            outcome = GenerationOutcome.IMPOSSIBLE
            detail = status.reason or ""
        elif recipe.generator is None:
            outcome = GenerationOutcome.NO_GENERATOR
            detail = ""
        elif status.state is DerivativeState.CURRENT and not force:
            outcome = GenerationOutcome.CURRENT
            detail = status.output_filename or ""
        elif status.state is DerivativeState.MISSING and stale_only:
            outcome = GenerationOutcome.MISSING
            detail = ""
        else:
            # MISSING (not stale_only) or STALE, or CURRENT under --force.
            assert status.source is not None  # MISSING/STALE/CURRENT always carry a selected source
            try:
                detail = _generate_one(asset, recipe, status.source, asset_dir_path)
                outcome = GenerationOutcome.GENERATED
            except GeneratorError as exc:
                outcome = GenerationOutcome.FAILED
                detail = str(exc)

        results.append(
            GenerationResult(
                asset_id=asset.id,
                derivative_type=status.derivative_type,
                outcome=outcome,
                detail=detail,
            )
        )
    return results
