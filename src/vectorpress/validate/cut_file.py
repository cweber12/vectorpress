"""``vectorpress.validate.cut_file``: the cut-file findings-report entry
point (§9, §9.1, ADR 0006, ADR 0007, issue #37).

A pure function from an effective derivative's own SVG bytes plus a
reference size to a :class:`~vectorpress.domain.finding.ValidationResult`
(ADR 0006's "validate: pure functions from geometry to findings") -- takes
bytes, not :mod:`vectorpress.pipeline`'s in-memory ``Subpath``, so a
hand-edited override (PRD 4) is checked by exactly the same code a generated
cut file is. This module (and everything under ``vectorpress.validate``)
never imports :mod:`vectorpress.pipeline`, and :mod:`vectorpress.pipeline.
generate` never calls this: ``pipeline`` and ``validate`` are independent
sibling layers (CLAUDE.md, ``pyproject.toml``'s import-linter contract).
"""

from vectorpress.domain.finding import Finding, ValidationResult
from vectorpress.validate import (
    accidental_dot,
    disconnected_fragments,
    excessive_complexity,
    narrow_feature,
    small_hole,
    tiny_isolated_shape,
)
from vectorpress.validate._svg_geometry import Piece, parse_cut_file

#: Every physical-unit threshold this issue's detectors use, keyed by name,
#: recorded verbatim with every findings report (issue #37's "the thresholds
#: used"). :func:`vectorpress.validate.disconnected_fragments.detect` has no
#: size threshold of its own -- "more than one piece" is a count, not a
#: measurement against a physical size -- so it contributes no entry here;
#: later issues add the rest of §9's list.
#:
#: Each area threshold here is strictly larger than the matching
#: :mod:`vectorpress.pipeline.cut_svg` cleanup threshold it sits above
#: (``island_min_area_in2`` / ``hole_min_area_in2``, both ``0.01`` --
#: :mod:`vectorpress.domain.recipe`): cleanup removes what is plainly noise
#: before tracing even happens (ADR 0007), so a shape or hole that survives
#: cleanup can still be small enough that a human should decide whether to
#: keep it. ``narrow_feature_min_width_in`` follows the same rule against
#: ``opening_width_in`` (``0.06``): cleanup's own morphological opening
#: already erases anything narrower than that width before tracing, so a
#: feature that survives cleanup can still be narrow enough to flag --
#: locked by ``tests/unit/test_validate_cut_file.py``'s own
#: ``test_every_cut_svg_cleanup_threshold_is_strictly_below_its_validation_counterpart``.
#:
#: ``accidental_dot_max_dimension_in`` has no cleanup counterpart -- cleanup's
#: own island removal only ever measures area, never a shape's extent -- but
#: its value is still constrained by ``island_min_area_in2`` in one
#: direction: a *circle* (the most area-efficient shape for a given extent)
#: at exactly this dimension has area pi*(0.1)^2 =~ 0.0314in^2, comfortably
#: above the 0.01in^2 island floor, so a genuinely round, barely-surviving
#: island still has room to be compact enough to read as a dot rather than
#: only ever falling through to the tiny-shape check. A value at or below
#: ~0.113in (the diameter whose circle area equals ``island_min_area_in2``
#: exactly) would make every dot-shaped candidate mathematically incapable
#: of surviving cleanup at all -- no shape could ever trip this detector.
#:
#: ``excessive_complexity_max_nodes_per_in``, ``excessive_complexity_
#: min_perimeter_in`` and ``excessive_complexity_max_node_count`` (issue
#: #40) have no cleanup counterpart -- ``cut_svg``'s own cleanup never
#: simplifies node count directly (``curve_tolerance`` governs potrace's own
#: curve fitting, not a physical threshold this table could sit strictly
#: above the same way an area or width can) -- see :mod:`vectorpress.
#: validate.excessive_complexity` for how the three combine.
#:
#: ``excessive_complexity_min_perimeter_in`` (review fix round 1, PR #46):
#: below this perimeter, "nodes per inch" is not judged at all -- a plain
#: 4-6 node dot or sliver a few hundredths of an inch across otherwise reads
#: as tens of nodes per inch purely from being tiny, nothing to do with
#: genuine complexity (exactly what :mod:`vectorpress.validate.
#: accidental_dot`/:mod:`vectorpress.validate.tiny_isolated_shape` already
#: name). ``0.75`` sits comfortably above every such piece this fixture
#: catalog's own dot/sliver subjects (``gumboot_chiton``, ``bat_star``)
#: produce at either the catalog default or ``kelp_forest_mini_pack``'s own
#: smaller reference-size override (their own perimeters top out around
#: 0.52in at the catalog default, smaller still at the override), and
#: comfortably below a genuine second piece's own perimeter (``giant_green_
#: anemone``'s and ``owl_limpet``'s own detached islands, each upward of
#: 1.5in at the catalog default).
#:
#: ``excessive_complexity_max_nodes_per_in`` (review fix round 1, PR #46):
#: ``11.0`` sits above the densest *judged* (perimeter at or above
#: ``excessive_complexity_min_perimeter_in``) piece any pre-existing fixture
#: asset produces at either reference size -- ``giant_green_anemone``'s own
#: detached island, ~9.56 nodes/in at ``kelp_forest_mini_pack``'s 1in
#: override, the highest observed -- with room to spare, while
#: ``coralline_algae``'s own finely rippled outline (issue #40) clears it
#: with a comfortable margin too (~13.4 nodes/in at the catalog default).
THRESHOLDS: dict[str, float] = {
    "accidental_dot_max_dimension_in": 0.2,
    "tiny_isolated_shape_min_area_in2": 0.02,
    "small_hole_min_area_in2": 0.02,
    "narrow_feature_min_width_in": 0.1,
    "excessive_complexity_max_nodes_per_in": 11.0,
    "excessive_complexity_min_perimeter_in": 0.75,
    "excessive_complexity_max_node_count": 300.0,
}


