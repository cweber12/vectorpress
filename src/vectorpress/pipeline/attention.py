"""The attention report: everything in a catalog that needs a human, grouped
by kind (§34, §24, CONTEXT.md "Attention report / Inbox": "the single list
of everything needing a human... Empty inbox = publishable catalog. The CLI
and UI show the same one").

Below ``cli`` (CLAUDE.md's layering guardrail), so a future ``ui`` (PRD 9)
and PRD 8's later additions (proposed updates, needs-rebuild products) plug
into the same model -- this module decides *what* needs attention;
``vpress attention`` only renders it and names the command that resolves
each item.

Reuses every existing per-(asset, derivative type) answer instead of
re-deriving it: :func:`~vectorpress.pipeline.generate.asset_derivative_statuses`
for derivative state, :func:`~vectorpress.catalog.overrides.effective_derivative`/
:func:`~vectorpress.catalog.overrides.effective_derivative_status` for the
effective review status, :func:`~vectorpress.catalog.overrides.override_currency`
for override staleness, and :func:`~vectorpress.pipeline.eligibility.
asset_eligibility_for` for blocking reasons and warnings -- the same
functions ``vpress asset`` and ``vpress status`` already call.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.collection_resolution import resolve_collections
from vectorpress.catalog.findings import read_findings_report
from vectorpress.catalog.load import LoadedCatalog
from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.catalog.overrides import (
    effective_derivative,
    effective_derivative_status,
    override_currency,
    read_override_bytes,
)
from vectorpress.catalog.provenance import DERIVED_DIRNAME
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.eligibility import (
    ASSET_LEVEL_BLOCKING_REASON_KINDS,
    BlockingReason,
    Eligibility,
)
from vectorpress.domain.finding import ValidationOutcome
from vectorpress.domain.recipe import RECIPES
from vectorpress.domain.status import Status
from vectorpress.pipeline.eligibility import asset_eligibility_for, possible_derivative_types
from vectorpress.pipeline.generate import asset_derivative_statuses


@dataclass(frozen=True)
class NeedsReviewItem:
    """One effective derivative whose status is not ``approved`` (§10):
    ``findings`` is the cut file's own pass/needs-review roll-up for
    ``cut_svg``, ``None`` for every other type and for a ``cut_svg`` that
    has never been validated."""

    asset_id: str
    derivative_type: DerivativeType
    status: Status
    note: str | None
    findings: ValidationOutcome | None


@dataclass(frozen=True)
class StaleOverrideItem:
    """One override whose edited-against source has changed (§22.2)."""

    asset_id: str
    derivative_type: DerivativeType
    reason: str


@dataclass(frozen=True)
class BlockedAssetItem:
    """One asset blocked by an asset-level condition -- rights or accuracy
    status (§10.1) -- with every such reason. Per-derivative non-approval is
    never repeated here: it is already a :class:`NeedsReviewItem`."""

    asset_id: str
    reasons: list[BlockingReason]


@dataclass(frozen=True)
class MissingDerivativeItem:
    """One derivative type that could exist for this asset but does not
    match what is currently selected and on disk: ``state`` is ``MISSING``
    (never generated, ``reason`` is ``None``) or ``STALE`` (generated once,
    but its provenance no longer matches -- ``reason`` names why, one of
    :data:`~vectorpress.catalog.provenance.SOURCE_CHANGED`,
    :data:`~vectorpress.catalog.provenance.RECIPE_CHANGED`,
    :data:`~vectorpress.catalog.provenance.OUTPUT_CHANGED_ON_DISK`).
    ``impossible`` types are never reported: nothing can ever fill them."""

    asset_id: str
    derivative_type: DerivativeType
    state: DerivativeState
    reason: str | None


@dataclass(frozen=True)
class WarningItem:
    """One asset's non-blocking warnings (§10.1: accuracy not reviewed,
    missing optional metadata) -- listed separately from every blocking
    kind and never counted toward :attr:`AttentionReport.is_empty`."""

    asset_id: str
    messages: list[str]


class AssetPublicationState(StrEnum):
    """Which §34 bucket one loaded asset falls into: every possible
    derivative approved and no asset-level block (``APPROVED``), an
    asset-level rights/accuracy block (``BLOCKED``, the same partition
    :class:`BlockedAssetItem` reports), or blocked only by an unapproved
    derivative (``AWAITING_REVIEW``) -- already visible as a
    :class:`NeedsReviewItem`. Every loaded asset falls into exactly one."""

    APPROVED = "approved"
    AWAITING_REVIEW = "awaiting_review"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AssetPublicationCounts:
    """How many loaded assets fall into each :class:`AssetPublicationState`
    (§34's "approved assets", "assets awaiting review", "assets blocked
    from publication") -- ``vpress status``'s own counts, built from the
    same classification :func:`build_attention_report` uses for
    :attr:`AttentionReport.blocked_assets`, so the two commands agree."""

    approved: int
    awaiting_review: int
    blocked: int


@dataclass(frozen=True)
class AttentionReport:
    """Everything in one loaded catalog that needs a human, grouped by kind,
    in a deterministic order (assets in ID order, derivative types in
    :data:`~vectorpress.domain.recipe.RECIPES` declaration order -- the same
    order every other per-asset traversal in this codebase already uses)."""

    needs_review: list[NeedsReviewItem]
    stale_overrides: list[StaleOverrideItem]
    blocked_assets: list[BlockedAssetItem]
    missing_derivatives: list[MissingDerivativeItem]
    missing_metadata: list[MetadataProblem]
    warnings: list[WarningItem]
    asset_publication_counts: AssetPublicationCounts

    @property
    def is_empty(self) -> bool:
        """Whether nothing needs a human (CONTEXT.md "empty inbox =
        publishable catalog"): warnings never count, since a warning never
        blocks anything (§10.1)."""
        return not (
            self.needs_review
            or self.stale_overrides
            or self.blocked_assets
            or self.missing_derivatives
            or self.missing_metadata
        )


def _cut_file_findings_result(
    asset_dir_path: Path, output_filename: str, is_override: bool
) -> ValidationOutcome | None:
    """The last-recorded pass/needs-review roll-up for one cut file, or
    ``None`` if it has never been validated at this path. Reads whatever
    report is on disk without checking it is still current against the
    file's own bytes (``vpress asset``'s own findings column does that, via
    :func:`~vectorpress.catalog.findings.findings_currency`) -- the
    attention report's own needs-review line already flags this derivative
    regardless of whether its findings report happens to be stale too."""
    report = read_findings_report(
        asset_dir_path / DERIVED_DIRNAME, output_filename, is_override=is_override
    )
    return None if report is None else report.result


def _needs_review_items(
    asset: Asset, asset_dir_path: Path, config: CatalogConfig
) -> list[NeedsReviewItem]:
    items: list[NeedsReviewItem] = []
    for status in asset_derivative_statuses(asset, asset_dir_path, config):
        if status.state not in (DerivativeState.CURRENT, DerivativeState.STALE):
            continue
        assert status.output_filename is not None  # CURRENT/STALE always carry a filename
        effective = effective_derivative(asset_dir_path, status.output_filename)
        assert effective is not None  # CURRENT/STALE means the generated file exists on disk
        record = effective_derivative_status(asset_dir_path, status.derivative_type, effective)
        if record.status is Status.APPROVED:
            continue

        findings = None
        if status.derivative_type is DerivativeType.CUT_SVG:
            findings = _cut_file_findings_result(
                asset_dir_path, status.output_filename, effective.is_override
            )
        items.append(
            NeedsReviewItem(
                asset_id=asset.id,
                derivative_type=status.derivative_type,
                status=record.status,
                note=record.note,
                findings=findings,
            )
        )
    return items


def _missing_derivative_items(
    asset: Asset, asset_dir_path: Path, config: CatalogConfig
) -> list[MissingDerivativeItem]:
    return [
        MissingDerivativeItem(
            asset_id=asset.id,
            derivative_type=status.derivative_type,
            state=status.state,
            reason=status.reason,
        )
        for status in asset_derivative_statuses(asset, asset_dir_path, config)
        if status.state in (DerivativeState.MISSING, DerivativeState.STALE)
    ]


def _stale_override_items(asset: Asset, asset_dir_path: Path) -> list[StaleOverrideItem]:
    """Every stale override across every recipe-bearing type for one asset
    (§22.2) -- the same per-type scan :func:`~vectorpress.pipeline.
    override_resolution.count_stale_overrides` uses to tally them, widened
    here to also carry each one's reason."""
    items: list[StaleOverrideItem] = []
    for derivative_type, recipe in RECIPES.items():
        filename = derivative_filename(asset.display_name, derivative_type)
        override_bytes = read_override_bytes(asset_dir_path, filename)
        if override_bytes is None:
            continue
        currency = override_currency(asset, asset_dir_path, recipe, filename)
        if currency is not None and currency.state is DerivativeState.STALE:
            assert currency.reason is not None  # STALE always carries a reason
            items.append(StaleOverrideItem(asset.id, derivative_type, currency.reason))
    return items


@dataclass(frozen=True)
class _AssetEligibilityOutcome:
    state: AssetPublicationState
    blocked: BlockedAssetItem | None
    warning: WarningItem | None


def _classify_asset(
    asset: Asset, asset_dir_path: Path, config: CatalogConfig
) -> _AssetEligibilityOutcome:
    """One asset's §34 bucket, plus its :class:`BlockedAssetItem` and
    :class:`WarningItem` when it has one -- computed together since both
    come from the same :func:`~vectorpress.pipeline.eligibility.
    asset_eligibility_for` call, evaluated against every derivative type
    this asset can have (§10.1's own rule for publication eligibility)."""
    types = possible_derivative_types(asset, asset_dir_path, config)
    result = asset_eligibility_for(asset, asset_dir_path, types, config)

    asset_level_reasons = [
        reason
        for reason in result.blocking_reasons
        if reason.kind in ASSET_LEVEL_BLOCKING_REASON_KINDS
    ]
    warning = WarningItem(asset.id, result.warnings) if result.warnings else None

    if asset_level_reasons:
        return _AssetEligibilityOutcome(
            AssetPublicationState.BLOCKED, BlockedAssetItem(asset.id, asset_level_reasons), warning
        )
    if result.eligibility is Eligibility.ELIGIBLE:
        return _AssetEligibilityOutcome(AssetPublicationState.APPROVED, None, warning)
    return _AssetEligibilityOutcome(AssetPublicationState.AWAITING_REVIEW, None, warning)


def build_attention_report(catalog: LoadedCatalog, root: Path) -> AttentionReport:
    """Build the attention report for one loaded catalog (§34, §24).

    ``catalog.config`` is ``None`` only when ``catalog.toml`` itself failed
    to load (:class:`~vectorpress.catalog.load.LoadedCatalog`): nothing
    derivative-shaped can be resolved then, so every group but
    ``missing_metadata`` (``catalog.problems``, which already names the
    broken ``catalog.toml``) is empty.

    ``missing_metadata`` also carries every collection's reference problems
    (an asset ID in ``membership.asset_ids`` that no loaded asset has,
    §11): a reference problem is not a load-time metadata problem, but it
    is rendered the same way and belongs in the same "needs a human" kind.
    """
    needs_review: list[NeedsReviewItem] = []
    stale_overrides: list[StaleOverrideItem] = []
    missing_derivatives: list[MissingDerivativeItem] = []
    blocked_assets: list[BlockedAssetItem] = []
    warnings: list[WarningItem] = []
    reference_problems: list[MetadataProblem] = []
    approved_count = 0
    awaiting_review_count = 0

    if catalog.config is not None:
        known_asset_ids = {asset.id for asset in catalog.assets}
        for resolved in resolve_collections(catalog.collections, catalog.config, known_asset_ids):
            reference_problems.extend(resolved.reference_problems)

        for asset in catalog.assets:
            asset_dir_path = asset_dir(root, catalog.config, asset.id)
            needs_review.extend(_needs_review_items(asset, asset_dir_path, catalog.config))
            stale_overrides.extend(_stale_override_items(asset, asset_dir_path))
            missing_derivatives.extend(
                _missing_derivative_items(asset, asset_dir_path, catalog.config)
            )

            outcome = _classify_asset(asset, asset_dir_path, catalog.config)
            if outcome.blocked is not None:
                blocked_assets.append(outcome.blocked)
            if outcome.warning is not None:
                warnings.append(outcome.warning)
            if outcome.state is AssetPublicationState.APPROVED:
                approved_count += 1
            elif outcome.state is AssetPublicationState.AWAITING_REVIEW:
                awaiting_review_count += 1

    return AttentionReport(
        needs_review=needs_review,
        stale_overrides=stale_overrides,
        blocked_assets=blocked_assets,
        missing_derivatives=missing_derivatives,
        missing_metadata=[*catalog.problems, *reference_problems],
        warnings=warnings,
        asset_publication_counts=AssetPublicationCounts(
            approved=approved_count,
            awaiting_review=awaiting_review_count,
            blocked=len(blocked_assets),
        ),
    )
