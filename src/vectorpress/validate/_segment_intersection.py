"""Find where line segments of flattened rings cross transversally -- the
arithmetic behind the self-intersection and unintended-overlap findings.

"Do two rings' boundaries cross at all" is a segment-intersection test, not
an area/union/difference computation, so it needs no polygon boolean
library -- the same plain, deterministic arithmetic as the rest of
:mod:`vectorpress.validate`.

Which segment pairs get that exact test is the expensive part: a traced
line-art outline flattens to rings of thousands of segments, and testing
every pair -- the approach before issue #86 -- took up to a minute per cut
file. :func:`find_intersections` sweeps every ring's segments at once,
sorted by their left edge, and hands the exact test only the pairs whose
bounding boxes overlap (numpy narrows the candidates; the test itself stays
plain-float Python, so every reported point is computed exactly as before).
"""

from collections.abc import Sequence

import numpy as np

from vectorpress.validate._svg_document import Point

#: The fixed epsilon a signed area (twice a triangle's own area, in squared
#: user units) must clear before :func:`segments_properly_intersect`
#: treats it as a genuine, non-collinear side -- absorbs the same kind of
#: last-bit floating-point noise :data:`~vectorpress.domain.numeric_format.
#: DECIMAL_PLACES` exists to absorb elsewhere, without being anywhere close
#: to a real crossing's own signed area for any shape this tool's fixtures
#: or a plausible hand-edited override would produce.
_INTERSECTION_EPS = 1e-6


def _strict_sign(value: float) -> int:
    """-1/0/1, with anything inside :data:`_INTERSECTION_EPS` of zero
    treated as exactly zero (collinear) -- :func:`segments_properly_intersect`'s
    own tolerance for floating-point noise."""
    if value > _INTERSECTION_EPS:
        return 1
    if value < -_INTERSECTION_EPS:
        return -1
    return 0


def _orientation(a: Point, b: Point, c: Point) -> float:
    """Twice the signed area of triangle ``abc`` -- positive when ``c`` is
    left of ray ``a->b``, negative when right, (near) zero when collinear.
    The one primitive :func:`segments_properly_intersect` builds on."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_properly_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> Point | None:
    """The point where segments ``p1p2`` and ``p3p4`` cross *transversally*
    -- each segment's own two endpoints strictly on opposite sides of the
    other -- or ``None`` when they do not: two segments that only touch at a shared
    endpoint, or run collinear along a shared edge (two identical, stacked
    subpaths' own coincident edges, say), are deliberately **not** a
    crossing -- that is :mod:`vectorpress.validate.duplicate_geometry`'s
    concern, not :mod:`vectorpress.validate.overlap`'s.

    A cheap bounding-box rejection runs first, so the result never depends
    on whether a caller pre-filtered by bounding box
    (:func:`find_intersections` does)."""
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


def find_intersections(rings: Sequence[tuple[Point, ...]]) -> dict[tuple[int, int], list[Point]]:
    """Every transversal crossing among ``rings`` (each already implicitly
    closed, like every other polygon helper in this package), keyed by the
    pair of ring indices involved, lower index first: ``(i, i)`` collects
    ring ``i``'s own self-intersections (§9's "a self-intersecting
    subpath" -- a bowtie is the simplest case), ``(i, j)`` with ``i < j``
    the points where ring ``i``'s boundary crosses ring ``j``'s (§9's
    "unintended overlap"). A pair with no crossing has no key at all.

    Two edges of the same ring that are adjacent (sharing a vertex,
    including the wrap-around pair) are never tested against each other --
    they always share exactly one point by construction, never a genuine
    crossing. Two rings that do not cross are either disjoint or one fully
    contains the other (a legitimate hole, say); this is deliberately blind
    to which of those two it is, since telling them apart is exactly the
    "well-nested" assumption :mod:`vectorpress.validate._pieces` makes and
    overlap detection must not rely on.

    Reports exactly the crossings an all-pairs scan would (issue #86, locked
    by ``tests/unit/test_validate_segment_intersection.py``): a pair whose
    bounding boxes do not even touch is one :func:`segments_properly_intersect`
    would reject anyway, and each candidate pair is passed to it in the same
    argument order the all-pairs scan used (the lower ring, then the lower
    segment index, first), so each point is the same float the scan
    computed.
    """
    ring_of: list[int] = []
    index_in_ring: list[int] = []
    ring_length: list[int] = []
    starts: list[Point] = []
    ends: list[Point] = []
    for ring_index, ring in enumerate(rings):
        n = len(ring)
        for k in range(n):
            ring_of.append(ring_index)
            index_in_ring.append(k)
            ring_length.append(n)
            starts.append(ring[k])
            ends.append(ring[(k + 1) % n])
    hits: dict[tuple[int, int], list[Point]] = {}
    if not starts:
        return hits

    start_xy = np.array(starts, dtype=np.float64)
    end_xy = np.array(ends, dtype=np.float64)
    min_x = np.minimum(start_xy[:, 0], end_xy[:, 0])
    max_x = np.maximum(start_xy[:, 0], end_xy[:, 0])
    min_y = np.minimum(start_xy[:, 1], end_xy[:, 1])
    max_y = np.maximum(start_xy[:, 1], end_xy[:, 1])
    # Sweep left to right: a segment's x-overlapping partners later in this
    # order are exactly those whose left edge is at or before its right edge.
    order = np.argsort(min_x, kind="stable")
    reach = np.searchsorted(min_x[order], max_x[order], side="right")

    for position in range(order.size):
        first = int(order[position])
        candidates = order[position + 1 : int(reach[position])]
        if candidates.size == 0:
            continue
        candidates = candidates[
            (min_y[candidates] <= max_y[first]) & (max_y[candidates] >= min_y[first])
        ]
        for other in candidates.tolist():
            low, high = sorted((first, other), key=lambda s: (ring_of[s], index_in_ring[s]))
            ring_low, ring_high = ring_of[low], ring_of[high]
            if ring_low == ring_high:
                gap = index_in_ring[high] - index_in_ring[low]
                if gap == 1 or gap == ring_length[low] - 1:
                    continue  # adjacent edges share a vertex, never a crossing
            hit = segments_properly_intersect(starts[low], ends[low], starts[high], ends[high])
            if hit is not None:
                hits.setdefault((ring_low, ring_high), []).append(hit)
    return dict(sorted(hits.items()))
