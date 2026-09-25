"""domain.eligibility: the pure publication-eligibility decision (§10,
§10.1, CONTEXT.md "Blocked", "Eligible").

No I/O anywhere here: every case is built from bare enum values and
:class:`~vectorpress.domain.eligibility.IncludedDerivative` values, never a
real asset folder (``tests/integration/test_eligibility.py`` exercises the
CLI end to end, against a real fixture asset).
"""

from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.eligibility import (
    Eligibility,
    IncludedDerivative,
    asset_eligibility,
    missing_optional_metadata_fields,
)
from vectorpress.domain.status import Status

_APPROVED_PNG = IncludedDerivative(
    DerivativeType.TRANSPARENT_PNG, DerivativeState.CURRENT, Status.APPROVED
)
_APPROVED_CUT = IncludedDerivative(DerivativeType.CUT_SVG, DerivativeState.CURRENT, Status.APPROVED)


def _asset(**overrides: object) -> Asset:
    """A fully-populated asset (every optional field filled) so a test only
    has to override what it is actually exercising."""
    fields: dict[str, object] = {
        "id": "ochre_sea_star",
        "common_name": "Ochre sea star",
        "display_name": "Ochre Sea Star",
        "scientific_name": "Pisaster ochraceus",
        "description": "A test asset.",
        "subject_category": "Echinoderm",
        "tags": ["sea star"],
        "regions": ["California"],
        "ecosystems": ["Tide pool"],
        "taxonomic_group": "Echinoderm",
        "product_use_categories": ["stickers"],
        "notes": "Some notes.",
        "rights_status": RightsStatus.ORIGINAL_ARTWORK,
        "accuracy_status": AccuracyStatus.APPROVED,
        "sources": [Source(role="silhouette", file="silhouette.png")],
    }
    fields.update(overrides)
    return Asset(**fields)  # type: ignore[arg-type]


# --- a clean asset is eligible, no reasons or warnings at all -----------------------


def test_a_fully_approved_asset_with_no_problems_is_eligible_with_no_reasons_or_warnings() -> None:
    result = asset_eligibility(
        RightsStatus.ORIGINAL_ARTWORK,
        AccuracyStatus.APPROVED,
        [],
        [_APPROVED_PNG, _APPROVED_CUT],
    )

    assert result.eligibility is Eligibility.ELIGIBLE
    assert result.blocking_reasons == []
    assert result.warnings == []


# --- §10.1 blocking conditions, each in isolation ------------------------------------


def test_rights_do_not_publish_blocks() -> None:
    result = asset_eligibility(
        RightsStatus.DO_NOT_PUBLISH, AccuracyStatus.APPROVED, [], [_APPROVED_PNG]
    )

    assert result.eligibility is Eligibility.BLOCKED
    assert result.blocking_reasons == ["rights status: do not publish"]
    assert result.warnings == []


def test_rights_review_required_blocks() -> None:
    result = asset_eligibility(
        RightsStatus.RIGHTS_REVIEW_REQUIRED, AccuracyStatus.APPROVED, [], [_APPROVED_PNG]
    )

    assert result.eligibility is Eligibility.BLOCKED
    assert result.blocking_reasons == ["rights status: rights review required"]
    assert result.warnings == []


def test_accuracy_issue_found_blocks() -> None:
    result = asset_eligibility(
        RightsStatus.ORIGINAL_ARTWORK, AccuracyStatus.ISSUE_FOUND, [], [_APPROVED_PNG]
    )

    assert result.eligibility is Eligibility.BLOCKED
    assert result.blocking_reasons == ["accuracy status: issue found"]
    assert result.warnings == []


def test_an_unapproved_included_derivative_blocks_naming_its_status() -> None:
    needs_review = IncludedDerivative(
        DerivativeType.CUT_SVG, DerivativeState.CURRENT, Status.NEEDS_REVIEW
    )

    result = asset_eligibility(
        RightsStatus.ORIGINAL_ARTWORK, AccuracyStatus.APPROVED, [], [_APPROVED_PNG, needs_review]
    )

    assert result.eligibility is Eligibility.BLOCKED
    assert result.blocking_reasons == ["cut_svg: needs review"]


def test_a_rejected_included_derivative_blocks_naming_rejected() -> None:
    rejected = IncludedDerivative(DerivativeType.CUT_SVG, DerivativeState.CURRENT, Status.REJECTED)

    result = asset_eligibility(
        RightsStatus.ORIGINAL_ARTWORK, AccuracyStatus.APPROVED, [], [rejected]
    )

    assert result.blocking_reasons == ["cut_svg: rejected"]


