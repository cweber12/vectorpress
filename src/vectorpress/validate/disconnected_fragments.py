"""The ``disconnected_fragments`` detector (§9, ADR 0007, issue #37).

A cut file's design is more than one separate physical piece: potrace's own
island-removal cleanup (:mod:`vectorpress.pipeline.cut_svg`) already drops
noise below the recipe's own thresholds, so anything that survives to reach
this detector is a genuine, deliberately-kept piece -- there is no size
threshold here (ADR 0007's "no automatic bridging or joining": every extra
piece is reported and left, never silently dropped or judged too small to
matter).
"""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    Finding,
    FindingKind,
    PathReference,
)
from vectorpress.validate._svg_geometry import Piece

_KIND = FindingKind.DISCONNECTED_FRAGMENTS
_CLASSIFICATION = CLASSIFICATION[_KIND]


def detect(pieces: list[Piece]) -> list[Finding]:
    """One finding per piece beyond the largest (by area), located at that
    piece's own bounding box (issue #37). A document with zero or one piece
    has nothing disconnected from anything else, so it yields no findings.

    Findings are returned in a fixed, deterministic order -- by the
    document's own path reference (element index, then subpath index) --
    independent of area, so the findings JSON this issue's persistence
    writes is byte-identical across a run and across platforms regardless of
    how :func:`vectorpress.validate._svg_geometry.parse_cut_file` happened to
    order equal-area pieces.
    """
    if len(pieces) <= 1:
        return []

    largest = max(pieces, key=lambda piece: piece.area)
    fragments = [piece for piece in pieces if piece is not largest]

    findings = [
        Finding(
            kind=_KIND,
            classification=_CLASSIFICATION,
            message=(
                f"disconnected fragment: path element {piece.element_index}, "
                f"subpath {piece.subpath_index} is separate from the design's largest piece"
            ),
            location=piece.bbox,
            path_reference=PathReference(
                element_index=piece.element_index,
                subpath_index=piece.subpath_index,
                id=piece.element_id,
            ),
        )
        for piece in fragments
    ]
    findings.sort(
        key=lambda finding: (
            finding.path_reference.element_index,
            finding.path_reference.subpath_index,
        )
    )
    return findings
