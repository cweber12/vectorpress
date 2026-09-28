# pyright: basic
# (reads the produced DXF back with ezdxf directly as this test's own
# oracle -- the same loose-third-party-type situation
# vectorpress.build._dxf_conversion's own docstring explains)
"""``build._dxf_conversion``: every closed subpath of an SVG becomes one DXF
polyline (ADR 0013, §7, §35, §36)."""

from datetime import datetime

import ezdxf
import pytest
from ezdxf.tools.juliandate import juliandate

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

_RECT_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<rect x="1" y="1" width="4" height="4"/>
</svg>"""

_CIRCLE_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<circle cx="5" cy="5" r="3"/>
</svg>"""

_POLYGON_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<polygon points="0,0 10,0 10,10 0,10"/>
</svg>"""

_SHAPES_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 30">
<rect x="1" y="1" width="4" height="4"/>
<circle cx="15" cy="15" r="3"/>
<polygon points="20,20 28,20 28,28 20,28"/>
</svg>"""

#: The same rectangle as ``_RECTANGLE_SVG``, but placed with its own
#: ``transform`` -- ADR 0007 makes a hand-edited override the effective
#: derivative, so a shape a human moved with a transform is exactly as real
#: a cut line as one authored at its final coordinates directly.
_TRANSLATED_RECTANGLE_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 30">
<path d="M0,0 L10,0 L10,10 L0,10 Z" transform="translate(10,20)"/>
</svg>"""

#: The rectangle placed under two nested groups -- an outer ``scale(2)``
#: around an inner ``translate(10,20)`` -- the way Inkscape puts a
#: transform on a layer or group at least as often as on a shape itself.
#: Applying the inner translate first, then the outer scale (SVG's own
#: nesting order): local (0,0) -> translate -> (10,20) -> scale -> (20,40).
_NESTED_GROUPS_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<g transform="scale(2)">
<g transform="translate(10,20)">
<path d="M0,0 L10,0 L10,10 L0,10 Z"/>
</g>
</g>
</svg>"""

#: A closed path inside ``<defs>`` -- never rendered on its own, only if a
#: ``<use>`` referenced it (deferred, out of scope) -- must not ship as a
#: cut line.
_DEFS_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<defs><path d="M0,0 L10,0 L10,10 L0,10 Z"/></defs>
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


def test_closed_rings_converts_a_rect_element() -> None:
    (ring,) = closed_rings(_RECT_SVG)
    assert sorted(set(ring)) == [(1.0, 1.0), (1.0, 5.0), (5.0, 1.0), (5.0, 5.0)]


def test_closed_rings_converts_a_circle_element() -> None:
    (ring,) = closed_rings(_CIRCLE_SVG)
    # a circle has no straight corner to anchor on; curve flattening alone
    # gives it far more than the 3-point floor a real ring needs.
    assert len(ring) > 10


def test_closed_rings_converts_a_polygon_element() -> None:
    (ring,) = closed_rings(_POLYGON_SVG)
    assert sorted(set(ring)) == [(0.0, 0.0), (0.0, 10.0), (10.0, 0.0), (10.0, 10.0)]


def test_closed_rings_applies_a_paths_own_transform_attribute() -> None:
    """A ``transform`` on a ``<path>`` moves its ring's coordinates -- an
    override placed with one is exactly as real a cut line as one authored
    at its final position directly (ADR 0007)."""
    (plain_ring,) = closed_rings(_RECTANGLE_SVG)
    (translated_ring,) = closed_rings(_TRANSLATED_RECTANGLE_SVG)
    assert translated_ring == tuple((x + 10.0, y + 20.0) for x, y in plain_ring)


def test_closed_rings_composes_nested_group_transforms() -> None:
    """A shape's own group and every ancestor group's ``transform`` compose
    together (Inkscape puts a transform on a layer or group at least as
    often as on a shape itself) -- the inner ``translate`` applies before
    the outer ``scale`` wrapping it, exactly SVG's own nesting order."""
    (plain_ring,) = closed_rings(_RECTANGLE_SVG)
    (nested_ring,) = closed_rings(_NESTED_GROUPS_SVG)
    assert nested_ring == tuple(((x + 10.0) * 2.0, (y + 20.0) * 2.0) for x, y in plain_ring)


