"""Deterministic, §8-clean SVG document assembly shared by every tracing
generator (issue #24: "§8 cleaning as a post-pass on the traced document
that the flat-color slice will reuse").

Builds a minimal SVG document straight from traced path geometry rather
than post-processing a tracer library's own XML output: every element this
module writes already satisfies §8 by construction --

- no ``<image>`` or other raster content (this module never writes one)
- no ``<metadata>``, editor namespaces or comments (this module never
  writes them)
- no empty groups (this module never writes a ``<g>`` at all)
- root ``viewBox`` tight to the geometry's own bounding box, so nothing is
  ever outside it and proportions hold (``width``/``height`` match the
  ``viewBox`` size exactly, a 1:1 mapping) -- computed from each Bézier
  curve's true extrema, not its control polygon (a cubic Bézier lies inside
  its control points' convex hull, but a control point is not generally on
  the curve itself, so using control points directly overshoots the actual
  bounds; review fix round 1, issue #24)
- no invisible elements: the one path this module writes always has a
  concrete fill and ``stroke="none"``, and degenerate (zero-area) subpaths
  are dropped before the bounding box is even computed

-- but is exercised as a single "build one clean compound path" function so
a later derivative type (``flatcolor_svg``) has one place to call for the
same guarantees instead of re-deriving them (:func:`render_svg`).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True)
class CornerSegment:
    """A straight-line potrace "corner" segment: two line segments, the
    current point to ``through``, then ``through`` to ``end`` (matches
    potrace's own corner semantics -- a corner is a vertex, not a single
    line)."""

    through: Point
    end: Point


@dataclass(frozen=True)
class CurveSegment:
    """A cubic Bézier segment from the current point to ``end``, via
    control points ``c1`` and ``c2``."""

    c1: Point
    c2: Point
    end: Point


Segment = CornerSegment | CurveSegment


@dataclass(frozen=True)
class Subpath:
    """One closed subpath of a traced compound path: where it starts, and
    the segments that trace it back to ``start`` (every subpath potrace
    produces is closed, so this module always closes with ``Z``)."""

    start: Point
    segments: tuple[Segment, ...]


def _quadratic_roots_in_unit_interval(a: float, b: float, c: float) -> list[float]:
    """Real roots of ``a*t**2 + b*t + c = 0`` strictly inside ``(0, 1)``
    (the open interval: ``t=0``/``t=1`` are a curve's own endpoints, always
    included in a bbox separately, so a root landing exactly on one adds
    nothing new)."""
    if abs(a) < 1e-12:
        if abs(b) < 1e-12:
            return []
        t = -c / b
        return [t] if 0.0 < t < 1.0 else []

    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return []
    sqrt_discriminant = math.sqrt(discriminant)
    roots = [(-b + sqrt_discriminant) / (2 * a), (-b - sqrt_discriminant) / (2 * a)]
    return [t for t in roots if 0.0 < t < 1.0]


def _bezier_axis_extrema_ts(p0: float, p1: float, p2: float, p3: float) -> list[float]:
    """The parameter values in ``(0, 1)`` where one axis of a cubic Bézier
    curve (control coordinates ``p0..p3`` on that axis) has a local
    extremum: the roots of its derivative, itself a quadratic in ``t``."""
    d0 = p1 - p0
    d1 = p2 - p1
    d2 = p3 - p2
    a = d0 - 2 * d1 + d2
    b = 2 * (d1 - d0)
    c = d0
    return _quadratic_roots_in_unit_interval(a, b, c)


def _bezier_point(t: float, p0: Point, p1: Point, p2: Point, p3: Point) -> Point:
    """The cubic Bézier curve's own position at ``t`` -- not a control
    point, which generally lies off the curve entirely."""
    mt = 1.0 - t
    x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
    y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
    return (x, y)


def _curve_bbox_points(start: Point, segment: CurveSegment) -> list[Point]:
    """Every point needed for a tight bounding box of one cubic Bézier
    segment: both endpoints, plus the curve's actual position at each
    axis's extremum parameter (review fix round 1, issue #24: a control
    point like ``c1``/``c2`` is generally not on the curve at all, so using
    control points directly for the bbox overshoots the true bounds)."""
    p0, p1, p2, p3 = start, segment.c1, segment.c2, segment.end
    points = [start, segment.end]
    for t in _bezier_axis_extrema_ts(p0[0], p1[0], p2[0], p3[0]):
        points.append(_bezier_point(t, p0, p1, p2, p3))
    for t in _bezier_axis_extrema_ts(p0[1], p1[1], p2[1], p3[1]):
        points.append(_bezier_point(t, p0, p1, p2, p3))
    return points


def _subpath_bbox_points(subpath: Subpath) -> list[Point]:
    """Every point needed for a tight bounding box of a subpath: corner
    vertices and endpoints directly (straight lines have no interior
    extrema beyond their own endpoints), and each Bézier segment's true
    curve extrema (:func:`_curve_bbox_points`) -- never a raw control
    point on its own."""
    points = [subpath.start]
    pos = subpath.start
    for segment in subpath.segments:
        if isinstance(segment, CornerSegment):
            points.append(segment.through)
            points.append(segment.end)
        else:
            points.extend(_curve_bbox_points(pos, segment))
        pos = segment.end
    return points


def _bbox(points: Sequence[Point]) -> tuple[float, float, float, float]:
    """``(min_x, min_y, max_x, max_y)`` of ``points``."""
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _is_degenerate(subpath: Subpath) -> bool:
    """A subpath with zero bounding-box area: a single point, or every
    point collinear along one axis -- not real artwork (§8: "no zero-area
    subpaths"). potrace's own ``turdsize`` (recipe parameter
    ``speckle_size``) already discards small specks by pixel area; this is
    a cheap, independent backstop against a genuinely degenerate subpath
    slipping through."""
    min_x, min_y, max_x, max_y = _bbox(_subpath_bbox_points(subpath))
    return max_x <= min_x or max_y <= min_y


def tight_viewbox(subpaths: Sequence[Subpath]) -> tuple[float, float, float, float]:
    """``(min_x, min_y, width, height)`` tight to every subpath's true
    curve geometry (§8: "use clean document bounds") -- the smallest box
    containing all of it, not the tracer's source canvas size and not the
    (looser) control-point polygon."""
    min_x, min_y, max_x, max_y = _bbox([p for sp in subpaths for p in _subpath_bbox_points(sp)])
    return min_x, min_y, max_x - min_x, max_y - min_y


#: Decimal places kept when serialising a coordinate. Fixed, low precision
#: is deliberate (not just tidy): it is what makes serialisation
#: byte-identical across ubuntu and windows CI (the same concern
#: ``pipeline.transparent_png``'s module docstring raises for PNG bytes).
#: potrace's curve fitting runs ``math.sqrt``/``atan2``/``cos`` -- libm
#: calls that can differ in their last bit between platforms' C libraries
#: for the same input -- and any such difference is many orders of
#: magnitude smaller than one ten-thousandth of a pixel, so rounding here
#: absorbs it before it can reach the output text.
_DECIMAL_PLACES = 4


def format_number(value: float) -> str:
    """``value`` formatted deterministically: fixed precision, then
    trailing zeros (and a trailing ``.``) trimmed, and ``-0`` normalised to
    ``0`` -- so identical geometry always serialises to identical text
    (§36) regardless of which platform produced the float."""
    text = f"{value:.{_DECIMAL_PLACES}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _format_point(point: Point) -> str:
    return f"{format_number(point[0])},{format_number(point[1])}"


def render_path_d(subpaths: Sequence[Subpath]) -> str:
    """The ``d`` attribute value for every subpath, concatenated: ``M`` to
    each subpath's start, ``L``/``L`` for a corner (through the vertex,
    then to the segment's end) or ``C`` for a Bézier curve, ``Z`` to close
    -- the same command mapping potrace's own reference SVG backend uses,
    so a design tool reading this file sees the geometry potrace intended."""
    parts: list[str] = []
    for subpath in subpaths:
        parts.append(f"M{_format_point(subpath.start)}")
        for segment in subpath.segments:
            if isinstance(segment, CornerSegment):
                parts.append(f"L{_format_point(segment.through)}")
                parts.append(f"L{_format_point(segment.end)}")
            else:
                parts.append(
                    f"C{_format_point(segment.c1)} {_format_point(segment.c2)} "
                    f"{_format_point(segment.end)}"
                )
        parts.append("Z")
    return "".join(parts)


def render_svg(subpaths: Sequence[Subpath], *, fill: str, fill_rule: str = "evenodd") -> bytes:
    """A complete, §8-clean SVG document: one ``<path>`` (compound when
    ``subpaths`` has more than one entry), filled with ``fill``, no stroke,
    root ``viewBox`` tight to the geometry.

    ``fill_rule`` defaults to ``"evenodd"``: potrace's own reference SVG
    backend uses it for exactly this reason -- unlike ``"nonzero"``, it
    keeps a hole a hole regardless of which winding direction potrace
    happened to trace each subpath in, so this module never has to inspect
    or normalise winding to get holes right (§8: "a fill rule and winding
    under which holes stay holes").

    Raises ``ValueError`` if every subpath is degenerate (or there are
    none): there is no clean document bounds to compute (§8) and nothing
    would be visible anyway.
    """
    visible = [sp for sp in subpaths if not _is_degenerate(sp)]
    if not visible:
        raise ValueError("no non-degenerate geometry to render as an SVG")

    min_x, min_y, width, height = tight_viewbox(visible)
    view_box = (
        f"{format_number(min_x)} {format_number(min_y)} "
        f"{format_number(width)} {format_number(height)}"
    )
    path_d = render_path_d(visible)

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{view_box}" width="{format_number(width)}" height="{format_number(height)}">'
        f'<path fill="{fill}" fill-rule="{fill_rule}" stroke="none" d="{path_d}"/>'
        "</svg>"
    )
    return svg.encode("utf-8")
