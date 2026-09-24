"""Group a document's subpaths into cut pieces and holes by containment
parity, and measure the document's physical scale (§9.1).

**A scoped simplification, not a full nonzero-winding implementation.**
Whether a subpath is a hole of its immediate parent is decided by
containment-depth parity alone (odd depth = hole), which is exactly the
even-odd fill rule's own definition. :mod:`vectorpress.pipeline.cut_svg`
always writes ``fill-rule="evenodd"``, and every fixture this grouping is
tested against uses simple, non-self-intersecting, well-nested subpaths (the
only shape a hand-authored override is likely to produce for a cut file
too), so depth parity gives the same grouping a full nonzero-winding
computation would. A path that actually relies on winding direction under
``fill-rule="nonzero"`` (two same-direction overlapping contours) is outside
this grouping's scope -- no finding kind built on it would misclassify such
a path as anything worse than an extra or missing fragment. Detectors that
must not assume well-nested geometry work from :mod:`vectorpress.validate.
_subpaths` instead.
"""

from dataclasses import dataclass

from vectorpress.domain.finding import BoundingBox
from vectorpress.validate._svg_document import (
    Point,
    SvgDocument,
    polygon_bbox,
    svg_viewbox_longest_side,
)


def polygon_area(points: tuple[Point, ...]) -> float:
    """A polygon's unsigned area via the shoelace formula."""
    total = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _polygon_representative_point(points: tuple[Point, ...]) -> Point:
    """A point inside ``points`` used to test containment against sibling
    subpaths: the area-weighted centroid, which lands inside any star-shaped
    polygon (potrace output and simple hand-authored shapes alike). A
    degenerate polygon (zero signed area -- a line-like sliver) falls back
    to the plain average of its vertices."""
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


