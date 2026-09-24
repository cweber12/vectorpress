"""The ``overlap`` detector (§9, ADR 0007, issue #41).

Two closed, filled subpaths whose own boundaries genuinely cross -- neither
one simply nested inside the other as a hole -- or a single subpath whose
own boundary crosses itself, can only come from a hand edit: the §8
builder's own tracer never emits self-intersecting or mutually crossing
geometry.

Deliberately independent of :mod:`vectorpress.validate._svg_geometry`'s own
piece/hole containment-parity grouping (that module's own docstring: "your
overlap and self-intersection detection must not rely on it"): a genuinely
overlapping pair can be *misclassified* by that parity model as a hole of
the other (its smaller area, and its own representative point happening to
land inside the bigger one, even though part of its own boundary sticks
out) -- so this runs directly over every raw :class:`~vectorpress.validate.
_svg_geometry.Subpath`'s own ring, testing every pair (and every subpath
against itself) for a genuine crossing via :func:`~vectorpress.validate.
_svg_geometry.find_ring_intersections`/:func:`~vectorpress.validate.
_svg_geometry.find_self_intersections`, never consulting :class:`~
vectorpress.validate._svg_geometry.Piece`/:class:`~vectorpress.validate.
_svg_geometry.Hole` at all.

Two subpaths that coincide exactly (:mod:`vectorpress.validate.
duplicate_geometry`'s own concern) never trip this: their edges run
collinear on top of each other rather than crossing transversally, and
:func:`~vectorpress.validate._svg_geometry.find_ring_intersections`
deliberately does not count that as a crossing.
"""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    BoundingBox,
    Finding,
    FindingKind,
    PathReference,
)
from vectorpress.domain.numeric_format import round_number
from vectorpress.validate._svg_geometry import (
    Point,
    Subpath,
    find_ring_intersections,
    find_self_intersections,
)

_KIND = FindingKind.OVERLAP
_CLASSIFICATION = CLASSIFICATION[_KIND]


def _hits_bbox(hits: list[Point]) -> BoundingBox:
    """The tight bounding box around every crossing point found for one
    subpath (self-intersection) or one pair of subpaths (overlap) -- the
    crossing's own location, never the much larger shape(s) it belongs to
    (§9's "located by the intersection's bbox")."""
    xs = [x for x, _y in hits]
    ys = [y for _x, y in hits]
    return BoundingBox(
        min_x=round_number(min(xs)),
        min_y=round_number(min(ys)),
        max_x=round_number(max(xs)),
        max_y=round_number(max(ys)),
    )


def detect(subpaths: list[Subpath]) -> list[Finding]:
    """One finding per self-intersecting subpath, and one finding per pair
    of subpaths whose boundaries cross without one nesting inside the
    other (§9), located at the crossing point(s)' own bounding box.

    A subpath under three points -- a bare open line segment, say -- is
    never a candidate here (issue #41 review fix round 1): a two-point
    "ring" has exactly one edge, which can never cross itself, and
    :func:`~vectorpress.validate._svg_geometry.parse_subpaths` itself keeps
    one only for :mod:`vectorpress.validate.open_path`'s own sake.

    Findings are returned in a fixed, deterministic order -- self-
    intersections first (by path reference), then pairwise overlaps (by
    the first, then the second, subpath's own path reference; ``subpaths``
    is already in document order, :func:`~vectorpress.validate.
    _svg_geometry.parse_subpaths`, so iterating pairs with the first index
    always less than the second already yields them in that order, the
    same reasoning :mod:`vectorpress.validate.duplicate_geometry` uses) --
    matching every other detector in this package (issue #37's own
    ordering rule).
    """
    subpaths = [subpath for subpath in subpaths if len(subpath.points) >= 3]

    self_findings: list[Finding] = []
    for subpath in subpaths:
        hits = find_self_intersections(subpath.points)
        if not hits:
            continue
        self_findings.append(
            Finding(
                kind=_KIND,
                classification=_CLASSIFICATION,
                message=(
                    f"unintended overlap: path element {subpath.element_index}, "
                    f"subpath {subpath.subpath_index} is self-intersecting"
                ),
                location=_hits_bbox(hits),
                path_reference=PathReference(
                    element_index=subpath.element_index,
                    subpath_index=subpath.subpath_index,
                    id=subpath.element_id,
                ),
            )
        )
    self_findings.sort(
        key=lambda finding: (
            finding.path_reference.element_index,
            finding.path_reference.subpath_index,
        )
    )

    pair_findings: list[Finding] = []
    for i in range(len(subpaths)):
        for j in range(i + 1, len(subpaths)):
            first, second = subpaths[i], subpaths[j]
            hits = find_ring_intersections(first.points, second.points)
            if not hits:
                continue
            pair_findings.append(
                Finding(
                    kind=_KIND,
                    classification=_CLASSIFICATION,
                    message=(
                        f"unintended overlap: path element {first.element_index}, "
                        f"subpath {first.subpath_index} overlaps path element "
                        f"{second.element_index}, subpath {second.subpath_index}"
                    ),
                    location=_hits_bbox(hits),
                    path_reference=PathReference(
                        element_index=first.element_index,
                        subpath_index=first.subpath_index,
                        id=first.element_id,
                    ),
                    related_path_reference=PathReference(
                        element_index=second.element_index,
                        subpath_index=second.subpath_index,
                        id=second.element_id,
                    ),
                )
            )

    return [*self_findings, *pair_findings]
