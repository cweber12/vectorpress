"""validate.cut_file: the disconnected-fragments findings-report tracer
(§9, §9.1, §35, ADR 0006, ADR 0007, issue #37).

Every SVG here is hand-written, never produced by
:mod:`vectorpress.pipeline.cut_svg` (``tests/integration/test_validate.py``
exercises the real fixture catalog end to end) -- ``validate_cut_file`` is a
pure function of bytes plus a reference size (ADR 0006), so a hand-edited
override is checked by exactly the same code a generated cut file is."""

import xml.etree.ElementTree as ET

import pytest

from vectorpress.domain.finding import FindingKind, ValidationOutcome
from vectorpress.validate.cut_file import validate_cut_file

REFERENCE_SIZE_IN = 3.0

_ONE_PIECE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="10" height="10">'
    b'<path d="M0,0 L10,0 L10,10 L0,10 Z"/></svg>'
)

_TWO_PIECE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 10" width="30" height="10">'
    b'<path d="M0,0 L10,0 L10,10 L0,10 Z M20,2 L28,2 L28,8 L20,8 Z"/></svg>'
)

_THREE_PIECE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 10" width="50" height="10">'
    b'<path d="M0,0 L10,0 L10,10 L0,10 Z'
    b" M20,2 L26,2 L26,8 L20,8 Z"
    b' M40,3 L45,3 L45,7 L40,7 Z"/></svg>'
)

# A donut -- one outer shell with one hole cut from it (even-odd) -- is a
# single physical piece, not two: the hole must not itself be counted as a
# disconnected fragment.
_RING_WITH_A_HOLE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="10" height="10" >'
    b'<path fill-rule="evenodd" d="M0,0 L10,0 L10,10 L0,10 Z M3,3 L7,3 L7,7 L3,7 Z"/></svg>'
)

_NO_VIEWBOX_NO_SIZE = (
    b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0,0 L10,0 L10,10 L0,10 Z"/></svg>'
)

_WIDTH_HEIGHT_ONLY_NO_VIEWBOX = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b'<path d="M0,0 L10,0 L10,10 L0,10 Z"/></svg>'
)


# --- one piece passes, two pieces need review (issue #37 acceptance criteria) --------------


def test_one_piece_svg_passes_with_no_findings() -> None:
    result = validate_cut_file(_ONE_PIECE, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.PASS
    assert result.findings == ()


def test_two_piece_svg_reports_exactly_one_disconnected_fragment_finding() -> None:
    result = validate_cut_file(_TWO_PIECE, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind is FindingKind.DISCONNECTED_FRAGMENTS


def test_two_piece_finding_is_located_at_the_smaller_pieces_own_bbox() -> None:
    """The smaller square (100 area units) is the one "beyond the largest"
    (10x10 = 100 area units for the first, 8x6 = 48 for the second -- the
    second is smaller, so it is the reported fragment, located at its own
    bounding box, not the larger piece's)."""
    result = validate_cut_file(_TWO_PIECE, REFERENCE_SIZE_IN)

    finding = result.findings[0]
    assert finding.location.min_x == pytest.approx(20.0)
    assert finding.location.min_y == pytest.approx(2.0)
    assert finding.location.max_x == pytest.approx(28.0)
    assert finding.location.max_y == pytest.approx(8.0)


def test_two_piece_finding_names_its_path_reference() -> None:
    """A path reference so an editor can navigate to it (issue #37): the
    element (this SVG's only ``<path>``, so index 0) and the offending
    subpath's index within it (the second subpath, index 1)."""
    result = validate_cut_file(_TWO_PIECE, REFERENCE_SIZE_IN)

    reference = result.findings[0].path_reference
    assert reference.element_index == 0
    assert reference.subpath_index == 1


def test_three_pieces_report_two_findings_neither_for_the_largest() -> None:
    result = validate_cut_file(_THREE_PIECE, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 2
    subpath_indices = {finding.path_reference.subpath_index for finding in result.findings}
    assert subpath_indices == {1, 2}  # subpath 0 is the largest piece, never a finding


def test_findings_are_in_a_deterministic_document_order() -> None:
    """Findings are ordered by path reference (element, then subpath index),
    not by area or any other incidental ordering (issue #37's "findings in a
    deterministic order")."""
    result = validate_cut_file(_THREE_PIECE, REFERENCE_SIZE_IN)

    ordered = [f.path_reference.subpath_index for f in result.findings]
    assert ordered == sorted(ordered)


def test_a_hole_in_a_ring_is_not_a_disconnected_fragment() -> None:
    """A donut is one physical piece with a hole cut out of it, not two
    pieces -- the hole must not itself be flagged (ADR 0007's "the design is
    more than one separate cut piece", not "more than one subpath")."""
    result = validate_cut_file(_RING_WITH_A_HOLE, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.PASS
    assert result.findings == ()


# --- physical scale: fails visibly with neither a viewBox nor width/height (§35) -----------


def test_svg_with_no_viewbox_and_no_width_or_height_fails_visibly() -> None:
    with pytest.raises(ValueError):
        validate_cut_file(_NO_VIEWBOX_NO_SIZE, REFERENCE_SIZE_IN)


def test_width_and_height_alone_are_enough_without_a_viewbox() -> None:
    """Falls back to ``width``/``height`` per issue #37's "falling back to
    width/height" -- only the *absence of both* fails."""
    result = validate_cut_file(_WIDTH_HEIGHT_ONLY_NO_VIEWBOX, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.PASS


def test_unparseable_svg_fails_visibly() -> None:
    with pytest.raises(ET.ParseError):
        validate_cut_file(b"not an svg document at all", REFERENCE_SIZE_IN)
