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
already express directly. A later issue that needs true general polygon
boolean operations (§9's overlap/duplicate-geometry kinds, say) can revisit
this.

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
