"""domain.finding: the findings model (CONTEXT.md "Findings", §9, §9.2,
issue #37).

No I/O here (ADR 0006) -- just the shape and the pass/needs-review roll-up,
exercised directly against hand-built :class:`Finding` values rather than
anything a real detector produced (``tests/unit/test_validate_cut_file.py``
covers the detector itself)."""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    BoundingBox,
    Finding,
    FindingClassification,
    FindingKind,
    PathReference,
    ValidationOutcome,
    ValidationResult,
)


def _finding(kind: FindingKind) -> Finding:
    return Finding(
        kind=kind,
        classification=CLASSIFICATION[kind],
        message="a finding",
        location=BoundingBox(min_x=0.0, min_y=0.0, max_x=1.0, max_y=1.0),
        path_reference=PathReference(element_index=0, subpath_index=0, id=None),
    )


# --- the classification table covers all eleven §9 kinds (issue #37 acceptance criterion) ------


def test_classification_table_covers_every_finding_kind() -> None:
    assert set(CLASSIFICATION) == set(FindingKind)


def test_there_are_exactly_eleven_finding_kinds() -> None:
    """§9 names eleven cut-file quality problems; the domain names all of
    them up front, whether or not a detector has landed yet (issue #37)."""
    assert len(FindingKind) == 11


def test_every_finding_kind_classifies_as_needing_review() -> None:
    """Every §9 kind this tool names is a genuine manufacturability problem
    (issue #37's domain description) -- the only classification that exists
    today."""
    assert all(
        classification is FindingClassification.NEEDS_REVIEW
        for classification in CLASSIFICATION.values()
    )


def test_disconnected_fragments_is_one_of_the_eleven_kinds() -> None:
    assert FindingKind.DISCONNECTED_FRAGMENTS in FindingKind


# --- ValidationResult.outcome (§9.2) -------------------------------------------------------


def test_no_findings_is_pass() -> None:
    result = ValidationResult(findings=())

    assert result.outcome is ValidationOutcome.PASS


def test_one_needs_review_finding_makes_the_whole_result_needs_review() -> None:
    result = ValidationResult(findings=(_finding(FindingKind.DISCONNECTED_FRAGMENTS),))

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW


def test_several_findings_still_needs_review() -> None:
    result = ValidationResult(
        findings=(
            _finding(FindingKind.DISCONNECTED_FRAGMENTS),
            _finding(FindingKind.RASTER_CONTENT),
        )
    )

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
