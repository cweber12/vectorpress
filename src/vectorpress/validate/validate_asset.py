"""Per-asset orchestration for ``vpress validate`` (§9, §9.1, §35, ADR 0004,
ADR 0006, ADR 0007, ADR 0008, issue #37 fix round 1, issue #38).

:func:`validate_asset_cut_file` is the one place that decides which file one
asset's ``cut_svg`` validation runs against, reads its bytes, runs the pure
:mod:`vectorpress.validate.cut_file` detectors, and persists the result --
reading and writing only through :mod:`vectorpress.catalog` (ADR 0006's
"catalog... the only layer touching catalog files"), and never importing
:mod:`vectorpress.pipeline` (this module's own layer, ``validate``, is
``pipeline``'s independent sibling, CLAUDE.md's layering guardrail,
``pyproject.toml``'s import-linter contract). :mod:`vectorpress.cli` calls
this and only formats its result (CLAUDE.md's "cli and ui are thin") -- a
future ``ui`` can call the exact same function.

Telling ``impossible`` from ``missing`` needs only
:func:`vectorpress.catalog.derivatives.select_source` (a pure function over
an already-loaded :class:`~vectorpress.domain.asset.Asset`, no I/O of its
own) plus a direct file-existence check: ``cut_svg``'s recipe never varies
by anything ``pipeline`` computes, and this command does not care whether an
existing file is current or stale (§9's "validation runs on any SVG
derivative, not only generated ones") -- only whether one exists to check at
all.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.derivatives import select_source
from vectorpress.catalog.findings import FindingsReport, write_findings_report
from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_derivative_bytes, sha256_bytes
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.finding import ValidationResult
from vectorpress.domain.recipe import RECIPES
from vectorpress.validate.cut_file import THRESHOLDS, validate_cut_file


class AssetValidationOutcome(StrEnum):
    """What happened when validating one asset's ``cut_svg`` (issue #37 fix
    round 1). ``IMPOSSIBLE``/``MISSING`` mirror
    :class:`~vectorpress.domain.derivative_state.DerivativeState`'s own
    names for "no source qualifies" / "nothing to check yet" -- there is
    nothing to validate either way. ``VALIDATED`` means a findings report
    was computed and persisted (its own pass/needs-review result lives on
    :attr:`AssetValidationResult.validation`); ``FAILED`` means the file
    could not be parsed at all (§35)."""

    IMPOSSIBLE = "impossible"
    MISSING = "missing"
    VALIDATED = "validated"
    FAILED = "failed"


@dataclass(frozen=True)
class AssetValidationResult:
    """One asset's ``vpress validate`` outcome (issue #37 fix round 1).

    ``filename`` is set for every outcome except ``IMPOSSIBLE`` (no source
    qualifies, so there is no filename to name at all).
    ``reason`` is set for ``IMPOSSIBLE`` (why no source qualifies) and
    ``FAILED`` (the parse error). ``validation`` is set exactly when
    ``outcome`` is ``VALIDATED``.
    """

    asset_id: str
    outcome: AssetValidationOutcome
    filename: str | None = None
    reason: str | None = None
    validation: ValidationResult | None = None


def validate_asset_cut_file(
    root: Path, config: CatalogConfig, asset: Asset, reference_size_in: float
) -> AssetValidationResult:
    """Validate one asset's ``cut_svg`` at ``reference_size_in`` (§9.1),
    writing a findings report through :mod:`vectorpress.catalog.findings`
    when a file exists to check (issue #37 fix round 1).

    ``reference_size_in`` is taken explicitly, not defaulted or read from
    ``config`` internally, matching issue #37's "pass the reference size
    explicitly into validation functions" -- the caller decides which
    reference size applies, typically via :func:`vectorpress.domain.
    reference_size.resolve_reference_size_in`.

    The findings report is persisted at the catalog-default path
    (``<file>.findings.json``, unchanged from before issue #38) exactly when
    ``reference_size_in`` equals ``config.reference_size_in``; any other
    value -- a product's override -- persists at its own size-keyed path
    instead (:func:`vectorpress.catalog.findings.findings_path`'s
    ``at_size``), so the two never overwrite or invalidate each other
    (issue #38's "a findings report is per (cut file, reference size)").
    """
    recipe = RECIPES[DerivativeType.CUT_SVG]
    selection = select_source(asset, recipe)
    if selection.state is DerivativeState.IMPOSSIBLE:
        return AssetValidationResult(
            asset_id=asset.id,
            outcome=AssetValidationOutcome.IMPOSSIBLE,
            reason=selection.reason,
        )

    filename = derivative_filename(asset.display_name, DerivativeType.CUT_SVG)
    derived_dir = asset_dir(root, config, asset.id) / DERIVED_DIRNAME

    svg_bytes = read_derivative_bytes(derived_dir, filename)
    if svg_bytes is None:
        return AssetValidationResult(
            asset_id=asset.id,
            outcome=AssetValidationOutcome.MISSING,
            filename=filename,
        )

    try:
        validation = validate_cut_file(
            svg_bytes, reference_size_in, catalog_reference_size_in=config.reference_size_in
        )
    except Exception as exc:  # any parse failure is a reported §35 validation failure, not a crash
        return AssetValidationResult(
            asset_id=asset.id,
            outcome=AssetValidationOutcome.FAILED,
            filename=filename,
            reason=str(exc),
        )

    # The catalog-default path stays exactly what it was before issue #38
    # (``at_size=None``); any other reference size -- a product's override --
    # is keyed by its own value instead, so it coexists rather than
    # overwriting the catalog-default report.
    at_size = None if reference_size_in == config.reference_size_in else reference_size_in
    write_findings_report(
        derived_dir,
        FindingsReport(
            validated_file=filename,
            content_hash=sha256_bytes(svg_bytes),
            reference_size_in=reference_size_in,
            excessive_complexity_reference_size_in=config.reference_size_in,
            thresholds=dict(THRESHOLDS),
            result=validation.outcome,
            findings=validation.findings,
        ),
        at_size=at_size,
    )

    return AssetValidationResult(
        asset_id=asset.id,
        outcome=AssetValidationOutcome.VALIDATED,
        filename=filename,
        validation=validation,
    )