def _claimed(findings: list[Finding]) -> set[tuple[int, int]]:
    """The ``(element_index, subpath_index)`` of every piece a detector's
    findings already claimed (issue #39): how :func:`validate_cut_file`
    keeps dot, tiny-shape and disconnected-fragment classification mutually
    exclusive without each detector needing to know about the others --
    a piece is simply never offered to the next detector once one finding
    already names it."""
    return {
        (finding.path_reference.element_index, finding.path_reference.subpath_index)
        for finding in findings
    }


def _unclaimed(pieces: list[Piece], claimed: set[tuple[int, int]]) -> list[Piece]:
    return [piece for piece in pieces if (piece.element_index, piece.subpath_index) not in claimed]


def validate_cut_file(svg_bytes: bytes, reference_size_in: float) -> ValidationResult:
    """Validate one cut file's bytes against every landed §9 detector, at
    ``reference_size_in`` physical inches (§9.1) -- issue #37 lands
    :func:`vectorpress.validate.disconnected_fragments.detect`; issue #39
    adds :mod:`vectorpress.validate.accidental_dot`, :mod:`vectorpress.
    validate.tiny_isolated_shape` and :mod:`vectorpress.validate.small_hole`;
    issue #40 adds :mod:`vectorpress.validate.narrow_feature` and
    :mod:`vectorpress.validate.excessive_complexity`; later issues add the
    rest of §9's list here, each contributing its own findings to the same
    result.

    A piece is checked against :mod:`accidental_dot` first, then
    :mod:`tiny_isolated_shape`, then :mod:`disconnected_fragments` -- each
    detector only ever sees the pieces the one before it left unclaimed
    (:func:`_unclaimed`), so a piece is reported as exactly one of the
    three, never more than one (issue #39's "one kind per shape", documented
    on :class:`~vectorpress.domain.finding.FindingKind`). Holes are an
    independent axis (:mod:`vectorpress.validate.small_hole`): a hole is
    never also a piece, so it never competes with any of the three. Narrow
    feature and excessive complexity (issue #40) are two further independent
    axes, checked against *every* piece the document has -- largest
    included, and regardless of whatever :mod:`accidental_dot`/
    :mod:`tiny_isolated_shape`/:mod:`disconnected_fragments` already claimed
    -- since neither is a piece-*classification* judgment the way those
    three are: a piece's own geometry can be narrow, or disproportionately
    complex, on top of whatever else it was already reported as.

    Raises :class:`ValueError` (propagated from :func:`vectorpress.validate.
    _svg_geometry.parse_cut_file`) for an SVG with no ``viewBox`` and no
    ``width``/``height`` to establish a scale from, or that otherwise fails
    to parse -- a validation failure (§35), never reported as passing.
    """
    parsed = parse_cut_file(svg_bytes, reference_size_in)
    scale = parsed.scale_user_units_per_inch

    dot_findings = accidental_dot.detect(
        parsed.pieces, scale, THRESHOLDS["accidental_dot_max_dimension_in"]
    )
    claimed = _claimed(dot_findings)

    tiny_findings = tiny_isolated_shape.detect(
        _unclaimed(parsed.pieces, claimed), scale, THRESHOLDS["tiny_isolated_shape_min_area_in2"]
    )
    claimed |= _claimed(tiny_findings)

    fragment_findings = disconnected_fragments.detect(_unclaimed(parsed.pieces, claimed))

    hole_findings = small_hole.detect(parsed.holes, scale, THRESHOLDS["small_hole_min_area_in2"])

    narrow_findings = narrow_feature.detect(
        parsed.pieces, scale, THRESHOLDS["narrow_feature_min_width_in"]
    )

    complexity_findings = excessive_complexity.detect(
        parsed.pieces,
        scale,
        THRESHOLDS["excessive_complexity_max_nodes_per_in"],
        THRESHOLDS["excessive_complexity_min_perimeter_in"],
        THRESHOLDS["excessive_complexity_max_node_count"],
    )

    findings: list[Finding] = [
        *dot_findings,
        *tiny_findings,
        *fragment_findings,
        *hole_findings,
        *narrow_findings,
        *complexity_findings,
    ]
    return ValidationResult(findings=tuple(findings))
