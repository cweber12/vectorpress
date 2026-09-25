"""Resolving a stale override: keep or discard (§22.2, ADR 0004, ADR 0005,
CONTEXT.md "Stale", "Override").

Re-edit needs no command here at all -- editing an override's bytes already
re-baselines it and returns it to ``needs_review``
(:func:`~vectorpress.catalog.overrides.ensure_override_provenance`, applied
the next time anything reads the override, e.g. ``vpress asset`` or
``vpress approve``). This module covers the other two resolutions: ``keep``
re-baselines without touching the bytes, and ``discard`` removes the
override and its tool-owned state so the generated file becomes effective
again.

Gated on the override itself, not the generated file's reviewability
(:func:`~vectorpress.pipeline.generate.reviewable_output_filename`): an
override can exist -- and be kept or discarded -- even when nothing has
ever been generated for its type (CONTEXT.md "Override": "nothing requires
generation first").
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.overrides import (
    delete_override_findings,
    delete_override_provenance,
    delete_override_status,
    discard_override_file,
    ensure_override_provenance,
    override_currency,
    override_path,
    read_override_bytes,
    rebaseline_override_source,
)
from vectorpress.catalog.provenance import DERIVED_DIRNAME
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.recipe import RECIPES


def _override_bytes_or_error(
    asset: Asset, asset_dir_path: Path, derivative_type: DerivativeType
) -> tuple[str | None, bytes | None, str | None]:
    """The override's filename and bytes for (``asset``, ``derivative_type``),
    or the reason there is nothing to act on: a type with no recipe yet, or
    one with no override sitting under ``overrides/`` at all. Shared by
    :func:`keep_override` and :func:`discard_override` (§22.2), the same
    "what to act on, or why not" split :func:`~vectorpress.pipeline.generate.
    reviewable_output_filename` gives approve/reject/regenerate/open."""
    if derivative_type not in RECIPES:
        return None, None, f"{derivative_type.value} has no recipe yet"

    filename = derivative_filename(asset.display_name, derivative_type)
    override_bytes = read_override_bytes(asset_dir_path, filename)
    if override_bytes is None:
        return None, None, f"{derivative_type.value} has no override"
    return filename, override_bytes, None


class KeepOutcome(StrEnum):
    """One ``vpress override keep`` outcome: ``KEPT`` re-baselined a stale
    override, ``NOT_STALE`` found nothing to do, ``ERROR`` when there is no
    override to act on."""

    KEPT = "kept"
    NOT_STALE = "not stale"
    ERROR = "error"


@dataclass(frozen=True)
class KeepResult:
    """The outcome of one ``vpress override keep`` attempt. ``error`` is set
    exactly when ``outcome`` is :attr:`KeepOutcome.ERROR`."""

    outcome: KeepOutcome
    error: str | None


def keep_override(
    asset: Asset, asset_dir_path: Path, derivative_type: DerivativeType
) -> KeepResult:
    """Keep one asset's override of ``derivative_type`` as-is against a
    changed source (§22.2): re-baselines its edited-against hash to the
    source currently selected for it, leaving the override's bytes and
    status untouched. A no-op, reported as such, on an override that is not
    currently stale -- including a second ``keep`` in a row, since the first
    one already moved the baseline. An unknown derivative type or one with
    no override at all is an error, nothing written.
    """
    filename, override_bytes, error = _override_bytes_or_error(
        asset, asset_dir_path, derivative_type
    )
    if filename is None:
        assert error is not None  # _override_bytes_or_error always pairs one with the other
        return KeepResult(KeepOutcome.ERROR, error)
    assert override_bytes is not None  # paired with filename

    recipe = RECIPES[derivative_type]
    # A hand-dropped override no command has touched yet has no baseline to
    # compare against -- give it one before asking whether it is stale.
    ensure_override_provenance(asset, asset_dir_path, recipe, filename, override_bytes)
    currency = override_currency(asset, asset_dir_path, recipe, filename)
    if currency is None or currency.state is not DerivativeState.STALE:
        return KeepResult(KeepOutcome.NOT_STALE, None)

    rebaseline_override_source(asset, asset_dir_path, recipe, filename, override_bytes)
    return KeepResult(KeepOutcome.KEPT, None)


class DiscardOutcome(StrEnum):
    """One ``vpress override discard`` outcome: ``DISCARDED`` removed the
    override, ``WOULD_DISCARD`` reported what removing it would do without
    ``--yes``, ``ERROR`` when there is no override to discard."""

    DISCARDED = "discarded"
    WOULD_DISCARD = "would discard"
    ERROR = "error"


@dataclass(frozen=True)
class DiscardResult:
    """The outcome of one ``vpress override discard`` attempt. ``error`` is
    set exactly when ``outcome`` is :attr:`DiscardOutcome.ERROR`.
    ``override_file`` is the override's path, set whenever one exists to
    discard (``DISCARDED`` and ``WOULD_DISCARD``) -- what
    ``WOULD_DISCARD`` reports without removing anything."""

    outcome: DiscardOutcome
    error: str | None
    override_file: Path | None


def discard_override(
    asset: Asset, asset_dir_path: Path, derivative_type: DerivativeType, *, confirmed: bool
) -> DiscardResult:
    """Discard one asset's override of ``derivative_type`` (§22.2): removes
    the override file, its provenance, its status and its findings report,
    so the generated file becomes the effective derivative again with its
    own status and findings. The one deletion the tool ever makes under
    ``overrides/`` (CONTEXT.md "Override"), made only on this explicit,
    confirmed request.

    ``confirmed=False`` (no ``--yes``) writes nothing and reports
    ``WOULD_DISCARD`` with the override's path, so the caller can print what
    removing it would do. An unknown derivative type or one with no override
    at all is an error, nothing written, whether or not ``confirmed``.
    """
    filename, _override_bytes, error = _override_bytes_or_error(
        asset, asset_dir_path, derivative_type
    )
    if filename is None:
        assert error is not None  # _override_bytes_or_error always pairs one with the other
        return DiscardResult(DiscardOutcome.ERROR, error, None)

    path = override_path(asset_dir_path, filename)
    if not confirmed:
        return DiscardResult(DiscardOutcome.WOULD_DISCARD, None, path)

    derived_dir = asset_dir_path / DERIVED_DIRNAME
    discard_override_file(asset_dir_path, filename)
    delete_override_provenance(derived_dir, filename)
    delete_override_status(derived_dir, derivative_type)
    delete_override_findings(derived_dir, filename)
    return DiscardResult(DiscardOutcome.DISCARDED, None, path)


def count_stale_overrides(assets: Iterable[Asset], root: Path, config: CatalogConfig) -> int:
    """How many overrides across ``assets`` are stale against the source
    they were edited against (§22.2, "vpress status counts stale
    overrides"). An override with no provenance recorded yet (never seen by
    :func:`~vectorpress.catalog.overrides.ensure_override_provenance`) has
    nothing to compare and does not count -- the same "nothing to compare
    yet" :func:`~vectorpress.catalog.overrides.override_currency` itself
    returns ``None`` for.
    """
    count = 0
    for asset in assets:
        asset_dir_path = asset_dir(root, config, asset.id)
        for derivative_type, recipe in RECIPES.items():
            filename = derivative_filename(asset.display_name, derivative_type)
            override_bytes = read_override_bytes(asset_dir_path, filename)
            if override_bytes is None:
                continue
            currency = override_currency(asset, asset_dir_path, recipe, filename)
            if currency is not None and currency.state is DerivativeState.STALE:
                count += 1
    return count
