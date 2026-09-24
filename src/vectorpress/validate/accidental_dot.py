"""The ``accidental_dot`` detector (§9, §9.1, ADR 0007, issue #39).

An isolated shape (any piece but the document's largest, the same "isolated
shape" candidate pool :mod:`vectorpress.validate.disconnected_fragments`
draws from) whose own bounding box's longest side is below the physical dot
threshold (§9.1) reads as accidental noise -- a speck the source artwork
never meant to keep as its own cut piece -- rather than a deliberately kept
detail, however far it sits from every other piece.

Checked *before* :mod:`vectorpress.validate.tiny_isolated_shape` by
:mod:`vectorpress.validate.cut_file` (issue #39's "dot and tiny shape are
mutually exclusive by construction"): a piece compact enough in every
direction to read as a dot is reported as exactly that, never also
considered for the area-based tiny-shape check.
"""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    Finding,
    FindingKind,
    PathReference,
)
from vectorpress.domain.numeric_format import round_number
from vectorpress.validate._svg_geometry import Piece, non_largest_pieces

_KIND = FindingKind.ACCIDENTAL_DOT
_CLASSIFICATION = CLASSIFICATION[_KIND]


def detect(
    pieces: list[Piece], scale_user_units_per_inch: float, max_dimension_in: float
) -> list[Finding]:
    """One finding per isolated piece whose bounding box's longest side is
    below ``max_dimension_in`` physical inches, converted to this document's
    own user units via ``scale_user_units_per_inch`` (§9.1). The document's
    largest piece is never a candidate (:func:`~vectorpress.validate.
    _svg_geometry.non_largest_pieces`), the same scoping
    :mod:`vectorpress.validate.disconnected_fragments` uses.

    Findings are returned in a fixed, deterministic order -- by path
    reference (element index, then subpath index) -- matching every other
    detector in this package (issue #37's own ordering rule).
    """
    max_dimension_user_units = max_dimension_in * scale_user_units_per_inch
    candidates = non_largest_pieces(pieces)
    dots = [piece for piece in candidates if piece.largest_dimension < max_dimension_user_units]

    findings = [
        Finding(
            kind=_KIND,
            classification=_CLASSIFICATION,
            message=(
                f"accidental dot: path element {piece.element_index}, "
                f"subpath {piece.subpath_index} is only "
                f"{round_number(piece.largest_dimension / scale_user_units_per_inch)}in "
                f"across, below the {max_dimension_in}in dot threshold"
            ),
            location=piece.bbox,
            path_reference=PathReference(
                element_index=piece.element_index,
                subpath_index=piece.subpath_index,
                id=piece.element_id,
            ),
            measured_value=round_number(piece.largest_dimension / scale_user_units_per_inch),
            threshold=round_number(max_dimension_in),
        )
        for piece in dots
    ]
    findings.sort(
        key=lambda finding: (
            finding.path_reference.element_index,
            finding.path_reference.subpath_index,
        )
    )
    return findings
