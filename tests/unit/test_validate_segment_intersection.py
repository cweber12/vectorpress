"""validate._segment_intersection: every transversal crossing among a set
of flattened rings, found without testing every segment pair (issue #86).

The brute-force all-pairs scan below is the algorithm this module used
before issue #86, kept here as the oracle: :func:`find_intersections` must
report exactly the crossings it reports -- same ring pairs, same points --
while calling the exact segment test only on segments whose bounding boxes
overlap.
"""

import math
import random

import pytest

from vectorpress.validate import _segment_intersection
from vectorpress.validate._segment_intersection import (
    find_intersections,
    segments_properly_intersect,
)
from vectorpress.validate._svg_document import Point

Ring = tuple[Point, ...]


def _brute_force(rings: list[Ring]) -> dict[tuple[int, int], list[Point]]:
    """Every non-adjacent edge pair within a ring, and every edge pair
    across two rings, tested directly (the pre-issue-#86 algorithm)."""
    hits: dict[tuple[int, int], list[Point]] = {}
    for r, ring in enumerate(rings):
        n = len(ring)
        for i in range(n):
            for j in range(i + 1, n):
                if j == i + 1 or (i == 0 and j == n - 1):
                    continue
                hit = segments_properly_intersect(
                    ring[i], ring[(i + 1) % n], ring[j], ring[(j + 1) % n]
                )
                if hit is not None:
                    hits.setdefault((r, r), []).append(hit)
    for a in range(len(rings)):
        for b in range(a + 1, len(rings)):
            ring_a, ring_b = rings[a], rings[b]
            na, nb = len(ring_a), len(ring_b)
            for i in range(na):
                for j in range(nb):
                    hit = segments_properly_intersect(
                        ring_a[i], ring_a[(i + 1) % na], ring_b[j], ring_b[(j + 1) % nb]
                    )
                    if hit is not None:
                        hits.setdefault((a, b), []).append(hit)
    return hits


def _sorted(hits: dict[tuple[int, int], list[Point]]) -> dict[tuple[int, int], list[Point]]:
    return {key: sorted(points) for key, points in hits.items()}


def _circle(cx: float, cy: float, radius: float, n: int, wobble: float = 0.0) -> Ring:
    """``n`` vertices around a circle, the radius rippling by ``wobble``
    so edges run at many different angles, like a traced outline's."""
    points: list[Point] = []
    for k in range(n):
        angle = k * 2 * math.pi / n
        r = radius + wobble * math.sin(7 * angle)
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return tuple(points)


def test_a_bowtie_reports_its_one_self_crossing() -> None:
    rings: list[Ring] = [((0.0, 0.0), (100.0, 100.0), (100.0, 0.0), (0.0, 100.0))]

    assert find_intersections(rings) == {(0, 0): [(50.0, 50.0)]}


def test_nested_disjoint_and_touching_rings_report_nothing() -> None:
    outer = ((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0))
    hole = ((20.0, 20.0), (40.0, 20.0), (40.0, 40.0), (20.0, 40.0))
    elsewhere = ((200.0, 0.0), (300.0, 0.0), (300.0, 100.0))
    sharing_an_edge = ((100.0, 0.0), (150.0, 0.0), (150.0, 100.0), (100.0, 100.0))

    assert find_intersections([outer, hole, elsewhere, sharing_an_edge]) == {}


@pytest.mark.parametrize("seed", range(12))
def test_matches_the_all_pairs_scan_on_random_rings(seed: int) -> None:
    """Random polygons self-intersect often and cross each other often;
    integer-snapped vertices also produce collinear and touching edges,
    which must stay non-crossings exactly as before."""
    rng = random.Random(seed)
    rings: list[Ring] = [
        tuple(
            (float(rng.randint(0, 40)), float(rng.randint(0, 40)))
            for _ in range(rng.randint(3, 25))
        )
        for _ in range(rng.randint(1, 6))
    ]

    assert _sorted(find_intersections(rings)) == _sorted(_brute_force(rings))


def test_matches_the_all_pairs_scan_on_long_crossing_outlines() -> None:
    """Line-art shaped input: two long, wobbly outlines that cross each
    other, plus a hole nested inside the first."""
    rings = [
        _circle(0.0, 0.0, 100.0, 600, wobble=3.0),
        _circle(150.0, 0.0, 80.0, 500, wobble=2.0),
        _circle(-40.0, 0.0, 20.0, 200),
    ]

    result = find_intersections(rings)

    assert set(result) == {(0, 1)}
    assert _sorted(result) == _sorted(_brute_force(rings))


def test_a_long_simple_outline_is_not_scanned_pair_by_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression issue #86 fixes: a 4,000-segment outline cost ~8M
    exact segment tests (every pair), which dominated ``vpress validate``
    on line art. Only bbox-overlapping segments may reach the exact test."""
    calls = 0
    exact = _segment_intersection.segments_properly_intersect

    def counting(p1: Point, p2: Point, p3: Point, p4: Point) -> Point | None:
        nonlocal calls
        calls += 1
        return exact(p1, p2, p3, p4)

    monkeypatch.setattr(_segment_intersection, "segments_properly_intersect", counting)
    ring = _circle(0.0, 0.0, 1000.0, 4000, wobble=5.0)

    assert find_intersections([ring]) == {}
    assert calls < 10 * len(ring)
