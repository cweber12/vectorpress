"""Publication eligibility: whether one asset may ship with a given set of
derivative types (§10, §10.1, ADR 0008, CONTEXT.md "Blocked", "Eligible").

No I/O here (ADR 0006): eligibility is a pure decision over already-resolved
inputs -- the asset's rights status, licensing notes and accuracy status,
its missing optional metadata fields, and each included derivative type's
state and (where it exists) effective status. Gathering those inputs from
disk is :mod:`vectorpress.pipeline.eligibility`'s job.

§10's "unless explicitly overridden" is ``allow_unapproved``: a caller (a
per-build ``--allow-unapproved`` flag) may ask that a ``generated`` or
``needs_review`` derivative admit rather than block. It never touches a
rights, accuracy or licensing-notes block, and never admits ``rejected`` or
``regenerate`` -- a human said no, or asked for a new take -- so it is a
third outcome per included derivative, not a second implementation: see
:func:`_derivative_outcome`.

Each blocking reason is a :class:`BlockingReason` -- a kind, the derivative
type it concerns (when it concerns one), and the value driving it -- rather
than pre-rendered text: a catalog-wide attention report groups and counts
by kind (asset-level rights/accuracy blocks versus per-derivative ones),
and only ``cli`` turns a reason into a message a human reads.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.status import Status

#: Every :class:`~vectorpress.domain.status.Status` ``allow_unapproved`` may
#: admit (§10.1's "unless explicitly overridden" covers approval only): a
#: freshly generated or reviewer-pending derivative -- never ``rejected`` (a
#: human said no) or ``regenerate`` (a human asked for a new take, CONTEXT.md
#: "Status" lifecycle).
ADMISSIBLE_UNAPPROVED_STATUSES = (Status.GENERATED, Status.NEEDS_REVIEW)

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


class BlockingReasonKind(StrEnum):
    """What kind of fact is behind one :class:`BlockingReason` (§10.1):
    ``RIGHTS_STATUS``, ``ACCURACY_STATUS`` and
    ``AI_GENERATED_LICENSING_NOTES`` are asset-level -- true of the asset
    regardless of any derivative type -- while ``DERIVATIVE_STATE``
    (missing/impossible) and ``DERIVATIVE_STATUS`` (needs_review/rejected/
    regenerate) each concern one included derivative type. A catalog-wide
    attention report uses this split: an asset-level reason is worth its
    own "blocked" line, a per-derivative one is already covered by that
    derivative's own needs-review line.

    ``AI_GENERATED_LICENSING_NOTES`` is distinct from ``RIGHTS_STATUS``
    (§26): ``ai_generated`` alone never blocks, only ``ai_generated`` paired
    with empty ``licensing_notes`` does -- its own reason so a catalog-wide
    report and ``cli`` can tell "rights status blocks outright" from "rights
    status needs a licensing note" apart."""

    RIGHTS_STATUS = "rights_status"
    ACCURACY_STATUS = "accuracy_status"
    AI_GENERATED_LICENSING_NOTES = "ai_generated_licensing_notes"
    DERIVATIVE_STATE = "derivative_state"
    DERIVATIVE_STATUS = "derivative_status"


#: Every :class:`BlockingReasonKind` that is true of the asset as a whole,
#: not of one derivative type -- what an attention report's "blocked
#: assets" kind reports, and what makes an asset stay blocked even once
#: every one of its derivatives is approved (CONTEXT.md "Blocked",
#: ``gumboot_chiton`` in the fixture catalog).
ASSET_LEVEL_BLOCKING_REASON_KINDS = (
    BlockingReasonKind.RIGHTS_STATUS,
    BlockingReasonKind.ACCURACY_STATUS,
    BlockingReasonKind.AI_GENERATED_LICENSING_NOTES,
)


@dataclass(frozen=True)
class BlockingReason:
    """One reason an asset is blocked from publication (§10.1): ``kind``
    says what kind of fact it is, ``derivative_type`` names which type it
    concerns (set exactly for :attr:`BlockingReasonKind.DERIVATIVE_STATE`
    and :attr:`BlockingReasonKind.DERIVATIVE_STATUS`, ``None`` for every
    kind in :data:`ASSET_LEVEL_BLOCKING_REASON_KINDS`), and ``value`` is
    the underlying enum's own string
    value (a :class:`~vectorpress.domain.asset.RightsStatus`,
    :class:`~vectorpress.domain.asset.AccuracyStatus`,
    :class:`~vectorpress.domain.derivative_state.DerivativeState` or
    :class:`~vectorpress.domain.status.Status`, always a plain string here
    since every one of those is itself a ``StrEnum``).

    Rendered to text only in ``cli``: this module never formats a message,
    so a catalog-wide attention report and a future ``ui`` can group, count
    and route on ``kind``/``derivative_type`` without parsing strings.
    """

    kind: BlockingReasonKind
    derivative_type: DerivativeType | None
    value: str


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


@dataclass(frozen=True)
class AdmittedUnapproved:
    """One included derivative admitted despite not being approved, under
    ``allow_unapproved`` (§10.1's "unless explicitly overridden"): its type,
    and its status at the moment of the decision -- ``generated`` or
    ``needs_review``, never ``rejected`` or ``regenerate`` (see
    :data:`ADMISSIBLE_UNAPPROVED_STATUSES`) -- so a build can record and
    report exactly what shipped unreviewed."""

    derivative_type: DerivativeType
    status: Status


