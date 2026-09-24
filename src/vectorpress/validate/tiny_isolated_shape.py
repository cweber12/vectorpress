"""The ``tiny_isolated_shape`` detector (§9, §9.1, ADR 0007, issue #39).

An isolated shape (any piece but the document's largest -- the same
candidate pool :mod:`vectorpress.validate.accidental_dot` and
:mod:`vectorpress.validate.disconnected_fragments` draw from) whose own area
is below the physical minimum shape area (§9.1) reads as noise too small to
manufacture cleanly -- a thin sliver, for example, whose bounding box may
still be large (elongated, not compact) but whose actual cut area is not.

``pieces`` here is already the candidate pool with every
:mod:`vectorpress.validate.accidental_dot` finding's own piece removed by
:mod:`vectorpress.validate.cut_file` (issue #39's "dot and tiny shape are
mutually exclusive by construction"): a compact piece small enough to read
as a dot is reported only there, never here too, even though a dot's area is
typically small as well.
"""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    Finding,
    FindingKind,
    PathReference,
)
from vectorpress.domain.numeric_format import round_number
from vectorpress.validate._svg_geometry import Piece, non_largest_pieces

_KIND = FindingKind.TINY_ISOLATED_SHAPE
_CLASSIFICATION = CLASSIFICATION[_KIND]


def detect(
    pieces: list[Piece], scale_user_units_per_inch: float, min_area_in2: float
) -> list[Finding]:
    """One finding per isolated piece whose own area is below
    ``min_area_in2`` physical square inches, converted to this document's
    own user units via ``scale_user_units_per_inch`` (§9.1). The document's
    largest piece is never a candidate (:func:`~vectorpress.validate.
    _svg_geometry.non_largest_pieces`) -- ``pieces`` also excludes whatever
    :mod:`vectorpress.validate.accidental_dot` already claimed, passed in by
    :mod:`vectorpress.validate.cut_file`.

    Findings are returned in a fixed, deterministic order -- by path
    reference (element index, then subpath index) -- matching every other
    detector in this package (issue #37's own ordering rule).
    """
    min_area_user_units2 = min_area_in2 * scale_user_units_per_inch**2
    candidates = non_largest_pieces(pieces)
    slivers = [piece for piece in candidates if piece.area < min_area_user_units2]

    findings = [
        Finding(
            kind=_KIND,
            classification=_CLASSIFICATION,
            message=(
                f"tiny isolated shape: path element {piece.element_index}, "
                f"subpath {piece.subpath_index} has area "
                f"{round_number(piece.area / scale_user_units_per_inch**2)}in², "
                f"below the {min_area_in2}in² minimum shape area"
            ),
            location=piece.bbox,
            path_reference=PathReference(
                element_index=piece.element_index,
                subpath_index=piece.subpath_index,
                id=piece.element_id,
            ),
            measured_value=round_number(piece.area / scale_user_units_per_inch**2),
            threshold=round_number(min_area_in2),
        )
        for piece in slivers
    ]
    findings.sort(
        key=lambda finding: (
            finding.path_reference.element_index,
            finding.path_reference.subpath_index,
        )
    )
    return findings
