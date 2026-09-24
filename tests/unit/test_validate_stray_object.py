"""validate.stray_object: the stray-object findings-report tracer (§9,
§9.1, ADR 0006, ADR 0007, issue #41).

Every SVG here is hand-written, never produced by :mod:`vectorpress.
pipeline.cut_svg` -- ``validate_cut_file`` is a pure function of bytes plus
a reference size (ADR 0006), so a hand-edited override is checked by
exactly the same code a generated cut file is (§9's own scope bullet 5)."""

from vectorpress.domain.finding import FindingKind, ValidationOutcome
from vectorpress.validate.cut_file import validate_cut_file

REFERENCE_SIZE_IN = 3.0

_HEAD = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">'
_MAIN_BODY = b'<path d="M10,10 L90,10 L90,90 L10,90 Z"/>'
_TAIL = b"</svg>"


def _svg(*extra: bytes) -> bytes:
    return _HEAD + _MAIN_BODY + b"".join(extra) + _TAIL


# --- off-canvas element ----------------------------------------------------------------------


def test_off_canvas_rect_yields_one_stray_object_finding() -> None:
    svg = _svg(b'<rect x="150" y="150" width="10" height="10"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind is FindingKind.STRAY_OBJECT
    assert finding.location is not None
    assert finding.location.min_x == 150.0
    assert "outside" in finding.message


def test_in_canvas_rect_yields_no_stray_object_finding() -> None:
    """Near miss: the same rect, fully inside the viewBox."""
    svg = _svg(b'<rect x="10" y="10" width="10" height="10"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT not in kinds


def test_the_main_path_itself_is_never_off_canvas(  # regression: issue #41 review fix
) -> None:
    """A ``<path>`` -- the cut file's own main geometry -- is never itself
    judged a stray object, even when it happens to sit exactly at the
    canvas edge (a real generated fixture's own curve fitting can land a
    fraction of a unit outside its own viewBox)."""
    svg = _HEAD + b'<path d="M0,0 L100,0 L100,100.0001 L0,100.0001 Z"/>' + _TAIL

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT not in kinds


# --- empty group -----------------------------------------------------------------------------


def test_empty_group_yields_a_stray_object_finding_with_no_bbox() -> None:
    svg = _svg(b'<g id="leftover"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    findings = [f for f in result.findings if f.kind is FindingKind.STRAY_OBJECT]
    assert len(findings) == 1
    assert findings[0].location is None
    assert findings[0].path_reference.id == "leftover"


def test_nonempty_group_yields_no_stray_object_finding() -> None:
    """Near miss: a group that actually contains something."""
    svg = _svg(b'<g><rect x="10" y="10" width="5" height="5"/></g>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT not in kinds


# --- invisible element -----------------------------------------------------------------------


def test_display_none_element_yields_stray_object_finding() -> None:
    svg = _svg(b'<rect x="10" y="10" width="5" height="5" display="none"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT in kinds


def test_visibility_hidden_element_yields_stray_object_finding() -> None:
    svg = _svg(b'<rect x="10" y="10" width="5" height="5" visibility="hidden"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT in kinds


def test_zero_opacity_element_yields_stray_object_finding() -> None:
    svg = _svg(b'<rect x="10" y="10" width="5" height="5" opacity="0"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT in kinds


def test_zero_fill_opacity_element_yields_stray_object_finding() -> None:
    svg = _svg(b'<rect x="10" y="10" width="5" height="5" fill-opacity="0"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT in kinds


def test_no_fill_and_no_stroke_element_yields_stray_object_finding() -> None:
    svg = _svg(b'<rect x="10" y="10" width="5" height="5" fill="none"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT in kinds


def test_visible_element_yields_no_stray_object_finding() -> None:
    """Near miss: an ordinary, visible element (default fill)."""
    svg = _svg(b'<rect x="10" y="10" width="5" height="5"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT not in kinds


def test_no_fill_but_a_real_stroke_is_not_invisible() -> None:
    """Near miss: ``fill="none"`` alone does not make an element invisible
    when it still has a stroke -- it is genuinely drawn, just unfilled."""
    svg = _svg(b'<rect x="10" y="10" width="5" height="5" fill="none" stroke="black"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT not in kinds


# --- non-artwork drawing element (stray <text>) ------------------------------------------


def test_text_element_yields_stray_object_finding() -> None:
    svg = _svg(b'<text x="10" y="10">note</text>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    findings = [f for f in result.findings if f.kind is FindingKind.STRAY_OBJECT]
    assert len(findings) == 1
    assert "text" in findings[0].message


# --- non-rendering containers: an element inside one is never itself a stray object -------


def test_off_canvas_element_inside_defs_is_never_a_stray_object() -> None:
    """Near miss: an element that would otherwise be off canvas, but lives
    inside ``<defs>`` -- never rendered on its own, so never itself
    "stray"."""
    svg = _svg(b'<defs><rect x="150" y="150" width="10" height="10"/></defs>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT not in kinds


def test_invisible_element_inside_a_pattern_tile_is_never_a_stray_object() -> None:
    """Near miss: an "invisible" (``fill="none"``, no stroke) element that
    is simply how a pattern's own tile is drawn."""
    svg = _svg(
        b'<defs><pattern id="p" width="10" height="10">'
        b'<rect x="0" y="0" width="10" height="10" fill="none"/>'
        b"</pattern></defs>"
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.STRAY_OBJECT not in kinds