def test_closed_rings_skips_geometry_inside_defs() -> None:
    """A ``<defs>`` subtree is never rendered on its own -- only via a
    ``<use>`` (deferred, out of scope) -- so it must not ship as a cut
    line."""
    assert closed_rings(_DEFS_SVG) == []


def test_svg_to_dxf_bytes_writes_one_polyline_entity_per_closed_subpath() -> None:
    dxf_bytes = svg_to_dxf_bytes(_DONUT_SVG)
    rings = _polyline_rings(dxf_bytes)
    assert len(rings) == len(closed_rings(_DONUT_SVG))


def test_svg_to_dxf_bytes_keeps_the_svgs_own_coordinates() -> None:
    dxf_bytes = svg_to_dxf_bytes(_RECTANGLE_SVG)
    (ring,) = _polyline_rings(dxf_bytes)
    assert sorted(set(ring)) == [(0.0, 0.0), (0.0, 10.0), (10.0, 0.0), (10.0, 10.0)]


def test_svg_to_dxf_bytes_writes_a_polyline_for_a_rect_a_circle_and_a_polygon() -> None:
    dxf_bytes = svg_to_dxf_bytes(_SHAPES_SVG)
    assert len(_polyline_rings(dxf_bytes)) == 3


def test_svg_to_dxf_bytes_moves_coordinates_for_a_transformed_path() -> None:
    """End to end: a ``transform`` on a ``<path>`` moves the coordinates
    actually shipped in the DXF, not just the in-memory ring
    (:func:`test_closed_rings_applies_a_paths_own_transform_attribute`)."""
    (plain_ring,) = _polyline_rings(svg_to_dxf_bytes(_RECTANGLE_SVG))
    (translated_ring,) = _polyline_rings(svg_to_dxf_bytes(_TRANSLATED_RECTANGLE_SVG))
    assert sorted(translated_ring) == sorted((x + 10.0, y + 20.0) for x, y in plain_ring)


def _header_var(dxf_text: str, name: str) -> str:
    """One DXF header variable's own value, read straight from the raw text
    -- never through ``ezdxf.read()``, which re-stamps ``$TDCREATE`` with
    the real wall-clock time the moment a document is loaded, defeating the
    very thing this is checking."""
    marker = f"{name}\n"
    start = dxf_text.index(marker) + len(marker)
    # the next two lines are the value's own group code, then the value.
    _group_code, value, *_rest = dxf_text[start:].split("\n", 2)
    return value


def test_svg_to_dxf_bytes_never_writes_insunits_and_fixes_the_timestamp() -> None:
    """The DXF carries no more physical sizing than the SVG did (ADR 0013),
    and never a build-time timestamp that would break a byte-identical
    rebuild (§36) -- ``$TDCREATE``/``$TDUPDATE`` hold ``ezdxf``'s own fixed
    epoch (2000-01-01), not the real time this test actually ran at."""
    dxf_text = svg_to_dxf_bytes(_RECTANGLE_SVG).decode("ascii")
    assert "$INSUNITS" not in dxf_text
    assert "\r\n" not in dxf_text

    fixed_epoch = juliandate(datetime(2000, 1, 1, 0, 0))
    for header_var in ("$TDCREATE", "$TDUPDATE"):
        assert float(_header_var(dxf_text, header_var)) == fixed_epoch


def test_svg_to_dxf_bytes_is_byte_identical_across_repeated_calls() -> None:
    first = svg_to_dxf_bytes(_DONUT_SVG)
    second = svg_to_dxf_bytes(_DONUT_SVG)
    assert first == second


def test_svg_to_dxf_bytes_raises_dxf_conversion_error_on_bad_input() -> None:
    with pytest.raises(DxfConversionError):
        svg_to_dxf_bytes(b"not xml at all <<<")
