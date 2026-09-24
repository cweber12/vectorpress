# pyright: basic
"""The one place that talks to ``svgelements`` (and Python's stdlib
``xml.etree.ElementTree``) directly (issue #37), mirroring
:mod:`vectorpress.pipeline._potrace_trace` and :mod:`vectorpress.pipeline.
_ndimage_cleanup`'s own split: every touch of a third-party parsing API is
isolated in this one small module, so :mod:`vectorpress.validate.cut_file`
stays a plain, fully-typed function from bytes to
:class:`~vectorpress.domain.finding.ValidationResult`. ``svgelements`` ships
no type stubs and no ``py.typed`` marker, so pyright infers its types from
source as broad ``Unknown`` unions in several places -- the ``# pyright:
basic`` at the top of this module is the same boundary this codebase's other
two library-wrapping modules draw for the same reason (their own module
docstrings explain it further); every public function this module exposes is
still fully, concretely typed.

**Library choice** (issue #37's "explain the choice in one PR paragraph"):
``svgelements`` is a pure-Python SVG path parser (no C extension, confirmed
by its installed layout -- a single ``.py`` module) -- it parses arbitrary
``d`` strings (absolute or relative, lines, cubic/quadratic Béziers, and
elliptical arcs) into segments with a uniform ``.point(t)`` sampling API,
which this module uses to flatten curves deterministically. It ships a
universal wheel, so it installs identically on ``ubuntu-latest`` and
``windows-latest`` with no system package. A ``<path>`` element's ``d`` is
parsed on its own, via ``svgelements.Path(d)`` directly rather than
``svgelements.SVG.parse`` on the whole document: the latter also applies the
root ``<svg>``'s own ``viewBox``-to-viewport transform, which would shift
every coordinate away from the plain numbers the ``d`` attribute (and this
module's own :func:`svg_viewbox_longest_side`) already uses -- and a
finding's location must stay in exactly the same "SVG user units" a human or
an editor already sees in the file (issue #37's "so it can be drawn over the
SVG"), not some further-transformed space.

**No ``shapely``.** The geometry this issue needs -- polygon area, bounding
box, a representative interior point, and point-in-polygon containment, to
group subpaths into holes and top-level pieces under the fill rule -- is
plain, deterministic arithmetic (shoelace area/centroid, ray-cast
containment), the same style already proven byte-identical across platforms
by :mod:`vectorpress.pipeline.svg_document`'s own Bézier-extrema bounding
box. Reaching for a GEOS-backed library like ``shapely`` for this would add a
second native dependency and a second thing to keep identical across
``ubuntu-latest``/``windows-latest`` for no behavior this module cannot
already express directly. Issue #41's overlap and self-intersection
detectors are the "later issue that needs... polygon boolean operations"
this paragraph once deferred -- they turn out not to need a general boolean
library either: "do two rings' boundaries cross at all" is a segment-
intersection test (:func:`find_ring_intersections`/
:func:`find_self_intersections`), the same plain, deterministic arithmetic
style as everything else here, not an area/union/difference computation.

**A scoped simplification, not a full nonzero-winding implementation.**
Whether a subpath is a hole of its immediate parent is decided by
containment-depth parity alone (odd depth = hole), which is exactly the
even-odd fill rule's own definition. :mod:`vectorpress.pipeline.cut_svg`
always writes ``fill-rule="evenodd"``, and every fixture and test this issue
exercises uses simple, non-self-intersecting, well-nested subpaths (the only
shape a hand-authored override is likely to produce for a cut file too), so
depth parity gives the same grouping a full nonzero-winding computation
would. A path that actually relies on winding direction under
``fill-rule="nonzero"`` (two same-direction overlapping contours) is outside
this tracer's scope -- no finding kind this issue detects would misclassify
it as anything worse than an extra or missing fragment, and a later issue
can extend this if a real cut file ever needs it.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass

import svgelements as se

from vectorpress.domain.finding import BoundingBox
from vectorpress.domain.numeric_format import round_number

Point = tuple[float, float]

#: Fixed sample count per curved segment (cubic/quadratic Bézier, arc) when
#: flattening it to line segments -- deterministic (no adaptive subdivision
#: that could react differently to libm's last-bit platform differences),
#: matching the fixed-step style ``tests/unit/test_pipeline_cut_svg.py``'s
#: own ``_flatten_cubic`` test helper already uses to check this generator's
#: geometry.
_CURVE_STEPS = 24

_LENGTH_RE = re.compile(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?")
_VIEWBOX_SPLIT_RE = re.compile(r"[\s,]+")


def _local_name(tag: str) -> str:
    """An XML tag's local name, stripping any ``{namespace}`` prefix
    ``ElementTree`` leaves on it."""
    return tag.rsplit("}", 1)[-1]


def _parse_length(value: str) -> float:
    """The leading numeric portion of an SVG length attribute (``"12.5"``,
    ``"12.5px"``, ``"3in"``) as a plain float -- a validated SVG's ``width``/
    ``height`` are unitless numbers in practice (this codebase's own writer
    never emits a unit suffix), but a hand-edited override might."""
    match = _LENGTH_RE.match(value.strip())
    if match is None:
        raise ValueError(f"not a numeric length: {value!r}")
    return float(match.group())


def svg_viewbox_longest_side(svg_bytes: bytes) -> float:
    """The longest side of the root ``<svg>``'s ``viewBox``, falling back to
    its ``width``/``height`` (issue #37's "Physical scale"): the basis for
    converting a physical-unit threshold (§9.1) into this document's own
    user units, the same role :mod:`vectorpress.pipeline.cut_svg`'s own
    ``_bbox_longest_side_px`` plays for the source raster at generation time.

    Raises :class:`ValueError` when the root element has neither -- there is
    no scale to validate physical thresholds against, so the caller must
    treat this as a validation failure (§35), never a passing result.
    """
    root = ET.fromstring(svg_bytes)
    view_box = root.attrib.get("viewBox")
    if view_box is not None:
        parts = [p for p in _VIEWBOX_SPLIT_RE.split(view_box.strip()) if p]
        if len(parts) == 4:
            _min_x, _min_y, width, height = (float(p) for p in parts)
            return max(width, height)

    sides = [
        _parse_length(value)
        for value in (root.attrib.get("width"), root.attrib.get("height"))
        if value is not None
    ]
    if sides:
        return max(sides)

    raise ValueError("SVG has neither a viewBox nor width/height to establish a scale from")


def _node_count(subpath: se.Subpath) -> int:
    """The number of anchor points a human editor would see on ``subpath``
    (issue #40, §9's "excessive geometric complexity"): every ``Move``,
    ``Line``, curve or ``Arc`` segment contributes one node at its own end
    point -- a ``Move`` plus ``n`` further segments describes ``n + 1``
    distinct anchors -- while ``Close`` (a zero-length return to the
    subpath's start, never a new anchor of its own) is not counted. This is
    the *authored* node count -- ``svgelements``' own segment list, exactly
    as potrace's curve fitting (or a hand-authored override) wrote it --
    never :func:`_flatten_subpath`'s fixed-step curve sampling, which would
    report the same, constant :data:`_CURVE_STEPS`-per-curve count for
    every path regardless of how few or many curves it actually has."""
    return sum(1 for segment in subpath if not isinstance(segment, se.Close))


def _flatten_subpath(subpath: se.Subpath) -> list[Point]:
    """One subpath's geometry as a flat polygon ring: every corner vertex
    directly, every curved segment sampled at :data:`_CURVE_STEPS` fixed
    steps (never a raw control point, which is generally not on the curve
    itself -- the same reasoning :mod:`vectorpress.pipeline.svg_document`'s
    own bounding-box code documents)."""
    points: list[Point] = []
    for segment in subpath:
        if isinstance(segment, se.Move | se.Line | se.Close):
            end = segment.end
            # every Move/Line/Close this module ever sees is a concrete,
            # anchored point -- never svgelements' own "unspecified" sentinel.
            assert end is not None
            assert end.x is not None
            assert end.y is not None
            points.append((float(end.x), float(end.y)))
            continue
        for step in range(1, _CURVE_STEPS + 1):
            # ``svgelements`` samples a curved segment's ``.point()`` with
            # numpy internally, returning ``numpy.float64`` rather than a
            # plain ``float`` -- coerced here, once, so every coordinate
            # downstream (bounding boxes included) is plain-``float``,
            # JSON-serializable without a custom encoder.
            sampled = segment.point(step / _CURVE_STEPS)
            points.append((float(sampled.x), float(sampled.y)))
    return points


def _polygon_area(points: list[Point]) -> float:
    """A polygon's unsigned area via the shoelace formula."""
    total = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _polygon_bbox(points: list[Point]) -> BoundingBox:
    """``points``'s tight bounding box, rounded to
    :data:`~vectorpress.domain.numeric_format.DECIMAL_PLACES` (issue #37 fix
    round 1): a curved segment's flattened points come from
    ``svgelements``' own ``numpy``-backed ``.point(t)`` sampling, which can
    differ in its last bit between platforms' C libraries for identical
    input the same way potrace's own curve fitting can -- rounded here, at
    the point a finding's location is actually built, the same fixed-
    precision rule :mod:`vectorpress.pipeline.svg_document` already applies
    to SVG coordinate text keeps findings JSON byte-identical across
    ubuntu and windows too (§36)."""
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return BoundingBox(
        min_x=round_number(min(xs)),
        min_y=round_number(min(ys)),
        max_x=round_number(max(xs)),
        max_y=round_number(max(ys)),
    )


def _polygon_representative_point(points: list[Point]) -> Point:
    """A point inside ``points`` used to test containment against sibling
    subpaths: the area-weighted centroid, which lands inside any star-shaped
    polygon (every shape this issue's fixtures and tests produce -- potrace
    output and simple hand-authored shapes alike). A degenerate polygon
    (zero signed area -- a line-like sliver) falls back to the plain average
    of its vertices."""
    n = len(points)
    signed_area = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        signed_area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    signed_area /= 2.0
    if abs(signed_area) < 1e-9:
        xs = [x for x, _y in points]
        ys = [y for _x, y in points]
        return (sum(xs) / n, sum(ys) / n)
    return (cx / (6.0 * signed_area), cy / (6.0 * signed_area))


def _point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    """Even-odd ray-cast point membership (matches
    :func:`vectorpress.pipeline.svg_document.render_svg`'s own fill rule and
    the identical test helper in ``tests/unit/test_pipeline_cut_svg.py``)."""
    px, py = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            x_at_y = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if x_at_y > px:
                inside = not inside
    return inside


@dataclass(frozen=True)
class Piece:
    """One candidate disconnected cut piece: a subpath not nested inside an
    odd number of its siblings (so, under even-odd, a filled shell rather
    than a hole), identified by where it sits in the document (issue #37's
    "path reference"), its own bounding box, and its net area (its own
    shell, minus any holes directly inside it) -- used to rank "the largest"
    piece among several.

    ``node_count``, ``outer_ring`` and ``hole_rings`` (issue #40) are this
    piece's own authored geometry, needed by :mod:`vectorpress.validate.
    excessive_complexity` (node density against physical perimeter) and
    :mod:`vectorpress.validate.narrow_feature` (rasterizing this piece --
    its own shell minus its own immediate holes, the same even-odd shape
    the SVG itself renders -- to measure a local width). ``outer_ring`` is
    this piece's own flattened boundary (:func:`_flatten_subpath`);
    ``hole_rings`` are its immediate holes' flattened boundaries only (a
    hole nested inside one of *those* holes would itself be a further
    piece, not one of this piece's own ``hole_rings`` -- out of scope for
    both consumers, the same "well-nested, simple" scope this module's own
    docstring already draws)."""

    element_index: int
    subpath_index: int
    element_id: str | None
    bbox: BoundingBox
    area: float
    node_count: int
    outer_ring: tuple[Point, ...]
    hole_rings: tuple[tuple[Point, ...], ...]

    @property
    def largest_dimension(self) -> float:
        """The longer side of this piece's own bounding box, in the same
        SVG user units as :attr:`bbox` (issue #39): the basis for telling an
        elongated sliver (a small area but a large extent in one direction)
        from a genuine dot (small in every direction) -- the same "longest
        side of a bounding box" measure :func:`svg_viewbox_longest_side`
        already uses for the document's own physical scale, applied here to
        one piece instead of the whole document."""
        return max(self.bbox.max_x - self.bbox.min_x, self.bbox.max_y - self.bbox.min_y)


@dataclass(frozen=True)
class Hole:
    """One interior ring (odd containment depth under even-odd fill),
    subtracted from its immediate parent :class:`Piece`'s own area -- a
    candidate very small hole (issue #39), identified the same way a
    :class:`Piece` is: where it sits in the document, its own bounding box,
    and its own (un-subtracted) area."""

    element_index: int
    subpath_index: int
    element_id: str | None
    bbox: BoundingBox
    area: float


def non_largest_pieces(pieces: list[Piece]) -> list[Piece]:
    """Every piece except the largest by area (issue #39): the shared
    "isolated shape" candidate pool every area-based §9 detector
    (:mod:`vectorpress.validate.accidental_dot`, :mod:`vectorpress.validate.
    tiny_isolated_shape`) and :mod:`vectorpress.validate.
    disconnected_fragments` all scope themselves to -- a document with zero
    or one piece has nothing isolated from anything else, so it yields
    nothing. Ties on area keep whichever :func:`max` happens to pick as "the
    largest" (arbitrary but consistent within one call), matching
    :mod:`vectorpress.validate.disconnected_fragments`'s own pre-issue-#39
    behavior exactly."""
    if len(pieces) <= 1:
        return []
    largest = max(pieces, key=lambda piece: piece.area)
    return [piece for piece in pieces if piece is not largest]


@dataclass(frozen=True)
class ParsedCutFile:
    """Everything :mod:`vectorpress.validate.cut_file`'s detectors need from
    one SVG: its candidate pieces, its candidate holes, and the physical
    scale (§9.1) a threshold-based detector converts a physical-unit
    threshold with -- ``reference_size_in`` physical inches map onto
    :attr:`scale_user_units_per_inch` user units."""

    pieces: list[Piece]
    holes: list[Hole]
    scale_user_units_per_inch: float


def parse_cut_file(svg_bytes: bytes, reference_size_in: float) -> ParsedCutFile:
    """Parse ``svg_bytes`` into its candidate pieces and physical scale
    (issue #37).

    Every ``<path>`` element in document order contributes its own
    subpaths (:func:`_flatten_subpath`); a subpath's containment depth among
    *every* subpath in the document (not just its own element's) decides
    whether it is a hole (odd depth, subtracted from its immediate parent's
    area) or a piece's own shell (even depth) -- so restructuring one shape
    across several ``<path>`` elements, as a hand-edited override might,
    does not change how many physical pieces are found.

    Raises :class:`ValueError` (from :func:`svg_viewbox_longest_side`, or
    from ``ElementTree``/``svgelements`` on unparseable XML or path data) for
    an SVG this cannot establish a scale for or make sense of at all --
    :mod:`vectorpress.validate.cut_file` lets this propagate as a validation
    failure (§35), never a passing result.
    """
    longest_side = svg_viewbox_longest_side(svg_bytes)
    scale = longest_side / reference_size_in

    root = ET.fromstring(svg_bytes)
    path_elements = [element for element in root.iter() if _local_name(element.tag) == "path"]

    subpaths: list[tuple[int, int, str | None, list[Point], int]] = []
    for element_index, element in enumerate(path_elements):
        d = element.attrib.get("d", "")
        element_id = element.attrib.get("id")
        for subpath_index, subpath in enumerate(se.Path(d).as_subpaths()):
            points = _flatten_subpath(subpath)
            if len(points) < 3:
                continue  # not a real polygon: an empty or degenerate subpath
            subpaths.append(
                (element_index, subpath_index, element_id, points, _node_count(subpath))
            )

    polygons = [record[3] for record in subpaths]
    areas = [_polygon_area(polygon) for polygon in polygons]
    representative_points = [_polygon_representative_point(polygon) for polygon in polygons]
    # A candidate container ``j`` must have a strictly larger area than ``i``
    # (issue #39 fix round 1): under this module's own "well-nested"
    # simplification, two subpaths whose interiors share a point are either
    # disjoint or one strictly contains the other, and a container is always
    # the bigger of the two. Without this guard, a shape whose own
    # representative point (its centroid) happens to land inside a much
    # smaller sibling -- a hole placed dead-center inside its own parent
    # shell, for example, the natural way to draw one -- would wrongly count
    # as "contained in" that sibling too, on nothing more than coincidental
    # point placement, corrupting which subpaths are real pieces at all.
    depths = [
        sum(
            1
            for j, polygon in enumerate(polygons)
            if j != i
            and areas[j] > areas[i]
            and _point_in_polygon(representative_points[i], polygon)
        )
        for i in range(len(polygons))
    ]
    parents: list[int | None] = []
    for i in range(len(polygons)):
        if depths[i] == 0:
            parents.append(None)
            continue
        candidates = [
            j
            for j in range(len(polygons))
            if j != i
            and depths[j] == depths[i] - 1
            and areas[j] > areas[i]
            and _point_in_polygon(representative_points[i], polygons[j])
        ]
        parents.append(min(candidates, key=lambda j: areas[j]) if candidates else None)

    pieces: list[Piece] = []
    holes: list[Hole] = []
    for i, (element_index, subpath_index, element_id, points, node_count) in enumerate(subpaths):
        if depths[i] % 2 != 0:
            # A hole, not a piece of its own -- subtracted from its parent's
            # area below, and recorded in its own right (issue #39) as a
            # candidate very small hole.
            holes.append(
                Hole(
                    element_index=element_index,
                    subpath_index=subpath_index,
                    element_id=element_id,
                    bbox=_polygon_bbox(points),
                    area=areas[i],
                )
            )
            continue
        own_hole_indices = [
            j for j in range(len(polygons)) if depths[j] == depths[i] + 1 and parents[j] == i
        ]
        hole_area = sum(areas[j] for j in own_hole_indices)
        pieces.append(
            Piece(
                element_index=element_index,
                subpath_index=subpath_index,
                element_id=element_id,
                bbox=_polygon_bbox(points),
                area=areas[i] - hole_area,
                node_count=node_count,
                outer_ring=tuple(points),
                hole_rings=tuple(tuple(polygons[j]) for j in own_hole_indices),
            )
        )

    return ParsedCutFile(pieces=pieces, holes=holes, scale_user_units_per_inch=scale)


# ---------------------------------------------------------------------------
# Raw subpaths, document elements and segment intersection (issue #41)
#
# Everything below serves the five §9 kinds only a hand-edited SVG can trip
# (open path, raster content, stray object, duplicate geometry, unintended
# overlap): :mod:`vectorpress.validate.open_path`, :mod:`vectorpress.
# validate.raster_content`, :mod:`vectorpress.validate.stray_object`,
# :mod:`vectorpress.validate.duplicate_geometry` and :mod:`vectorpress.
# validate.overlap`. Unlike :class:`Piece`/:class:`Hole` above, none of this
# groups a subpath by containment parity: :func:`parse_subpaths` returns
# every subpath exactly as authored, and :func:`parse_document_elements`
# every element exactly as it sits in the document -- the "well-nested,
# non-overlapping" simplification this module's own docstring draws around
# piece/hole grouping does not hold for a document that is, by definition,
# possibly malformed.
# ---------------------------------------------------------------------------

#: A subpath's own end point landing on its own start within this many user
#: units still counts as closed (issue #41's :mod:`vectorpress.validate.
#: open_path`) even without an explicit ``Z`` -- a hand-authored override
#: might close a shape by repeating the start coordinate as its last ``L``
#: instead. Deliberately tiny: this is a tolerance for "the same point
#: written twice", not a snapping distance.
_CLOSE_TOLERANCE = 1e-6

#: The fixed epsilon a signed area (twice a triangle's own area, in squared
#: user units) must clear before :func:`_segments_properly_intersect`
#: treats it as a genuine, non-collinear side -- absorbs the same kind of
#: last-bit floating-point noise :data:`~vectorpress.domain.numeric_format.
#: DECIMAL_PLACES` exists to absorb elsewhere in this module, without being
#: anywhere close to a real crossing's own signed area for any shape this
#: tool's fixtures or a plausible hand-edited override would produce.
_INTERSECTION_EPS = 1e-6

#: Tags this module computes a definite bounding box for (issue #41) --
#: every other tag (``g``, ``text``, ``pattern``, ``foreignObject``, …) gets
#: ``bbox=None`` from :func:`_generic_element_bbox`: no made-up box, only a
#: real one when the shape's own geometry is simple, closed-form arithmetic
#: (this module's own "plain, deterministic arithmetic... no shapely"
#: choice, applied here to a handful of common shape elements rather than
#: just ``<path>``).
_BBOX_TAGS = frozenset(
    {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "image"}
)

#: Tags whose own subtree is never rendered directly -- only ever
#: *referenced* (a gradient, a clip path, a pattern tile, a reusable
#: symbol) -- so an element inside one is never itself a stray object
#: (issue #41's :mod:`vectorpress.validate.stray_object`): an off-canvas or
#: seemingly invisible shape *inside a ``<pattern>``'s own tile*, for
#: example, is exactly how a legitimate pattern is defined, not a mistake.
#: :mod:`vectorpress.validate.raster_content` does not consult this --
#: exactly the opposite case, a ``<pattern>`` carrying raster content, is
#: still a real problem regardless of never being rendered on its own.
_NON_RENDERING_CONTAINER_TAGS = frozenset(
    {"defs", "symbol", "clipPath", "mask", "marker", "pattern"}
)


def parse_style_declarations(attrib: Mapping[str, str]) -> dict[str, str]:
    """``style``'s own ``property: value`` declarations, parsed once
    (issue #41 review fix round 1) -- shared by :func:`_element_has_fill`
    and :mod:`vectorpress.validate.stray_object`'s own ``_is_invisible``,
    both of which need to check a ``style`` declaration with the same
    "a style declaration wins over the plain attribute" precedence SVG
    itself gives it, rather than each re-parsing ``style`` on its own."""
    style = attrib.get("style", "")
    declarations: dict[str, str] = {}
    for declaration in style.split(";"):
        name, _sep, value = declaration.partition(":")
        name = name.strip().lower()
        if name:
            declarations[name] = value.strip()
    return declarations


def effective_attribute(attrib: Mapping[str, str], name: str) -> str | None:
    """``attrib``'s own effective value for presentation attribute
    ``name`` (issue #41 review fix round 1): a ``style`` declaration wins
    over the plain attribute (SVG's own precedence), falling back to the
    plain attribute, then ``None`` when neither is set."""
    declarations = parse_style_declarations(attrib)
    if name in declarations:
        return declarations[name]
    return attrib.get(name)


def _element_has_fill(attrib: Mapping[str, str]) -> bool:
    """Whether a ``<path>`` element's own attributes paint a fill at all
    (§9's "a path with no fill, where a closed filled path is expected") --
    SVG's own default (no ``fill`` attribute, no ``style`` override) is a
    *filled* black shape, so only an explicit ``none`` (the ``fill``
    attribute, or a ``fill`` declaration inside ``style``) counts as "no
    fill"."""
    effective = effective_attribute(attrib, "fill")
    return effective is None or effective.strip().lower() != "none"


def _subpath_is_closed(subpath: se.Subpath, points: list[Point]) -> bool:
    """Whether ``subpath`` is closed (§9's "a subpath that is not closed --
    no Z and its end is not its start"): an explicit ``Close`` segment, or
    its own flattened end point landing back on its own start point within
    :data:`_CLOSE_TOLERANCE`."""
    if any(isinstance(segment, se.Close) for segment in subpath):
        return True
    if len(points) < 2:
        return False
    (start_x, start_y), (end_x, end_y) = points[0], points[-1]
    return abs(start_x - end_x) < _CLOSE_TOLERANCE and abs(start_y - end_y) < _CLOSE_TOLERANCE


@dataclass(frozen=True)
class Subpath:
    """One subpath's own raw geometry (issue #41): every subpath any
    ``<path>`` element in the document has, independent of the piece/hole
    containment-parity grouping :class:`Piece`/:class:`Hole` compute above
    -- :mod:`vectorpress.validate.open_path`, :mod:`vectorpress.validate.
    duplicate_geometry` and :mod:`vectorpress.validate.overlap` all need
    every subpath exactly as authored: the last two by design (their own
    module docstrings say why grouping is the wrong basis for them), the
    first because a genuinely unclosed subpath cannot be reliably
    classified as a piece or a hole to begin with."""

    element_index: int
    subpath_index: int
    element_id: str | None
    points: tuple[Point, ...]
    bbox: BoundingBox
    closed: bool
    has_fill: bool


def parse_subpaths(svg_bytes: bytes) -> list[Subpath]:
    """Every subpath in the document, in document order, exactly as
    authored (issue #41) -- unlike :func:`parse_cut_file`, this never
    groups a subpath into a piece or a hole.

    Only a truly empty subpath (a bare ``Move`` with nothing after it, no
    points at all -- ``len(points) < 2``) is dropped here (issue #41
    review fix round 1): a two-point subpath, a bare open line segment
    such as ``<path d="M0,0 L50,50"/>``, is kept -- it is exactly §9's
    simplest "a subpath that is not closed" case, and dropping it here
    would hide it from :mod:`vectorpress.validate.open_path` entirely, the
    one detector that needs to see it. :mod:`vectorpress.validate.
    duplicate_geometry` and :mod:`vectorpress.validate.overlap` -- the
    other two consumers of this function's own output -- filter a
    fewer-than-three-point subpath back out themselves (their own modules'
    docstrings): neither "the same geometry" nor "a self-intersecting
    ring" means anything for a shape with no real interior.

    Raises :class:`ValueError` the same way :func:`parse_cut_file` does,
    for unparseable XML or path data (§35)."""
    root = ET.fromstring(svg_bytes)
    path_elements = [element for element in root.iter() if _local_name(element.tag) == "path"]

    subpaths: list[Subpath] = []
    for element_index, element in enumerate(path_elements):
        d = element.attrib.get("d", "")
        element_id = element.attrib.get("id")
        has_fill = _element_has_fill(element.attrib)
        for subpath_index, subpath in enumerate(se.Path(d).as_subpaths()):
            points = _flatten_subpath(subpath)
            if len(points) < 2:
                continue  # truly empty: a bare Move with nothing after it
            subpaths.append(
                Subpath(
                    element_index=element_index,
                    subpath_index=subpath_index,
                    element_id=element_id,
                    points=tuple(points),
                    bbox=_polygon_bbox(points),
                    closed=_subpath_is_closed(subpath, points),
                    has_fill=has_fill,
                )
            )
    return subpaths


def _root_bbox(root: ET.Element) -> BoundingBox:
    """The root ``<svg>``'s own bounding box, from its ``viewBox`` (its own
    ``min-x``/``min-y``/width/height, so an offset viewBox is honored, not
    assumed to start at the origin) or, failing that, ``width``/``height``
    starting at the origin (issue #41) -- a separate, small function from
    :func:`svg_viewbox_longest_side` (which only ever needs one number, and
    tolerates a single ``width`` *or* ``height`` alone): the actual 2-D box
    :func:`parse_document_elements` needs to test an element's own bbox
    against for "off canvas" has no single-sided equivalent, so this
    requires both ``width`` and ``height`` together when there is no
    ``viewBox``.

    Raises :class:`ValueError` for a root with neither (§35)."""
    view_box = root.attrib.get("viewBox")
    if view_box is not None:
        parts = [p for p in _VIEWBOX_SPLIT_RE.split(view_box.strip()) if p]
        if len(parts) == 4:
            min_x, min_y, width, height = (float(p) for p in parts)
            return BoundingBox(min_x=min_x, min_y=min_y, max_x=min_x + width, max_y=min_y + height)

    width_attr = root.attrib.get("width")
    height_attr = root.attrib.get("height")
    if width_attr is not None and height_attr is not None:
        width = _parse_length(width_attr)
        height = _parse_length(height_attr)
        return BoundingBox(min_x=0.0, min_y=0.0, max_x=width, max_y=height)

    raise ValueError("SVG has neither a viewBox nor width/height to establish a scale from")


def _parse_points_attr(value: str) -> list[Point]:
    """A ``points`` attribute (``<polyline>``/``<polygon>``) as ``(x, y)``
    pairs, tolerating either comma or whitespace separators the same way
    SVG itself does."""
    numbers = [float(match) for match in _LENGTH_RE.findall(value)]
    return list(zip(numbers[0::2], numbers[1::2], strict=False))


def _bbox(min_x: float, min_y: float, max_x: float, max_y: float) -> BoundingBox:
    """A :class:`~vectorpress.domain.finding.BoundingBox` with every
    coordinate rounded (:func:`~vectorpress.domain.numeric_format.
    round_number`) -- the same "rounded at the point a finding's location
    is actually built" rule :func:`_polygon_bbox` already applies, kept
    here too so every bbox this module ever produces, path-flattened or a
    plain shape element's own attributes alike, is rounded the same way."""
    return BoundingBox(
        min_x=round_number(min_x),
        min_y=round_number(min_y),
        max_x=round_number(max_x),
        max_y=round_number(max_y),
    )


def _generic_element_bbox(tag: str, attrib: Mapping[str, str]) -> BoundingBox | None:
    """``tag``'s own bounding box computed from its own attributes alone
    (issue #41's :mod:`vectorpress.validate.stray_object`) -- deliberately
    narrow: only the handful of shape elements a hand-edited cut-file
    override plausibly contains (:data:`_BBOX_TAGS`), each a closed-form
    read of its own geometry attributes (no ``transform`` resolution -- the
    same plain-user-unit-coordinates scope :func:`svg_viewbox_longest_side`'s
    own docstring already draws for this module). Returns ``None`` for any
    tag not in that set, or one whose own attributes do not parse (a
    malformed override, or a required attribute simply absent) -- never a
    made-up box."""
    try:
        if tag == "rect":
            x = _parse_length(attrib.get("x", "0"))
            y = _parse_length(attrib.get("y", "0"))
            width = _parse_length(attrib["width"])
            height = _parse_length(attrib["height"])
            return _bbox(x, y, x + width, y + height)
        if tag == "circle":
            cx = _parse_length(attrib.get("cx", "0"))
            cy = _parse_length(attrib.get("cy", "0"))
            r = _parse_length(attrib["r"])
            return _bbox(cx - r, cy - r, cx + r, cy + r)
        if tag == "ellipse":
            cx = _parse_length(attrib.get("cx", "0"))
            cy = _parse_length(attrib.get("cy", "0"))
            rx = _parse_length(attrib["rx"])
            ry = _parse_length(attrib["ry"])
            return _bbox(cx - rx, cy - ry, cx + rx, cy + ry)
        if tag == "line":
            x1 = _parse_length(attrib["x1"])
            y1 = _parse_length(attrib["y1"])
            x2 = _parse_length(attrib["x2"])
            y2 = _parse_length(attrib["y2"])
            return _bbox(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        if tag in ("polyline", "polygon"):
            points = _parse_points_attr(attrib.get("points", ""))
            if not points:
                return None
            xs = [x for x, _y in points]
            ys = [y for _x, y in points]
            return _bbox(min(xs), min(ys), max(xs), max(ys))
        if tag == "image":
            x = _parse_length(attrib.get("x", "0"))
            y = _parse_length(attrib.get("y", "0"))
            width = _parse_length(attrib["width"])
            height = _parse_length(attrib["height"])
            return _bbox(x, y, x + width, y + height)
        if tag == "path":
            all_points: list[Point] = []
            for subpath in se.Path(attrib.get("d", "")).as_subpaths():
                all_points.extend(_flatten_subpath(subpath))
            if not all_points:
                return None
            return _polygon_bbox(all_points)
    except (KeyError, ValueError):
        return None
    return None


def _has_own_data_uri(attrib: Mapping[str, str]) -> bool:
    """Whether any of ``attrib``'s own values contains a ``data:`` URI (§9's
    "a ``data:`` image URI anywhere") -- checked against every attribute,
    not just ``href``/``xlink:href``, since a raster image can just as well
    be smuggled in through a ``style`` declaration (``fill:url(data:...)``)."""
    return any("data:" in value for value in attrib.values())


def _subtree_has_raster(element: ET.Element) -> bool:
    """Whether ``element`` or any of its descendants is an ``<image>``, or
    carries a ``data:`` URI of its own (issue #41's :mod:`vectorpress.
    validate.raster_content`) -- the basis for "a pattern/foreignObject
    carrying raster content": a ``<pattern>`` or ``<foreignObject>`` is
    flagged when its own subtree contains either, not only when the
    element itself does."""
    for descendant in element.iter():
        if _local_name(descendant.tag) == "image":
            return True
        if _has_own_data_uri(descendant.attrib):
            return True
    return False


def _build_parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    """``{child: parent}`` for every element under ``root`` -- ``ElementTree``
    keeps no parent pointers of its own, so this is built once per document
    (issue #41's :func:`_is_rendered`)."""
    return {child: parent for parent in root.iter() for child in parent}


def _is_rendered(element: ET.Element, parent_map: Mapping[ET.Element, ET.Element]) -> bool:
    """Whether ``element`` is ever actually drawn -- ``False`` when any
    ancestor is a non-rendering container (:data:`_NON_RENDERING_CONTAINER_TAGS`,
    issue #41's :mod:`vectorpress.validate.stray_object`)."""
    current = parent_map.get(element)
    while current is not None:
        if _local_name(current.tag) in _NON_RENDERING_CONTAINER_TAGS:
            return False
        current = parent_map.get(current)
    return True


#: Tags :func:`_inside_raster_container` walks up looking for -- the same
#: two tags :mod:`vectorpress.validate.raster_content` itself flags as
#: "carrying raster content" when their own subtree has any.
_RASTER_CONTAINER_TAGS = frozenset({"pattern", "foreignObject"})


def _inside_raster_container(
    element: ET.Element, parent_map: Mapping[ET.Element, ET.Element]
) -> bool:
    """Whether some ancestor of ``element`` is itself a ``<pattern>`` or
    ``<foreignObject>`` (issue #41's :mod:`vectorpress.validate.
    raster_content`): that ancestor's own subtree scan (:func:`_subtree_has_raster`)
    already finds and reports whatever raster content ``element`` itself
    might be or carry, so ``element`` is never *also* independently
    flagged -- one finding for the container, not one for the container
    and a second for each raster descendant inside it."""
    current = parent_map.get(element)
    while current is not None:
        if _local_name(current.tag) in _RASTER_CONTAINER_TAGS:
            return True
        current = parent_map.get(current)
    return False


@dataclass(frozen=True)
class DocumentElement:
    """One element in the document, document order, root ``<svg>`` excluded
    (issue #41) -- the basis for :mod:`vectorpress.validate.raster_content`
    and :mod:`vectorpress.validate.stray_object`, which reason about whole
    elements (a stray ``<image>``, an empty ``<g>``, off-canvas geometry)
    rather than a ``<path>``'s own subpaths.

    ``bbox`` is ``None`` for a tag this module has no simple, closed-form
    geometry for, or one whose own attributes did not parse
    (:func:`_generic_element_bbox`) -- never a made-up box (Finding's own
    "no geometry, no bbox" rule). ``has_own_data_uri`` and
    ``subtree_has_raster`` are :func:`_has_own_data_uri`/
    :func:`_subtree_has_raster`'s own results, computed once here rather
    than re-walked per detector. ``rendered`` is :func:`_is_rendered`'s own
    result -- :mod:`vectorpress.validate.stray_object` only ever judges a
    rendered element a stray object; :mod:`vectorpress.validate.
    raster_content` ignores this field, since a pattern tile or a clip path
    can still carry raster content worth flagging even though it is never
    rendered on its own. ``inside_raster_container`` is :func:`_inside_raster_container`'s
    own result -- :mod:`vectorpress.validate.raster_content` skips an
    element inside a ``<pattern>``/``<foreignObject>`` it already reports
    on its own, so raster content nested inside one is never
    double-counted."""

    element_index: int
    tag: str
    element_id: str | None
    bbox: BoundingBox | None
    has_own_data_uri: bool
    subtree_has_raster: bool
    has_children: bool
    attrib: Mapping[str, str]
    rendered: bool
    inside_raster_container: bool


def parse_document_elements(svg_bytes: bytes) -> tuple[BoundingBox, list[DocumentElement]]:
    """The document's own bounding box (:func:`_root_bbox`), plus every
    element in it excluding the root ``<svg>`` (issue #41) -- the shared
    parse :mod:`vectorpress.validate.raster_content` and
    :mod:`vectorpress.validate.stray_object` both work from.

    Raises :class:`ValueError` the same way :func:`_root_bbox` does, for a
    root with neither a ``viewBox`` nor ``width``/``height`` (§35)."""
    root = ET.fromstring(svg_bytes)
    view_box = _root_bbox(root)
    parent_map = _build_parent_map(root)

    elements: list[DocumentElement] = []
    for element_index, element in enumerate(child for child in root.iter() if child is not root):
        tag = _local_name(element.tag)
        elements.append(
            DocumentElement(
                element_index=element_index,
                tag=tag,
                element_id=element.attrib.get("id"),
                bbox=_generic_element_bbox(tag, element.attrib),
                has_own_data_uri=_has_own_data_uri(element.attrib),
                subtree_has_raster=_subtree_has_raster(element),
                has_children=len(list(element)) > 0,
                attrib=dict(element.attrib),
                rendered=_is_rendered(element, parent_map),
                inside_raster_container=_inside_raster_container(element, parent_map),
            )
        )
    return view_box, elements


def _strict_sign(value: float) -> int:
    """-1/0/1, with anything inside :data:`_INTERSECTION_EPS` of zero
    treated as exactly zero (collinear) -- :func:`_segments_properly_intersect`'s
    own tolerance for floating-point noise."""
    if value > _INTERSECTION_EPS:
        return 1
    if value < -_INTERSECTION_EPS:
        return -1
    return 0


def _orientation(a: Point, b: Point, c: Point) -> float:
    """Twice the signed area of triangle ``abc`` -- positive when ``c`` is
    left of ray ``a->b``, negative when right, (near) zero when collinear.
    The one primitive :func:`_segments_properly_intersect` builds on."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_properly_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> Point | None:
    """The point where segments ``p1p2`` and ``p3p4`` cross *transversally*
    -- each segment's own two endpoints strictly on opposite sides of the
    other -- or ``None`` when they do not (issue #41's overlap/self-
    intersection detectors): two segments that only touch at a shared
    endpoint, or run collinear along a shared edge (two identical, stacked
    subpaths' own coincident edges, say), are deliberately **not** a
    crossing -- that is :mod:`vectorpress.validate.duplicate_geometry`'s
    concern, not :mod:`vectorpress.validate.overlap`'s.

    A cheap bounding-box rejection runs first: the dominant cost for a
    finely traced outline's own self-intersection scan (hundreds of
    flattened points, an edge pair for every non-adjacent pair) is the
    sheer number of pairs, not the handful of multiplications the full test
    itself needs, so rejecting spatially-disjoint pairs cheaply first is
    the one optimization worth making here."""
    if max(p1[0], p2[0]) < min(p3[0], p4[0]) or max(p3[0], p4[0]) < min(p1[0], p2[0]):
        return None
    if max(p1[1], p2[1]) < min(p3[1], p4[1]) or max(p3[1], p4[1]) < min(p1[1], p2[1]):
        return None

    s1 = _strict_sign(_orientation(p3, p4, p1))
    s2 = _strict_sign(_orientation(p3, p4, p2))
    s3 = _strict_sign(_orientation(p1, p2, p3))
    s4 = _strict_sign(_orientation(p1, p2, p4))
    if s1 == 0 or s2 == 0 or s3 == 0 or s4 == 0:
        return None  # touching or collinear -- not a proper crossing
    if s1 == s2 or s3 == s4:
        return None

    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) < 1e-12:
        return None  # parallel -- the sign test above should already exclude this
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denominator
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denominator
    return (px, py)


def find_self_intersections(points: tuple[Point, ...]) -> list[Point]:
    """Every point where two non-adjacent edges of the one closed ring
    ``points`` (already implicitly closed, like every other polygon helper
    in this module) cross transversally (§9's "a self-intersecting
    subpath", issue #41) -- a bowtie is the simplest case: two edges on
    opposite sides of the ring crossing each other. Adjacent edges (sharing
    a vertex, including the wrap-around pair) are never tested against each
    other -- they always share exactly one point by construction, never a
    genuine crossing."""
    n = len(points)
    hits: list[Point] = []
    for i in range(n):
        a1, a2 = points[i], points[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            b1, b2 = points[j], points[(j + 1) % n]
            hit = _segments_properly_intersect(a1, a2, b1, b2)
            if hit is not None:
                hits.append(hit)
    return hits


def find_ring_intersections(ring_a: tuple[Point, ...], ring_b: tuple[Point, ...]) -> list[Point]:
    """Every point where an edge of ``ring_a`` crosses an edge of
    ``ring_b`` transversally (§9's "unintended overlap", issue #41) -- two
    rings that do not cross at all are either disjoint or one fully
    contains the other (a legitimate hole, say); this is deliberately blind
    to which of those two it is, since telling them apart is exactly the
    "well-nested" assumption this module's own docstring says overlap
    detection must not rely on."""
    hits: list[Point] = []
    na, nb = len(ring_a), len(ring_b)
    for i in range(na):
        a1, a2 = ring_a[i], ring_a[(i + 1) % na]
        for j in range(nb):
            b1, b2 = ring_b[j], ring_b[(j + 1) % nb]
            hit = _segments_properly_intersect(a1, a2, b1, b2)
            if hit is not None:
                hits.append(hit)
    return hits