def _derivative_outcome(
    included: IncludedDerivative, allow_unapproved: bool
) -> tuple[BlockingReason | None, AdmittedUnapproved | None]:
    """The §10.1 outcome for one included derivative: a blocking reason, an
    :class:`AdmittedUnapproved` record, or neither (approved) -- never both.

    A derivative with no output at all (``missing``/``impossible``) always
    blocks: ``allow_unapproved`` admits a status, not an absent file.
    ``approved`` blocks nothing. Every other status blocks naming itself,
    unless ``allow_unapproved`` and the status is one of
    :data:`ADMISSIBLE_UNAPPROVED_STATUSES`, in which case it is admitted
    instead -- ``rejected`` and ``regenerate`` block regardless.
    """
    if included.state in (DerivativeState.MISSING, DerivativeState.IMPOSSIBLE):
        return (
            BlockingReason(
                BlockingReasonKind.DERIVATIVE_STATE, included.derivative_type, included.state.value
            ),
            None,
        )
    assert included.status is not None  # CURRENT/STALE always carry a status
    if included.status is Status.APPROVED:
        return None, None
    if allow_unapproved and included.status in ADMISSIBLE_UNAPPROVED_STATUSES:
        return None, AdmittedUnapproved(included.derivative_type, included.status)
    return (
        BlockingReason(
            BlockingReasonKind.DERIVATIVE_STATUS, included.derivative_type, included.status.value
        ),
        None,
    )


@dataclass(frozen=True)
class EligibilityResult:
    """One asset's publication eligibility for a given set of derivative
    types (§10, §10.1): eligible or blocked, every blocking reason, every
    warning, and every :class:`AdmittedUnapproved` derivative
    ``allow_unapproved`` let through. Warnings never affect
    :attr:`eligibility`; ``admitted_unapproved`` is populated whether or not
    the asset ends up eligible overall (another included derivative may
    still block it), so a caller that cares only about shipped members
    filters by :attr:`eligibility` itself."""

    eligibility: Eligibility
    blocking_reasons: list[BlockingReason]
    warnings: list[str]
    admitted_unapproved: list[AdmittedUnapproved]


def asset_eligibility(
    rights_status: RightsStatus,
    accuracy_status: AccuracyStatus,
    missing_metadata_fields: Sequence[str],
    included_derivatives: Sequence[IncludedDerivative],
    *,
    licensing_notes: str,
    allow_unapproved: bool = False,
) -> EligibilityResult:
    """Whether an asset may ship with ``included_derivatives`` (§10, §10.1).

    Blocking: rights status ``do_not_publish`` or ``rights_review_required``;
    rights status ``ai_generated`` with empty (or whitespace-only)
    ``licensing_notes`` (§26 -- not blocking on its own, only paired with
    missing notes); accuracy status ``issue_found``; any included derivative
    not approved and not admitted, one reason per type naming its status
    when it has one, else its state (a missing or impossible derivative
    counts as not approved, and is never admitted).

    ``allow_unapproved`` (§10.1's "unless explicitly overridden") admits a
    ``generated`` or ``needs_review`` included derivative instead of
    blocking on it, recorded in ``admitted_unapproved`` -- it never touches
    a rights, accuracy or licensing-notes block, and never admits
    ``rejected`` or ``regenerate`` (:func:`_derivative_outcome`). Rights
    status is hand-authored and asset-level (CONTEXT.md "AI-generated"):
    nothing here ever lifts an ``ai_generated`` licensing-notes block either.

    Warnings, which never block: accuracy status ``not_reviewed``; one per
    field named in ``missing_metadata_fields`` ("missing optional metadata").

    ``eligibility`` is :attr:`Eligibility.BLOCKED` iff ``blocking_reasons``
    is non-empty.
    """
    blocking_reasons: list[BlockingReason] = []
    warnings: list[str] = []
    admitted_unapproved: list[AdmittedUnapproved] = []

    if rights_status in (RightsStatus.DO_NOT_PUBLISH, RightsStatus.RIGHTS_REVIEW_REQUIRED):
        blocking_reasons.append(
            BlockingReason(BlockingReasonKind.RIGHTS_STATUS, None, rights_status.value)
        )

    if rights_status is RightsStatus.AI_GENERATED and not licensing_notes.strip():
        blocking_reasons.append(
            BlockingReason(
                BlockingReasonKind.AI_GENERATED_LICENSING_NOTES, None, rights_status.value
            )
        )

    if accuracy_status is AccuracyStatus.ISSUE_FOUND:
        blocking_reasons.append(
            BlockingReason(BlockingReasonKind.ACCURACY_STATUS, None, accuracy_status.value)
        )
    elif accuracy_status is AccuracyStatus.NOT_REVIEWED:
        warnings.append(f"accuracy status: {accuracy_status.value.replace('_', ' ')}")

    for included in included_derivatives:
        reason, admitted = _derivative_outcome(included, allow_unapproved)
        if reason is not None:
            blocking_reasons.append(reason)
        if admitted is not None:
            admitted_unapproved.append(admitted)

    warnings.extend(f"missing optional metadata: {field}" for field in missing_metadata_fields)

    eligibility = Eligibility.BLOCKED if blocking_reasons else Eligibility.ELIGIBLE
    return EligibilityResult(eligibility, blocking_reasons, warnings, admitted_unapproved)
