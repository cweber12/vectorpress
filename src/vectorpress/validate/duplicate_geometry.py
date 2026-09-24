"""The ``duplicate_geometry`` detector (§9, ADR 0007).

Two subpaths with the exact same geometry -- the same shape stacked
exactly on top of itself, or repeated verbatim elsewhere in the document --
serve no purpose a cut file needs and can only make a hand edit (or a
copy-paste mistake) harder to reason about; the §8 builder's own tracer
never emits the same ring twice.

Runs over every :mod:`vectorpress.validate._subpaths.Subpath` in the
document (not grouped into piece/hole), comparing every pair: two subpaths
are "the same geometry" when their own flattened point sets match, each
rounded to :data:`~vectorpress.domain.numeric_format.DECIMAL_PLACES` (the
one fixed rounding tolerance every number this tool writes already uses),
regardless of which vertex either one happens to start at or which
direction it winds -- a *sorted* point set, not an ordered sequence
comparison, so a duplicate drawn starting from a different corner, or
wound the other way, is still caught.

Reported **once per duplicate pair** (:attr:`~vectorpress.domain.finding.
Finding.related_path_reference` names the second subpath), not once per
member -- three or more identical copies report one finding per pair among
them, the same "report and leave, never bridge or merge silently" spirit
ADR 0007 already applies to disconnected fragments.
"""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    Finding,
    FindingKind,
    PathReference,
)
from vectorpress.domain.numeric_format import round_number
from vectorpress.validate._subpaths import Subpath

_KIND = FindingKind.DUPLICATE_GEOMETRY
_CLASSIFICATION = CLASSIFICATION[_KIND]


#: How close a subpath's own last flattened point must be to its first
#: before :func:`_signature` treats them as "the same point" and drops the
#: redundant one -- :func:`vectorpress.validate._svg_document.
#: flatten_subpath` appends an explicit ``Close`` segment's own end point
#: (identical to the subpath's start) as a genuine extra point, so without
#: this, *which* vertex is the duplicated one -- and so the point
#: *multiset* :func:`_signature` builds -- would depend on which vertex
#: happens to be the authored starting point, breaking the "independent of
#: starting vertex" guarantee this detector's own docstring promises.
_CLOSE_POINT_TOLERANCE = 1e-9


def _signature(subpath: Subpath) -> tuple[tuple[float, float], ...]:
    """``subpath``'s own rounded point set, sorted -- shape- and
    position-identity independent of starting vertex or winding
    direction."""
    points = subpath.points
    if len(points) > 1:
        (start_x, start_y), (end_x, end_y) = points[0], points[-1]
        if (
            abs(start_x - end_x) < _CLOSE_POINT_TOLERANCE
            and abs(start_y - end_y) < _CLOSE_POINT_TOLERANCE
        ):
            points = points[:-1]
    return tuple(sorted((round_number(x), round_number(y)) for x, y in points))


def detect(subpaths: list[Subpath]) -> list[Finding]:
    """One finding per pair of subpaths whose own geometry matches within
    rounding tolerance (§9), located at the shared bounding box (identical
    geometry means an identical bbox too).

    A subpath under three points -- a bare open line segment, say -- is
    never a candidate here: "the same geometry" means nothing for a shape
    with no real interior, and :func:`~vectorpress.validate._subpaths.
    parse_subpaths` itself keeps one only for :mod:`vectorpress.validate.open_path`'s own sake.

    ``subpaths`` is already in document order (:func:`~vectorpress.
    validate._subpaths.parse_subpaths`), so iterating pairs with the
    first index always less than the second already yields findings in a
    fixed, deterministic order -- by the first (lower document order)
    subpath's own path reference, then the second's -- with no further
    sort needed.
    """
    subpaths = [subpath for subpath in subpaths if len(subpath.points) >= 3]
    signatures = [_signature(subpath) for subpath in subpaths]

    findings: list[Finding] = []
    for i in range(len(subpaths)):
        for j in range(i + 1, len(subpaths)):
            if signatures[i] != signatures[j]:
                continue
            first, second = subpaths[i], subpaths[j]
            findings.append(
                Finding(
                    kind=_KIND,
                    classification=_CLASSIFICATION,
                    message=(
                        f"duplicate geometry: path element {first.element_index}, "
                        f"subpath {first.subpath_index} has the same geometry as "
                        f"path element {second.element_index}, subpath {second.subpath_index}"
                    ),
                    location=first.bbox,
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

    return findings
