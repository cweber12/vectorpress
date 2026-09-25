"""Human review actions on derivatives (§10, §22.1, ADR 0004, ADR 0005).

Orchestrates :mod:`vectorpress.catalog.status` the way
:mod:`vectorpress.pipeline.generate` orchestrates
:mod:`vectorpress.catalog.provenance` (ADR 0006's "catalog... the only layer
touching catalog files"): this module decides which derivative a review
action applies to and whether it is currently reviewable; ``catalog.status``
persists the record. Both ``cli`` and a future ``ui`` call this module, so
"can this derivative be approved right now" is answered in exactly one
place.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_derivative_bytes, sha256_bytes
from vectorpress.catalog.status import asset_derivative_status, write_status
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.status import Status, StatusRecord
from vectorpress.pipeline.generate import asset_derivative_statuses


class ApproveOutcome(StrEnum):
    """One ``vpress approve`` outcome: ``APPROVED`` on success, ``ERROR``
    when nothing was written -- an unknown derivative type, or one that is
    ``missing`` or ``impossible`` for this asset (no output file exists to
    approve)."""

    APPROVED = "approved"
    ERROR = "error"


@dataclass(frozen=True)
class ApproveResult:
    """The outcome of one approve attempt. ``error`` is set exactly when
    ``outcome`` is :attr:`ApproveOutcome.ERROR`, naming why nothing was
    written."""

    outcome: ApproveOutcome
    error: str | None


def approve_derivative(
    asset: Asset,
    asset_dir_path: Path,
    derivative_type: DerivativeType,
    note: str | None,
    config: CatalogConfig | None = None,
) -> ApproveResult:
    """Approve one asset's derivative of ``derivative_type`` (§10): writes
    an ``approved`` status record against the derivative's current output
    hash, with ``note`` if given.

    A derivative type with no recipe yet, or one that is ``missing`` or
    ``impossible`` for this asset, has no output file to approve -- an
    error, nothing written. A ``current`` or ``stale`` derivative (its
    output file exists either way) can be approved; approving a repeat of
    an already-approved, unchanged derivative writes nothing new (the same
    idempotence :func:`~vectorpress.catalog.status.write_status` gives
    every status write).
    """
    status = next(
        (
            s
            for s in asset_derivative_statuses(asset, asset_dir_path, config)
            if s.derivative_type is derivative_type
        ),
        None,
    )
    if status is None:
        return ApproveResult(ApproveOutcome.ERROR, f"{derivative_type.value} has no recipe yet")
    if status.state not in (DerivativeState.CURRENT, DerivativeState.STALE):
        return ApproveResult(
            ApproveOutcome.ERROR, f"{derivative_type.value} is {status.state.value}"
        )

    assert status.output_filename is not None  # CURRENT/STALE always carry a filename
    derived_dir = asset_dir_path / DERIVED_DIRNAME
    output_bytes = read_derivative_bytes(derived_dir, status.output_filename)
    assert output_bytes is not None  # CURRENT/STALE means the file exists on disk

    write_status(
        derived_dir,
        derivative_type,
        StatusRecord(status=Status.APPROVED, note=note, output_hash=sha256_bytes(output_bytes)),
    )
    return ApproveResult(ApproveOutcome.APPROVED, None)


@dataclass(frozen=True)
class StatusCounts:
    """How many existing (asset, derivative type) pairs carry each status
    (§10), across a set of loaded assets. ``generated`` is never counted:
    it is a pass-through never persisted to disk (ADR 0004,
    :class:`~vectorpress.domain.status.Status`)."""

    needs_review: int
    approved: int
    rejected: int
    regenerate: int


def count_derivative_statuses(
    assets: Iterable[Asset], root: Path, config: CatalogConfig
) -> StatusCounts:
    """Tally every existing derivative's status, across ``assets`` (§10's
    "vpress status adds counts of derivatives by status").

    Only a derivative that exists on disk (``current`` or ``stale``) has a
    status to count; ``missing`` and ``impossible`` derivatives contribute
    nothing, the same as :func:`~vectorpress.catalog.derivatives.tally_derivative_states`
    does for state counts.
    """
    counts = dict.fromkeys(Status, 0)
    for asset in assets:
        asset_dir_path = asset_dir(root, config, asset.id)
        derived_dir = asset_dir_path / DERIVED_DIRNAME
        for status in asset_derivative_statuses(asset, asset_dir_path, config):
            if status.state not in (DerivativeState.CURRENT, DerivativeState.STALE):
                continue
            assert status.output_filename is not None  # CURRENT/STALE always carry a filename
            output_bytes = read_derivative_bytes(derived_dir, status.output_filename)
            assert output_bytes is not None  # CURRENT/STALE means the file exists on disk
            record = asset_derivative_status(derived_dir, status.derivative_type, output_bytes)
            counts[record.status] += 1
    return StatusCounts(
        needs_review=counts[Status.NEEDS_REVIEW],
        approved=counts[Status.APPROVED],
        rejected=counts[Status.REJECTED],
        regenerate=counts[Status.REGENERATE],
    )
