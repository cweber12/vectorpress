"""validate.open_path: the open-path findings-report tracer (§9, §9.1,
ADR 0006, ADR 0007, issue #41).

Every SVG here is hand-written, never produced by :mod:`vectorpress.
pipeline.cut_svg` -- ``validate_cut_file`` is a pure function of bytes plus
a reference size (ADR 0006), so a hand-edited override is checked by
exactly the same code a generated cut file is (§9's own scope bullet 5)."""

import pytest

from vectorpress.domain.finding import FindingKind, ValidationOutcome
from vectorpress.validate.cut_file import validate_cut_file

REFERENCE_SIZE_IN = 3.0

_HEAD = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">'
_TAIL = b"</svg>"


def _svg(path_element: bytes) -> bytes:
    return _HEAD + path_element + _TAIL


# --- unclosed subpath (no Z, end != start) -------------------------------------------------


def test_unclosed_subpath_yields_one_open_path_finding() -> None:
    svg = _svg(b'<path d="M10,10 L90,10 L90,90 L10,90"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind is FindingKind.OPEN_PATH
    assert finding.location is not None
    assert finding.location.min_x == pytest.approx(10.0)
    assert finding.location.min_y == pytest.approx(10.0)
    assert finding.location.max_x == pytest.approx(90.0)
    assert finding.location.max_y == pytest.approx(90.0)
    assert finding.path_reference.element_index == 0
    assert finding.path_reference.subpath_index == 0


def test_closed_subpath_with_explicit_z_yields_no_open_path_finding() -> None:
    """Near miss: the same shape, closed with an explicit ``Z``."""
    svg = _svg(b'<path d="M10,10 L90,10 L90,90 L10,90 Z"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.OPEN_PATH not in kinds


def test_subpath_closed_by_repeating_the_start_point_without_z_yields_no_finding() -> None:
    """Near miss: no ``Z``, but the last point is the same as the first --
    still closed (issue #41's own tolerance-based closure check)."""
    svg = _svg(b'<path d="M10,10 L90,10 L90,90 L10,90 L10,10"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.OPEN_PATH not in kinds


# --- no fill: a stroke-only path, where a closed filled path is expected -------------------


def test_stroke_only_path_yields_open_path_finding_even_though_closed() -> None:
    svg = _svg(b'<path fill="none" stroke="black" d="M10,10 L90,10 L90,90 L10,90 Z"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind is FindingKind.OPEN_PATH
    assert "no fill" in finding.message


def test_style_fill_none_also_yields_open_path_finding() -> None:
    """A ``style`` declaration is checked the same way the plain ``fill``
    attribute is (and wins over it, SVG's own precedence)."""
    svg = _svg(b'<path style="fill:none;stroke:black" d="M10,10 L90,10 L90,90 L10,90 Z"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.OPEN_PATH in kinds


def test_path_with_no_fill_attribute_at_all_is_filled_by_default() -> None:
    """Near miss: SVG's own default (no ``fill`` attribute, no ``style``
    override) is a filled black shape -- no open_path finding."""
    svg = _svg(b'<path d="M10,10 L90,10 L90,90 L10,90 Z"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.OPEN_PATH not in kinds


def test_explicit_fill_black_yields_no_finding() -> None:
    """Near miss: an explicit, non-``none`` fill is still a fill."""
    svg = _svg(b'<path fill="#000000" d="M10,10 L90,10 L90,90 L10,90 Z"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.OPEN_PATH not in kinds


# --- a bare open line segment (fewer than 3 points) still reaches open_path ----------------


def test_a_bare_two_point_line_segment_yields_an_open_path_finding() -> None:
    """Issue #41 review fix round 1: a subpath with only two points -- an
    open line segment, not even a polygon -- is §9's simplest possible
    "not closed" case. Before this fix, ``_svg_geometry.parse_subpaths``
    silently dropped any subpath under three points, so a document
    containing nothing but a stray open segment like this reported
    ``pass`` -- no detector ever saw it (it is far too small a shape to
    become a piece or a hole either, so no other kind picks it up)."""
    svg = _svg(b'<path d="M20,50 L60,80"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 1  # nothing else in this document to find
    finding = result.findings[0]
    assert finding.kind is FindingKind.OPEN_PATH
    assert finding.location is not None
    assert finding.location.min_x == pytest.approx(20.0)
    assert finding.location.min_y == pytest.approx(50.0)
    assert finding.location.max_x == pytest.approx(60.0)
    assert finding.location.max_y == pytest.approx(80.0)