def test_a_missing_included_derivative_blocks_naming_the_missing_state() -> None:
    missing = IncludedDerivative(DerivativeType.CUT_SVG, DerivativeState.MISSING, None)

    result = asset_eligibility(
        RightsStatus.ORIGINAL_ARTWORK, AccuracyStatus.APPROVED, [], [_APPROVED_PNG, missing]
    )

    assert result.eligibility is Eligibility.BLOCKED
    assert result.blocking_reasons == ["cut_svg: missing"]


def test_an_impossible_included_derivative_blocks_naming_the_impossible_state() -> None:
    impossible = IncludedDerivative(DerivativeType.FLATCOLOR_SVG, DerivativeState.IMPOSSIBLE, None)

    result = asset_eligibility(
        RightsStatus.ORIGINAL_ARTWORK, AccuracyStatus.APPROVED, [], [_APPROVED_PNG, impossible]
    )

    assert result.eligibility is Eligibility.BLOCKED
    assert result.blocking_reasons == ["flatcolor_svg: impossible"]


def test_every_unapproved_included_type_gets_its_own_reason() -> None:
    """§10.1's "any included derivative is not approved" names one reason
    per type, not a single collapsed reason."""
    needs_review = IncludedDerivative(
        DerivativeType.CUT_SVG, DerivativeState.CURRENT, Status.NEEDS_REVIEW
    )
    missing = IncludedDerivative(DerivativeType.SILHOUETTE_SVG, DerivativeState.MISSING, None)

    result = asset_eligibility(
        RightsStatus.ORIGINAL_ARTWORK,
        AccuracyStatus.APPROVED,
        [],
        [_APPROVED_PNG, needs_review, missing],
    )

    assert result.eligibility is Eligibility.BLOCKED
    assert result.blocking_reasons == ["cut_svg: needs review", "silhouette_svg: missing"]


# --- §10.1 warnings, each in isolation: never block ----------------------------------


def test_accuracy_not_reviewed_is_a_warning_that_leaves_the_asset_eligible() -> None:
    result = asset_eligibility(
        RightsStatus.ORIGINAL_ARTWORK, AccuracyStatus.NOT_REVIEWED, [], [_APPROVED_PNG]
    )

    assert result.eligibility is Eligibility.ELIGIBLE
    assert result.blocking_reasons == []
    assert result.warnings == ["accuracy status: not reviewed"]


def test_missing_optional_metadata_is_a_warning_that_leaves_the_asset_eligible() -> None:
    result = asset_eligibility(
        RightsStatus.ORIGINAL_ARTWORK,
        AccuracyStatus.APPROVED,
        ["scientific_name", "tags"],
        [_APPROVED_PNG],
    )

    assert result.eligibility is Eligibility.ELIGIBLE
    assert result.blocking_reasons == []
    assert result.warnings == [
        "missing optional metadata: scientific_name",
        "missing optional metadata: tags",
    ]


def test_warnings_alone_leave_the_asset_eligible() -> None:
    """Both warning kinds together, everything else clean: still eligible."""
    result = asset_eligibility(
        RightsStatus.ORIGINAL_ARTWORK,
        AccuracyStatus.NOT_REVIEWED,
        ["notes"],
        [_APPROVED_PNG, _APPROVED_CUT],
    )

    assert result.eligibility is Eligibility.ELIGIBLE
    assert result.blocking_reasons == []
    assert len(result.warnings) == 2


# --- blocking reasons and warnings together ------------------------------------------


def test_blocking_reasons_and_warnings_are_both_reported_together() -> None:
    needs_review = IncludedDerivative(
        DerivativeType.CUT_SVG, DerivativeState.CURRENT, Status.NEEDS_REVIEW
    )

    result = asset_eligibility(
        RightsStatus.ORIGINAL_ARTWORK,
        AccuracyStatus.NOT_REVIEWED,
        ["scientific_name"],
        [needs_review],
    )

    assert result.eligibility is Eligibility.BLOCKED
    assert result.blocking_reasons == ["cut_svg: needs review"]
    assert result.warnings == [
        "accuracy status: not reviewed",
        "missing optional metadata: scientific_name",
    ]


# --- missing_optional_metadata_fields -------------------------------------------------


def test_missing_optional_metadata_fields_is_empty_for_a_fully_populated_asset() -> None:
    assert missing_optional_metadata_fields(_asset()) == []


def test_missing_optional_metadata_fields_names_every_empty_optional_field() -> None:
    asset = _asset(scientific_name=None, tags=[], notes="")

    assert missing_optional_metadata_fields(asset) == ["scientific_name", "tags", "notes"]
