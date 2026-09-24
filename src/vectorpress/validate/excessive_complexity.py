"""The ``excessive_complexity`` detector (§9, §9.1, ADR 0007, issue #40, PR
#46 review fix rounds 1 and 2).

A path whose node count is out of proportion to its own physical size is
hard to cut cleanly and hard for a human to review or hand-edit -- issue
#40's documented measure is **nodes per inch of perimeter** at the reference
size (§9.1): a piece's own authored node count (:attr:`~vectorpress.
validate._svg_geometry.Piece.node_count` -- every ``Move``/``Line``/curve/
``Arc`` segment, never the fixed-step curve *sampling*
:mod:`vectorpress.validate._svg_geometry` also flattens every subpath to)
divided by its own flattened perimeter's physical length.

**Density alone grows without bound as a piece shrinks** (review fix round
1): a plain 4-6 node dot or sliver a few hundredths of an inch across
already reads as "tens of nodes per inch" purely from having a tiny
perimeter, nothing to do with genuine complexity -- exactly the shape
:mod:`vectorpress.validate.accidental_dot` and :mod:`vectorpress.validate.
tiny_isolated_shape` already exist to name. Density is therefore judged only
on a piece whose own perimeter is at or above ``min_perimeter_in`` -- a
piece smaller than that is never judged *by density*, left entirely to the
dot/tiny-shape kinds for that measure.

The **absolute node cap** (``max_node_count``) is a backstop against a
pathologically node-heavy path whose density alone would not flag it (a
huge, evenly detailed design, say) -- set well above what realistic traced
artwork ever needs (hundreds of nodes, not tens), so in practice the density
measure above is what actually catches an excessively complex piece; the
cap is deliberately the rarer path to a finding, not the common one. Unlike
density, the cap is checked **regardless of a piece's own size** (review fix
round 2): a piece below ``min_perimeter_in`` is exempt from density, never
from the cap -- an authored node count in the hundreds is exactly as
unmanageable to cut and hand-edit on a tiny piece as on a large one, so
nothing about being small should exempt a piece from this particular
backstop (in practice, the pieces small enough to be excluded from density
essentially never carry that many nodes, so this rarely fires on them; it
is a deliberate, checked property of the detector, not an untested
possibility).

A piece trips this kind when either measure is out of bounds; the
``measured_value``/``threshold`` recorded are whichever one it tripped
(density first, since it is the primary, size-aware measure -- the cap is a
backstop, checked only once density does not already explain the finding).

Runs over *every* piece the document has, largest included -- like
:mod:`vectorpress.validate.narrow_feature`, this is not one of the three
piece-*classification* kinds :class:`~vectorpress.domain.finding.FindingKind`
documents as mutually exclusive; a design's own main body, a finely ragged
outline for example, is exactly the piece this issue's own fixture means to
trip it on.
"""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    Finding,
    FindingKind,
    PathReference,
)
from vectorpress.domain.numeric_format import format_number, round_number
from vectorpress.validate._svg_geometry import Piece

_KIND = FindingKind.EXCESSIVE_COMPLEXITY
_CLASSIFICATION = CLASSIFICATION[_KIND]


def _perimeter(ring: tuple[tuple[float, float], ...]) -> float:
    """``ring``'s own perimeter (its points already close the loop
    implicitly, the same convention every other polygon helper in this
    package uses -- :func:`vectorpress.validate._svg_geometry._polygon_area`,
    :func:`~vectorpress.validate._svg_geometry._point_in_polygon`)."""
    return sum(
        ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True)
    )


def detect(
    pieces: list[Piece],
    scale_user_units_per_inch: float,
    max_nodes_per_inch: float,
    min_perimeter_in: float,
    max_node_count: float,
) -> list[Finding]:
    """One finding per piece whose node density (nodes per physical inch of
    its own perimeter, §9.1) exceeds ``max_nodes_per_inch`` -- judged only
    when the piece's own perimeter is at or above ``min_perimeter_in``, so a
    piece too small for "per inch" to mean anything is never judged by
    density at all (review fix round 1) -- or whose raw node count exceeds
    ``max_node_count`` regardless of size, a backstop checked whenever
    density does not already explain the finding.

    Findings are returned in a fixed, deterministic order -- by path
    reference (element index, then subpath index) -- matching every other
    detector in this package (issue #37's own ordering rule).
    """
    findings: list[Finding] = []
    for piece in pieces:
        perimeter_in = _perimeter(piece.outer_ring) / scale_user_units_per_inch
        nodes_per_inch = piece.node_count / perimeter_in if perimeter_in > 0 else 0.0
        density_judged = perimeter_in >= min_perimeter_in

        if density_judged and nodes_per_inch > max_nodes_per_inch:
            measured_value = round_number(nodes_per_inch)
            threshold = round_number(max_nodes_per_inch)
            reason = f"{measured_value} nodes/in, above the {threshold} nodes/in threshold"
        elif piece.node_count > max_node_count:
            measured_value = round_number(float(piece.node_count))
            threshold = round_number(max_node_count)
            reason = f"{piece.node_count} nodes, above the {format_number(max_node_count)}-node cap"
        else:
            continue

        findings.append(
            Finding(
                kind=_KIND,
                classification=_CLASSIFICATION,
                message=(
                    f"excessive geometric complexity: path element {piece.element_index}, "
                    f"subpath {piece.subpath_index} has {reason}"
                ),
                location=piece.bbox,
                path_reference=PathReference(
                    element_index=piece.element_index,
                    subpath_index=piece.subpath_index,
                    id=piece.element_id,
                ),
                measured_value=measured_value,
                threshold=threshold,
            )
        )

    findings.sort(
        key=lambda finding: (
            finding.path_reference.element_index,
            finding.path_reference.subpath_index,
        )
    )
    return findings
