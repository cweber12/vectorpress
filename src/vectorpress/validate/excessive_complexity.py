"""The ``excessive_complexity`` detector (§9, §9.1, ADR 0007, issue #40).

A path whose node count is out of proportion to its own physical size is
hard to cut cleanly and hard for a human to review or hand-edit -- issue
#40's documented measure is **nodes per inch of perimeter** at the reference
size (§9.1): a piece's own authored node count (:attr:`~vectorpress.
validate._svg_geometry.Piece.node_count` -- every ``Move``/``Line``/curve/
``Arc`` segment, never the fixed-step curve *sampling*
:mod:`vectorpress.validate._svg_geometry` also flattens every subpath to)
divided by its own flattened perimeter's physical length. A **density**
alone would let a merely large piece accumulate an unmanageable raw node
count while still reading as "proportionate" -- so an absolute cap on the
raw node count backstops it regardless of physical size.

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
from vectorpress.domain.numeric_format import round_number
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
    max_node_count: float,
) -> list[Finding]:
    """One finding per piece whose node density (nodes per physical inch of
    its own perimeter, §9.1) exceeds ``max_nodes_per_inch``, or whose raw
    node count exceeds ``max_node_count`` -- whichever it trips (density
    first).

    Findings are returned in a fixed, deterministic order -- by path
    reference (element index, then subpath index) -- matching every other
    detector in this package (issue #37's own ordering rule).
    """
    findings: list[Finding] = []
    for piece in pieces:
        perimeter_in = _perimeter(piece.outer_ring) / scale_user_units_per_inch
        nodes_per_inch = piece.node_count / perimeter_in if perimeter_in > 0 else 0.0

        if nodes_per_inch > max_nodes_per_inch:
            measured_value = round_number(nodes_per_inch)
            threshold = round_number(max_nodes_per_inch)
            reason = f"{measured_value} nodes/in, above the {threshold} nodes/in threshold"
        elif piece.node_count > max_node_count:
            measured_value = round_number(float(piece.node_count))
            threshold = round_number(max_node_count)
            reason = f"{piece.node_count} nodes, above the {threshold}-node cap"
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
