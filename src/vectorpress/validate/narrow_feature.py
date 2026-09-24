"""The ``narrow_feature`` detector (§9, §9.1, ADR 0007, issue #40).

A part of a piece's own geometry narrower than the physical minimum feature
width (§9.1) -- a thin tentacle, a neck joining two lobes, a fragile bridge
-- reads as too fragile to manufacture cleanly: it can tear during cutting,
weeding or handling. Detected by rasterizing each piece (its own shell minus
its own immediate holes, :mod:`vectorpress.validate._raster`) and comparing
it against a morphological opening sized from the threshold: whatever the
opening erases is, by construction, narrower than the threshold somewhere
along its own length (the same technique :mod:`vectorpress.pipeline.
cut_svg`'s own cleanup uses to erase a hairline spur, reused here purely to
measure).

Unlike :mod:`vectorpress.validate.accidental_dot`, :mod:`vectorpress.
validate.tiny_isolated_shape` and :mod:`vectorpress.validate.
disconnected_fragments`, this detector is not one of the three
piece-*classification* kinds :class:`~vectorpress.domain.finding.FindingKind`
documents as mutually exclusive -- a narrow neck is a property of one
piece's own geometry, not a judgment about the piece as a whole, so this
runs over *every* piece the document has, largest included (the fixture
this issue adds trips it on the document's own main body).

One piece can carry more than one narrow region (two separate thin necks,
say) -- one finding per connected region the opening erased, not one per
piece.
"""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    BoundingBox,
    Finding,
    FindingKind,
    PathReference,
)
from vectorpress.domain.numeric_format import round_number
from vectorpress.validate._raster import narrow_regions, pixel_size_for_min_width, rasterize_piece
from vectorpress.validate._svg_geometry import Piece

_KIND = FindingKind.NARROW_FEATURE
_CLASSIFICATION = CLASSIFICATION[_KIND]


def _sort_key(finding: Finding) -> tuple[int, int | None, float, float]:
    """This module's own finding order (element, subpath, then the narrow
    region's own top-left corner) -- a small named function rather than an
    inline lambda so it can assert ``location`` is set, which it always is
    for every finding this module's own :func:`detect` builds (issue #41
    widened :class:`~vectorpress.domain.finding.Finding.location` to
    ``BoundingBox | None`` for kinds with no geometry; this one always has
    some)."""
    assert finding.location is not None
    return (
        finding.path_reference.element_index,
        finding.path_reference.subpath_index,
        finding.location.min_y,
        finding.location.min_x,
    )


def detect(
    pieces: list[Piece], scale_user_units_per_inch: float, min_width_in: float
) -> list[Finding]:
    """One finding per connected region narrower than ``min_width_in``
    physical inches found anywhere in any piece, converted to this
    document's own user units via ``scale_user_units_per_inch`` (§9.1).

    Findings are returned in a fixed, deterministic order -- by path
    reference (element index, then subpath index), then by the narrow
    region's own top-left corner for the (rare) case of more than one in a
    single piece -- matching every other detector in this package (issue
    #37's own ordering rule).
    """
    min_width_user_units = min_width_in * scale_user_units_per_inch
    pixel_size = pixel_size_for_min_width(min_width_user_units)

    findings: list[Finding] = []
    for piece in pieces:
        raster = rasterize_piece(piece.outer_ring, piece.hole_rings, pixel_size)
        for region in narrow_regions(raster):
            location = BoundingBox(
                min_x=round_number(raster.origin_x + region.min_col * pixel_size),
                min_y=round_number(raster.origin_y + region.min_row * pixel_size),
                max_x=round_number(raster.origin_x + region.max_col * pixel_size),
                max_y=round_number(raster.origin_y + region.max_row * pixel_size),
            )
            width_in = round_number(
                region.narrowest_width_px * pixel_size / scale_user_units_per_inch
            )
            findings.append(
                Finding(
                    kind=_KIND,
                    classification=_CLASSIFICATION,
                    message=(
                        f"narrow feature: path element {piece.element_index}, "
                        f"subpath {piece.subpath_index} narrows to {width_in}in wide, "
                        f"below the {min_width_in}in minimum feature width"
                    ),
                    location=location,
                    path_reference=PathReference(
                        element_index=piece.element_index,
                        subpath_index=piece.subpath_index,
                        id=piece.element_id,
                    ),
                    measured_value=width_in,
                    threshold=round_number(min_width_in),
                )
            )

    findings.sort(key=_sort_key)
    return findings
