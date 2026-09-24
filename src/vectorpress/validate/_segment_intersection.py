"""Find where line segments of flattened rings cross transversally -- the
arithmetic behind the self-intersection and unintended-overlap findings.

"Do two rings' boundaries cross at all" is a segment-intersection test, not
an area/union/difference computation, so it needs no polygon boolean
library -- the same plain, deterministic arithmetic as the rest of
:mod:`vectorpress.validate`.
"""

from vectorpress.validate._svg_document import Point

#: The fixed epsilon a signed area (twice a triangle's own area, in squared
#: user units) must clear before :func:`_segments_properly_intersect`
#: treats it as a genuine, non-collinear side -- absorbs the same kind of
#: last-bit floating-point noise :data:`~vectorpress.domain.numeric_format.
#: DECIMAL_PLACES` exists to absorb elsewhere, without being anywhere close
#: to a real crossing's own signed area for any shape this tool's fixtures
#: or a plausible hand-edited override would produce.
_INTERSECTION_EPS = 1e-6


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
    other -- or ``None`` when they do not: two segments that only touch at a shared
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
    in this package) cross transversally (§9's "a self-intersecting
    subpath") -- a bowtie is the simplest case: two edges on
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
    ``ring_b`` transversally (§9's "unintended overlap") -- two
    rings that do not cross at all are either disjoint or one fully
    contains the other (a legitimate hole, say); this is deliberately blind
    to which of those two it is, since telling them apart is exactly the
    "well-nested" assumption :mod:`vectorpress.validate._pieces` makes and
    overlap detection must not rely on."""
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
