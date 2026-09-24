"""The ``small_hole`` detector (§9, §9.1, ADR 0007, issue #39).

A hole (an interior ring, :class:`~vectorpress.validate._svg_geometry.Hole`)
whose own area is below the physical minimum hole area (§9.1) reads as
manufacturing noise -- too small to punch or cut cleanly, or an artifact of
tracing -- rather than a deliberately kept opening.

Unlike :mod:`vectorpress.validate.accidental_dot` and :mod:`vectorpress.
validate.tiny_isolated_shape`, this detector never scopes to "every hole but
the largest": a hole is not a piece, has no "largest hole" carve-out to make
(ADR 0007 only ever exempts the document's one largest *piece* from being
its own finding), and holes never compete with dot/tiny-shape/disconnected-
fragment classification -- those three are piece kinds; this is the one
detector over holes.
"""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    Finding,
    FindingKind,
    PathReference,
)
from vectorpress.domain.numeric_format import round_number
from vectorpress.validate._svg_geometry import Hole

_KIND = FindingKind.SMALL_HOLE
_CLASSIFICATION = CLASSIFICATION[_KIND]


def detect(
    holes: list[Hole], scale_user_units_per_inch: float, min_area_in2: float
) -> list[Finding]:
    """One finding per hole whose own area is below ``min_area_in2``
    physical square inches, converted to this document's own user units via
    ``scale_user_units_per_inch`` (§9.1).

    Findings are returned in a fixed, deterministic order -- by path
    reference (element index, then subpath index) -- matching every other
    detector in this package (issue #37's own ordering rule).
    """
    min_area_user_units2 = min_area_in2 * scale_user_units_per_inch**2
    tiny_holes = [hole for hole in holes if hole.area < min_area_user_units2]

    findings = [
        Finding(
            kind=_KIND,
            classification=_CLASSIFICATION,
            message=(
                f"very small hole: path element {hole.element_index}, "
                f"subpath {hole.subpath_index} has area "
                f"{round_number(hole.area / scale_user_units_per_inch**2)}in², "
                f"below the {min_area_in2}in² minimum hole area"
            ),
            location=hole.bbox,
            path_reference=PathReference(
                element_index=hole.element_index,
                subpath_index=hole.subpath_index,
                id=hole.element_id,
            ),
            measured_value=round_number(hole.area / scale_user_units_per_inch**2),
            threshold=round_number(min_area_in2),
        )
        for hole in tiny_holes
    ]
    findings.sort(
        key=lambda finding: (
            finding.path_reference.element_index,
            finding.path_reference.subpath_index,
        )
    )
    return findings
