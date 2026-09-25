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
from vectorpress.catalog.overrides import (
    effective_derivative,
    effective_derivative_status,
    ensure_override_provenance,
    write_override_status,
)
from vectorpress.catalog.provenance import DERIVED_DIRNAME, sha256_bytes
from vectorpress.catalog.status import write_status
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import RECIPES
from vectorpress.domain.status import Status, StatusRecord
from vectorpress.pipeline.generate import asset_derivative_statuses, reviewable_output_filename


def _reviewable_output_hash(
    asset: Asset,
    asset_dir_path: Path,
    derivative_type: DerivativeType,
    config: CatalogConfig | None,
) -> tuple[str | None, bool, str | None]:
    """The output hash of the *effective* derivative of ``derivative_type``
    to write a status against, whether it is an override, or the reason it
    cannot be reviewed right now (§6.8, §10): shared by
    :func:`approve_derivative`, :func:`reject_derivative` and
    :func:`regenerate_derivative`, since all three need the same answer to
    "does this derivative have a file to attach a status to, and which
    status store does that status belong in."

    A derivative type with no recipe yet, or one whose *generated* file is
    ``missing`` or ``impossible`` for this asset, has no output file -- an
    error, even when an override happens to sit under ``overrides/`` with no
    generated counterpart (:func:`~vectorpress.pipeline.generate.
    reviewable_output_filename` gates reviewability on the generated file's
    own state, the same as before overrides existed). A ``current`` or
    ``stale`` generated derivative can be reviewed; when an override is
    present for it, this resolves to the override instead (CONTEXT.md
    "Effective derivative") and, as a side effect, records the override's
    provenance the first time it is seen (:func:`~vectorpress.
    catalog.overrides.ensure_override_provenance`).
    """
    output_filename, error = reviewable_output_filename(
        asset, asset_dir_path, derivative_type, config
    )
    if output_filename is None:
        assert error is not None  # reviewable_output_filename always pairs one with the other
        return None, False, error

    effective = effective_derivative(asset_dir_path, output_filename)
    assert effective is not None  # CURRENT/STALE means the generated file exists on disk

    if effective.is_override:
        ensure_override_provenance(
            asset, asset_dir_path, RECIPES[derivative_type], output_filename, effective.bytes
        )
    return sha256_bytes(effective.bytes), effective.is_override, None


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
    hash, with ``note`` if given, replacing any previous note.

    A derivative type with no recipe yet, or one that is ``missing`` or
    ``impossible`` for this asset, has no output file to approve -- an
    error, nothing written. Approving a repeat of an already-approved,
    unchanged derivative writes nothing new (the same idempotence
    :func:`~vectorpress.catalog.status.write_status` gives every status
    write). When an override exists, this approves *it* instead of the
    generated file (§6.8, CONTEXT.md "Effective derivative"), writing to
    the override's own status store
    (:func:`~vectorpress.catalog.overrides.write_override_status`) so the
    generated file's own status is untouched.
    """
    output_hash, is_override, error = _reviewable_output_hash(
        asset, asset_dir_path, derivative_type, config
    )
    if output_hash is None:
        assert error is not None  # _reviewable_output_hash always pairs one with the other
        return ApproveResult(ApproveOutcome.ERROR, error)

    record = StatusRecord(status=Status.APPROVED, note=note, output_hash=output_hash)
    derived_dir = asset_dir_path / DERIVED_DIRNAME
    if is_override:
        write_override_status(derived_dir, derivative_type, record)
    else:
        write_status(derived_dir, derivative_type, record)
    return ApproveResult(ApproveOutcome.APPROVED, None)


class RejectOutcome(StrEnum):
    """One ``vpress reject`` outcome -- the same two cases as
    :class:`ApproveOutcome`, for the ``rejected`` status instead."""

    REJECTED = "rejected"
    ERROR = "error"


@dataclass(frozen=True)
class RejectResult:
    """The outcome of one reject attempt. ``error`` is set exactly when
    ``outcome`` is :attr:`RejectOutcome.ERROR`, naming why nothing was
    written."""

    outcome: RejectOutcome
    error: str | None


def reject_derivative(
    asset: Asset,
    asset_dir_path: Path,
    derivative_type: DerivativeType,
    note: str | None,
    config: CatalogConfig | None = None,
) -> RejectResult:
    """Reject one asset's derivative of ``derivative_type`` (§10): writes a
    ``rejected`` status record against the derivative's current output
    hash, with ``note`` if given, replacing any previous note.

    Same eligibility as :func:`approve_derivative`: a derivative type with
    no recipe yet, or one that is ``missing`` or ``impossible``, is an
    error, nothing written. Same effective-derivative targeting too: an
    override, when present, is what gets rejected.
    """
    output_hash, is_override, error = _reviewable_output_hash(
        asset, asset_dir_path, derivative_type, config
    )
    if output_hash is None:
        assert error is not None  # _reviewable_output_hash always pairs one with the other
        return RejectResult(RejectOutcome.ERROR, error)

    record = StatusRecord(status=Status.REJECTED, note=note, output_hash=output_hash)
    derived_dir = asset_dir_path / DERIVED_DIRNAME
    if is_override:
        write_override_status(derived_dir, derivative_type, record)
    else:
        write_status(derived_dir, derivative_type, record)
    return RejectResult(RejectOutcome.REJECTED, None)


class RegenerateOutcome(StrEnum):
    """One ``vpress regenerate`` outcome -- the same two cases as
    :class:`ApproveOutcome`, for the ``regenerate`` status instead."""

    REGENERATE = "regenerate"
    ERROR = "error"


@dataclass(frozen=True)
class RegenerateResult:
    """The outcome of one mark-for-regeneration attempt. ``error`` is set
    exactly when ``outcome`` is :attr:`RegenerateOutcome.ERROR`, naming why
    nothing was written."""

    outcome: RegenerateOutcome
    error: str | None


def regenerate_derivative(
    asset: Asset,
    asset_dir_path: Path,
    derivative_type: DerivativeType,
    note: str | None,
    config: CatalogConfig | None = None,
) -> RegenerateResult:
    """Mark one asset's derivative of ``derivative_type`` for regeneration
    (§24): writes a ``regenerate`` status record against the derivative's
    current output hash, with ``note`` if given, replacing any previous
    note. Does **not** regenerate anything itself -- the next
    ``vpress generate`` for this asset treats a ``regenerate``-marked
    derivative as due for generation even when it is ``current``, as if
    ``--force`` applied to that derivative alone
    (:func:`~vectorpress.pipeline.generate.generate_asset`), and the
    derivative ends up ``needs_review`` afterward whether or not its bytes
    changed (:func:`~vectorpress.domain.status.status_after_generation`).

    Same eligibility as :func:`approve_derivative`: a derivative type with
    no recipe yet, or one that is ``missing`` or ``impossible``, is an
    error, nothing written. Same effective-derivative targeting too: marking
    an overridden type for regeneration marks the override's own status --
    it does not force the override itself to be regenerated (overrides are
    never overwritten, §6.8); ``vpress generate`` only ever reads the
    *generated* file's own status (:func:`~vectorpress.pipeline.generate.
    _regenerate_requested`), never ``overrides/``.
    """
    output_hash, is_override, error = _reviewable_output_hash(
        asset, asset_dir_path, derivative_type, config
    )
    if output_hash is None:
        assert error is not None  # _reviewable_output_hash always pairs one with the other
        return RegenerateResult(RegenerateOutcome.ERROR, error)

    record = StatusRecord(status=Status.REGENERATE, note=note, output_hash=output_hash)
    derived_dir = asset_dir_path / DERIVED_DIRNAME
    if is_override:
        write_override_status(derived_dir, derivative_type, record)
    else:
        write_status(derived_dir, derivative_type, record)
    return RegenerateResult(RegenerateOutcome.REGENERATE, None)


@dataclass(frozen=True)
class ReviewTarget:
    """One (asset, derivative type) a bulk approve/reject/regenerate should
    act on."""

    asset: Asset
    derivative_type: DerivativeType


@dataclass(frozen=True)
class SkippedTarget:
    """One (asset, derivative type) a bulk approve/reject/regenerate left
    untouched, and why -- never a failure (§10, §24: "skipped and named,
    never failed on")."""

    asset_id: str
    derivative_type: DerivativeType
    reason: str


@dataclass(frozen=True)
class TargetSelection:
    """What a bulk approve/reject/regenerate should act on
    (:attr:`targets`), and what it is leaving alone and why
    (:attr:`skipped`)."""

    targets: list[ReviewTarget]
    skipped: list[SkippedTarget]


def select_review_targets(
    assets: Iterable[Asset],
    root: Path,
    config: CatalogConfig,
    *,
    derivative_type: DerivativeType | None = None,
    status: Status | None = None,
) -> TargetSelection:
    """Every (asset, derivative type) a bulk approve/reject/regenerate acts
    on, across ``assets`` (§10, §24) -- the targeting shape ``approve``,
    ``reject`` and ``regenerate`` share: one asset's every existing
    derivative (``assets`` holding just that one asset, ``derivative_type``
    ``None``), or the whole catalog (``assets`` holding every loaded asset),
    optionally narrowed to one ``derivative_type`` and/or one current
    ``status``.

    Below ``cli`` (CLAUDE.md's layering guardrail) so a future ``ui`` calls
    the same function; ``assets`` is exactly what the caller already
    resolved (asset lookup and "failed to load" reporting stay the CLI's
    job, the same as ``vpress generate --all``'s).

    A derivative that is ``missing`` or ``impossible`` for its asset is
    named in :attr:`TargetSelection.skipped`, never a failure. So is
    ``derivative_type`` itself when it names a type with no recipe yet --
    one skip entry per asset in scope, the bulk equivalent of the "has no
    recipe yet" error a single-target action gives. ``status`` narrows to
    derivatives whose *current* status (ADR 0004's "status follows the
    bytes", the same computation ``vpress asset`` displays) matches -- the
    override's own status when one is present (CONTEXT.md "Effective
    derivative"), else the generated file's; a derivative excluded by
    ``status`` is not named -- narrowing further is not a problem to report,
    unlike missing or impossible.
    """
    targets: list[ReviewTarget] = []
    skipped: list[SkippedTarget] = []
    type_has_recipe = derivative_type is None or derivative_type in RECIPES

    for asset in assets:
        if not type_has_recipe:
            assert derivative_type is not None  # type_has_recipe is only False when it is set
            skipped.append(SkippedTarget(asset.id, derivative_type, "has no recipe yet"))
            continue

        asset_dir_path = asset_dir(root, config, asset.id)
        for derivative_status in asset_derivative_statuses(asset, asset_dir_path, config):
            if (
                derivative_type is not None
                and derivative_status.derivative_type is not derivative_type
            ):
                continue
            if derivative_status.state not in (DerivativeState.CURRENT, DerivativeState.STALE):
                skipped.append(
                    SkippedTarget(
                        asset.id, derivative_status.derivative_type, derivative_status.state.value
                    )
                )
                continue

            assert derivative_status.output_filename is not None  # CURRENT/STALE carry a filename
            if status is not None:
                effective = effective_derivative(asset_dir_path, derivative_status.output_filename)
                assert (
                    effective is not None
                )  # CURRENT/STALE means the generated file exists on disk
                record = effective_derivative_status(
                    asset_dir_path, derivative_status.derivative_type, effective
                )
                if record.status is not status:
                    continue

            targets.append(ReviewTarget(asset, derivative_status.derivative_type))

    return TargetSelection(targets=targets, skipped=skipped)


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
    does for state counts. An overridden type counts the override's own
    status (CONTEXT.md "Effective derivative"), not the generated file's.
    """
    counts = dict.fromkeys(Status, 0)
    for asset in assets:
        asset_dir_path = asset_dir(root, config, asset.id)
        for status in asset_derivative_statuses(asset, asset_dir_path, config):
            if status.state not in (DerivativeState.CURRENT, DerivativeState.STALE):
                continue
            assert status.output_filename is not None  # CURRENT/STALE always carry a filename
            effective = effective_derivative(asset_dir_path, status.output_filename)
            assert effective is not None  # CURRENT/STALE means the generated file exists on disk
            record = effective_derivative_status(asset_dir_path, status.derivative_type, effective)
            counts[record.status] += 1
    return StatusCounts(
        needs_review=counts[Status.NEEDS_REVIEW],
        approved=counts[Status.APPROVED],
        rejected=counts[Status.REJECTED],
        regenerate=counts[Status.REGENERATE],
    )
