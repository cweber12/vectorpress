# pyright: basic
# (reads the produced DXF back with ezdxf directly as this test's own
# oracle -- the same loose-third-party-type situation
# vectorpress.build._dxf_conversion's own docstring explains)
"""``build._dxf_conversion``: every closed subpath of an SVG becomes one DXF
polyline (ADR 0013, §7, §35, §36)."""

import ezdxf
import pytest

from vectorpress.build._dxf_conversion import (
    DxfConversionError,
    closed_rings,
    svg_to_dxf_bytes,
)

_RECTANGLE_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<path d="M0,0 L10,0 L10,10 L0,10 Z"/>
</svg>"""

#: A donut: an outer square piece with a smaller square hole inside it, as
#: two closed subpaths of the same ``<path>`` -- both must survive as their
#: own polyline (ADR 0013: "Holes and islands keep their structure").
_DONUT_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<path d="M0,0 L10,0 L10,10 L0,10 Z M3,3 L7,3 L7,7 L3,7 Z" fill-rule="evenodd"/>
</svg>"""

_OPEN_LINE_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<path d="M0,0 L10,10"/>
</svg>"""

#: A quarter circle drawn with a cubic Bezier, closed back through the
#: origin with two straight lines -- exercises curve flattening, not just
#: straight ``L`` segments.
_CURVE_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<path d="M10,0 C10,5.523 5.523,10 0,10 L0,0 Z"/>
</svg>"""


def _polyline_rings(dxf_bytes: bytes) -> list[list[tuple[float, float]]]:
    """Every ``POLYLINE`` entity's vertices, read back with ``ezdxf``
    directly as this test's own oracle -- independent of this module's own
    writer."""
    import io

    doc = ezdxf.read(io.StringIO(dxf_bytes.decode("ascii")))  # pyright: ignore[reportPrivateImportUsage]
    modelspace = doc.modelspace()
    return [
        [
            (vertex.dxf.location.x, vertex.dxf.location.y)
            for vertex in polyline.vertices  # pyright: ignore[reportAttributeAccessIssue]
        ]
        for polyline in modelspace.query("POLYLINE")
    ]


def test_closed_rings_finds_one_ring_per_closed_subpath() -> None:
    rings = closed_rings(_RECTANGLE_SVG)
    assert len(rings) == 1
    assert rings[0][0] == (0.0, 0.0)


def test_closed_rings_keeps_a_hole_as_its_own_ring() -> None:
    rings = closed_rings(_DONUT_SVG)
    assert len(rings) == 2


def test_closed_rings_leaves_out_an_open_subpath() -> None:
    assert closed_rings(_OPEN_LINE_SVG) == []


def test_closed_rings_flattens_a_curved_segment_to_more_than_its_anchors() -> None:
    (ring,) = closed_rings(_CURVE_SVG)
    # M, L, Z contribute 3 anchor points; the curve alone samples
    # CURVE_STEPS more, so a real curve is not collapsed to a straight edge.
    assert len(ring) > 10


def test_closed_rings_raises_on_malformed_xml() -> None:
    with pytest.raises(DxfConversionError):
        closed_rings(b"<svg><path d=")


def test_closed_rings_raises_on_unparseable_path_data() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0,0 L abc"/></svg>'
    with pytest.raises(DxfConversionError):
        closed_rings(svg)


def test_svg_to_dxf_bytes_writes_one_polyline_entity_per_closed_subpath() -> None:
    dxf_bytes = svg_to_dxf_bytes(_DONUT_SVG)
    rings = _polyline_rings(dxf_bytes)
    assert len(rings) == len(closed_rings(_DONUT_SVG))


def test_svg_to_dxf_bytes_keeps_the_svgs_own_coordinates() -> None:
    dxf_bytes = svg_to_dxf_bytes(_RECTANGLE_SVG)
    (ring,) = _polyline_rings(dxf_bytes)
    assert sorted(set(ring)) == [(0.0, 0.0), (0.0, 10.0), (10.0, 0.0), (10.0, 10.0)]


def test_svg_to_dxf_bytes_never_writes_insunits_or_a_wall_clock_timestamp() -> None:
    """The DXF carries no more physical sizing than the SVG did (ADR 0013),
    and never a build-time timestamp that would break a byte-identical
    rebuild (§36)."""
    dxf_text = svg_to_dxf_bytes(_RECTANGLE_SVG).decode("ascii")
    assert "$INSUNITS" not in dxf_text
    assert "\r\n" not in dxf_text


def test_svg_to_dxf_bytes_is_byte_identical_across_repeated_calls() -> None:
    first = svg_to_dxf_bytes(_DONUT_SVG)
    second = svg_to_dxf_bytes(_DONUT_SVG)
    assert first == second


def test_svg_to_dxf_bytes_raises_dxf_conversion_error_on_bad_input() -> None:
    with pytest.raises(DxfConversionError):
        svg_to_dxf_bytes(b"not xml at all <<<")
