"""validate.duplicate_geometry: the duplicate-geometry findings-report
tracer (§9, §9.1, ADR 0006, ADR 0007, issue #41).

Every SVG here is hand-written, never produced by :mod:`vectorpress.
pipeline.cut_svg` -- ``validate_cut_file`` is a pure function of bytes plus
a reference size (ADR 0006), so a hand-edited override is checked by
exactly the same code a generated cut file is (§9's own scope bullet 5).

Every fixture below uses two holes cut from one big square (rather than two
top-level pieces) so the fixture trips *only* duplicate_geometry: two
equal-area top-level pieces would also be reported as a disconnected
fragment (ADR 0007's own "no bridging" -- see this module's own
``tests/fixtures/findings/duplicate_geometry.svg`` for the same reasoning,
spelled out in full)."""

from vectorpress.domain.finding import FindingKind, ValidationOutcome
from vectorpress.validate.cut_file import validate_cut_file

REFERENCE_SIZE_IN = 3.0

_HEAD = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
_MAIN_BODY = b"M0,0 L90,0 L90,90 L0,90 Z"
_HOLE = b" M40,40 L60,40 L60,60 L40,60 Z"
_TAIL = b"</svg>"


def test_two_identical_holes_yield_one_duplicate_geometry_finding() -> None:
    svg = _HEAD + b'<path fill-rule="evenodd" d="' + _MAIN_BODY + _HOLE + _HOLE + b'"/>' + _TAIL

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    findings = [f for f in result.findings if f.kind is FindingKind.DUPLICATE_GEOMETRY]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.path_reference.element_index == 0
    assert finding.path_reference.subpath_index == 1
    assert finding.related_path_reference is not None
    assert finding.related_path_reference.subpath_index == 2
    assert finding.location is not None
    assert finding.location.min_x == 40.0
    assert finding.location.max_x == 60.0


def test_two_different_holes_yield_no_duplicate_geometry_finding() -> None:
    """Near miss: same two-hole shape, but the holes are not the same
    geometry (one is shifted)."""
    other_hole = b" M200,40 L220,40 L220,60 L200,60 Z"
    svg = (
        _HEAD + b'<path fill-rule="evenodd" d="' + _MAIN_BODY + _HOLE + other_hole + b'"/>' + _TAIL
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.DUPLICATE_GEOMETRY not in kinds


def test_three_identical_holes_yield_one_finding_per_pair() -> None:
    svg = (
        _HEAD
        + b'<path fill-rule="evenodd" d="'
        + _MAIN_BODY
        + _HOLE
        + _HOLE
        + _HOLE
        + b'"/>'
        + _TAIL
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    findings = [f for f in result.findings if f.kind is FindingKind.DUPLICATE_GEOMETRY]
    assert len(findings) == 3  # (1,2), (1,3), (2,3)
    pairs = {
        (f.path_reference.subpath_index, f.related_path_reference.subpath_index)  # type: ignore[union-attr]
        for f in findings
    }
    assert pairs == {(1, 2), (1, 3), (2, 3)}


def test_duplicate_found_regardless_of_starting_vertex_or_winding_direction() -> None:
    """A duplicate drawn starting from a different corner and wound the
    other way is still the same geometry."""
    reversed_hole = b" M40,60 L60,60 L60,40 L40,40 Z"
    svg = (
        _HEAD
        + b'<path fill-rule="evenodd" d="'
        + _MAIN_BODY
        + _HOLE
        + reversed_hole
        + b'"/>'
        + _TAIL
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.DUPLICATE_GEOMETRY in kinds
