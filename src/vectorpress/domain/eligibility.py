"""Publication eligibility: whether one asset may ship with a given set of
derivative types (§10, §10.1, ADR 0008, CONTEXT.md "Blocked", "Eligible").

No I/O here (ADR 0006): eligibility is a pure decision over already-resolved
inputs -- the asset's rights and accuracy status, its missing optional
metadata fields, and each included derivative type's state and (where it
exists) effective status. Gathering those inputs from disk is
:mod:`vectorpress.pipeline.eligibility`'s job.

§10's "unless explicitly overridden" is not decided here: nothing in this
module knows about products, so every included derivative that is not
approved blocks, with no exceptions. A later PRD that adds a product-level
override extends the caller, not this function's contract -- the seam is
:class:`EligibilityResult`'s ``blocking_reasons`` staying a plain list a
caller can filter before deciding what to show.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.status import Status

#: The §5 descriptive fields that are optional on an asset -- absent or
#: empty is a warning (§10.1's "missing optional metadata"), never a block.
#: Required fields (common name, display name, description, subject
#: category, taxonomic group, rights status, accuracy status) are never
#: missing here at all: an asset without one does not load (ADR 0005,
#: `catalog.assets`), so this list only names fields the model itself
#: allows to be empty.
OPTIONAL_METADATA_FIELDS: tuple[str, ...] = (
    "scientific_name",
    "tags",
    "regions",
    "ecosystems",
    "product_use_categories",
    "notes",
)


def missing_optional_metadata_fields(asset: Asset) -> list[str]:
    """Every :data:`OPTIONAL_METADATA_FIELDS` name this asset leaves empty
    (§5, §10.1's "missing optional metadata"), in that fixed order --
    ``scientific_name`` counts as missing when ``None``, every other field
    (a string or a list) when it is falsy."""
    return [field for field in OPTIONAL_METADATA_FIELDS if not getattr(asset, field)]


class Eligibility(StrEnum):
    """Whether an asset may ship with a given set of derivative types
    (CONTEXT.md "Eligible", "Blocked")."""

    ELIGIBLE = "eligible"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class IncludedDerivative:
    """One derivative type a candidate set of products would include: its
    current derivative state, and its *effective* status (§6.8) when it has
    one (§10, §10.1).

    ``status`` is ``None`` exactly when ``state`` is ``MISSING`` or
    ``IMPOSSIBLE`` -- nothing exists yet to have a status, and
    :func:`asset_eligibility` treats both the same as any other
    not-approved derivative. A ``CURRENT`` or ``STALE`` derivative always
    carries a status (at worst the legacy default, ``needs_review``).
    """

    derivative_type: DerivativeType
    state: DerivativeState
    status: Status | None


def _derivative_blocking_reason(included: IncludedDerivative) -> str | None:
    """The §10.1 blocking reason for one included derivative, or ``None``
    when it is approved and blocks nothing: names ``included``'s state when
    it has no output at all (``missing``/``impossible``), else its status."""
    if included.state in (DerivativeState.MISSING, DerivativeState.IMPOSSIBLE):
        return f"{included.derivative_type.value}: {included.state.value}"
    if included.status is Status.APPROVED:
        return None
    assert included.status is not None  # CURRENT/STALE always carry a status
    return f"{included.derivative_type.value}: {included.status.value.replace('_', ' ')}"


@dataclass(frozen=True)
class EligibilityResult:
    """One asset's publication eligibility for a given set of derivative
    types (§10, §10.1): eligible or blocked, every blocking reason, and
    every warning. Warnings never affect :attr:`eligibility`."""

    eligibility: Eligibility
    blocking_reasons: list[str]
    warnings: list[str]


def asset_eligibility(
    rights_status: RightsStatus,
    accuracy_status: AccuracyStatus,
    missing_metadata_fields: Sequence[str],
    included_derivatives: Sequence[IncludedDerivative],
) -> EligibilityResult:
    """Whether an asset may ship with ``included_derivatives`` (§10, §10.1).

    Blocking: rights status ``do_not_publish`` or ``rights_review_required``;
    accuracy status ``issue_found``; any included derivative not approved,
    one reason per type naming its status when it has one, else its state
    (a missing or impossible derivative counts as not approved).

    Warnings, which never block: accuracy status ``not_reviewed``; one per
    field named in ``missing_metadata_fields`` ("missing optional metadata").

    ``eligibility`` is :attr:`Eligibility.BLOCKED` iff ``blocking_reasons``
    is non-empty.
    """
    blocking_reasons: list[str] = []
    warnings: list[str] = []

    if rights_status in (RightsStatus.DO_NOT_PUBLISH, RightsStatus.RIGHTS_REVIEW_REQUIRED):
        blocking_reasons.append(f"rights status: {rights_status.value.replace('_', ' ')}")

    if accuracy_status is AccuracyStatus.ISSUE_FOUND:
        blocking_reasons.append(f"accuracy status: {accuracy_status.value.replace('_', ' ')}")
    elif accuracy_status is AccuracyStatus.NOT_REVIEWED:
        warnings.append(f"accuracy status: {accuracy_status.value.replace('_', ' ')}")

    for included in included_derivatives:
        reason = _derivative_blocking_reason(included)
        if reason is not None:
            blocking_reasons.append(reason)

    warnings.extend(f"missing optional metadata: {field}" for field in missing_metadata_fields)

    eligibility = Eligibility.BLOCKED if blocking_reasons else Eligibility.ELIGIBLE
    return EligibilityResult(eligibility, blocking_reasons, warnings)