def point_in_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
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
    than a hole), identified by where it sits in the document (its path
    reference), its own bounding box, and its net area (its own shell, minus
    any holes directly inside it) -- used to rank "the largest" piece among
    several.

    ``node_count``, ``outer_ring`` and ``hole_rings`` are this piece's own
    authored geometry, needed by :mod:`vectorpress.validate.
    excessive_complexity` (node density against physical perimeter) and
    :mod:`vectorpress.validate.narrow_feature` (rasterizing this piece --
    its own shell minus its own immediate holes, the same even-odd shape
    the SVG itself renders -- to measure a local width). ``outer_ring`` is
    this piece's own flattened boundary; ``hole_rings`` are its immediate
    holes' flattened boundaries only (a hole nested inside one of *those*
    holes would itself be a further piece, not one of this piece's own
    ``hole_rings`` -- out of scope for both consumers, the same "well-nested,
    simple" scope this module's docstring draws)."""

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
        SVG user units as :attr:`bbox`: the basis for telling an elongated
        sliver (a small area but a large extent in one direction) from a
        genuine dot (small in every direction)."""
        return max(self.bbox.max_x - self.bbox.min_x, self.bbox.max_y - self.bbox.min_y)


@dataclass(frozen=True)
class Hole:
    """One interior ring (odd containment depth under even-odd fill),
    subtracted from its immediate parent :class:`Piece`'s own area -- a
    candidate very small hole, identified the same way a :class:`Piece` is:
    where it sits in the document, its own bounding box, and its own
    (un-subtracted) area."""

    element_index: int
    subpath_index: int
    element_id: str | None
    bbox: BoundingBox
    area: float


def non_largest_pieces(pieces: list[Piece]) -> list[Piece]:
    """Every piece except the largest by area: the shared "isolated shape"
    candidate pool every area-based §9 detector (:mod:`vectorpress.validate.
    accidental_dot`, :mod:`vectorpress.validate.tiny_isolated_shape`) and
    :mod:`vectorpress.validate.disconnected_fragments` all scope themselves
    to -- a document with zero or one piece has nothing isolated from
    anything else, so it yields nothing. Ties on area keep whichever
    :func:`max` happens to pick as "the largest" (arbitrary but consistent
    within one call)."""
    if len(pieces) <= 1:
        return []
    largest = max(pieces, key=lambda piece: piece.area)
    return [piece for piece in pieces if piece is not largest]


@dataclass(frozen=True)
class ParsedCutFile:
    """Everything :mod:`vectorpress.validate.cut_file`'s piece and hole
    detectors need from one SVG: its candidate pieces, its candidate holes,
    and the physical scale (§9.1) a threshold-based detector converts a
    physical-unit threshold with -- ``reference_size_in`` physical inches
    map onto :attr:`scale_user_units_per_inch` user units."""

    pieces: list[Piece]
    holes: list[Hole]
    scale_user_units_per_inch: float


def parse_cut_file(document: SvgDocument, reference_size_in: float) -> ParsedCutFile:
    """Group ``document``'s subpaths into its candidate pieces and holes,
    and compute its physical scale.

    Every ``<path>`` element in document order contributes its own
    subpaths; a subpath's containment depth among *every* subpath in the
    document (not just its own element's) decides whether it is a hole (odd
    depth, subtracted from its immediate parent's area) or a piece's own
    shell (even depth) -- so restructuring one shape across several
    ``<path>`` elements, as a hand-edited override might, does not change
    how many physical pieces are found.

    Raises :class:`ValueError` (from :func:`~vectorpress.validate.
    _svg_document.svg_viewbox_longest_side`, or from ``svgelements`` on
    unparseable path data) for an SVG this cannot establish a scale for or
    make sense of at all -- :mod:`vectorpress.validate.cut_file` lets this
    propagate as a validation failure (§35), never a passing result.
    """
    longest_side = svg_viewbox_longest_side(document)
    scale = longest_side / reference_size_in

    subpaths: list[tuple[int, int, str | None, tuple[Point, ...], int]] = []
    for path in document.paths:
        for subpath_index, subpath in enumerate(path.subpaths):
            if len(subpath.points) < 3:
                continue  # not a real polygon: an empty or degenerate subpath
            subpaths.append(
                (
                    path.element_index,
                    subpath_index,
                    path.element_id,
                    subpath.points,
                    subpath.node_count,
                )
            )

    polygons = [record[3] for record in subpaths]
    areas = [polygon_area(polygon) for polygon in polygons]
    representative_points = [_polygon_representative_point(polygon) for polygon in polygons]
    # A candidate container ``j`` must have a strictly larger area than ``i``:
    # under this module's "well-nested" simplification, two subpaths whose
    # interiors share a point are either disjoint or one strictly contains
    # the other, and a container is always the bigger of the two. Without
    # this guard, a shape whose own representative point (its centroid)
    # happens to land inside a much smaller sibling -- a hole placed
    # dead-center inside its own parent shell, for example, the natural way
    # to draw one -- would wrongly count as "contained in" that sibling too,
    # on nothing more than coincidental point placement, corrupting which
    # subpaths are real pieces at all.
    depths = [
        sum(
            1
            for j, polygon in enumerate(polygons)
            if j != i
            and areas[j] > areas[i]
            and point_in_polygon(representative_points[i], polygon)
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
            and point_in_polygon(representative_points[i], polygons[j])
        ]
        parents.append(min(candidates, key=lambda j: areas[j]) if candidates else None)

    pieces: list[Piece] = []
    holes: list[Hole] = []
    for i, (element_index, subpath_index, element_id, points, node_count) in enumerate(subpaths):
        if depths[i] % 2 != 0:
            # A hole, not a piece of its own -- subtracted from its parent's
            # area below, and recorded in its own right as a candidate very
            # small hole.
            holes.append(
                Hole(
                    element_index=element_index,
                    subpath_index=subpath_index,
                    element_id=element_id,
                    bbox=polygon_bbox(points),
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
                bbox=polygon_bbox(points),
                area=areas[i] - hole_area,
                node_count=node_count,
                outer_ring=points,
                hole_rings=tuple(polygons[j] for j in own_hole_indices),
            )
        )

    return ParsedCutFile(pieces=pieces, holes=holes, scale_user_units_per_inch=scale)
