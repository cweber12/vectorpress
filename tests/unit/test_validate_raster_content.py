"""validate.raster_content: the raster-content findings-report tracer (§9,
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


# --- <image> element -----------------------------------------------------------------------


def test_image_element_yields_one_raster_content_finding() -> None:
    svg = _svg(b'<image x="0" y="0" width="20" height="20" href="foo.png"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind is FindingKind.RASTER_CONTENT
    assert finding.location is not None
    assert finding.location.min_x == 0.0
    assert finding.location.max_x == 20.0
    assert finding.path_reference.subpath_index is None


def test_no_image_element_yields_no_raster_content_finding() -> None:
    """Near miss: a plain path-only document."""
    svg = _svg()

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.RASTER_CONTENT not in kinds


# --- a data: URI anywhere --------------------------------------------------------------------


def test_data_uri_in_a_style_attribute_yields_raster_content_finding() -> None:
    svg = _svg(
        b'<rect x="0" y="0" width="10" height="10" style="fill:url(data:image/png;base64,AA)"/>'
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.RASTER_CONTENT in kinds


def test_ordinary_url_reference_yields_no_raster_content_finding() -> None:
    """Near miss: a ``url(#id)`` reference is not a data: URI."""
    svg = _svg(b'<rect x="0" y="0" width="10" height="10" fill="url(#gradient)"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.RASTER_CONTENT not in kinds


# --- pattern / foreignObject carrying raster content ----------------------------------------


def test_pattern_with_an_image_child_yields_raster_content_finding() -> None:
    svg = _svg(
        b'<defs><pattern id="p" width="10" height="10">'
        b'<image x="0" y="0" width="10" height="10" href="foo.png"/>'
        b"</pattern></defs>"
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    findings = [f for f in result.findings if f.kind is FindingKind.RASTER_CONTENT]
    assert len(findings) == 1
    assert "pattern" in findings[0].message


def test_pattern_with_only_vector_children_yields_no_raster_content_finding() -> None:
    """Near miss: a pattern tile that is plain vector geometry, no raster
    content anywhere in its own subtree."""
    svg = _svg(
        b'<defs><pattern id="p" width="10" height="10">'
        b'<rect x="0" y="0" width="10" height="10"/>'
        b"</pattern></defs>"
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.RASTER_CONTENT not in kinds


def test_foreignobject_with_a_data_uri_yields_raster_content_finding() -> None:
    svg = _svg(
        b'<foreignObject x="0" y="0" width="10" height="10">'
        b'<img src="data:image/png;base64,AA"/>'
        b"</foreignObject>"
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    findings = [f for f in result.findings if f.kind is FindingKind.RASTER_CONTENT]
    assert len(findings) == 1
    assert "foreignObject" in findings[0].message


def test_empty_foreignobject_yields_no_raster_content_finding() -> None:
    """Near miss: a foreignObject with no raster content in its subtree at
    all (still an odd thing for a cut file to contain, but not this
    detector's own concern -- :mod:`vectorpress.validate.stray_object`'s,
    were it not itself a non-rendering-adjacent container this issue keeps
    out of that detector's own scope too)."""
    svg = _svg(b'<foreignObject x="0" y="0" width="10" height="10"/>')

    result = validate_cut_file(svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.RASTER_CONTENT not in kinds
