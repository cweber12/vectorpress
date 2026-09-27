"""``vectorpress.validate.cut_file``: the cut-file findings-report entry
point (§9, §9.1, ADR 0006, ADR 0007).

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
    duplicate_geometry,
    excessive_complexity,
    narrow_feature,
    open_path,
    overlap,
    raster_content,
    small_hole,
    stray_object,
    tiny_isolated_shape,
)
from vectorpress.validate._document_elements import parse_document_elements
from vectorpress.validate._pieces import Piece, parse_cut_file
from vectorpress.validate._subpaths import parse_subpaths
from vectorpress.validate._svg_document import parse_svg_document, svg_viewbox_longest_side

#: Every physical-unit threshold the §9 detectors use, keyed by name,
#: recorded verbatim with every findings report. :func:`vectorpress.
#: validate.disconnected_fragments.detect` has no size threshold of its own
#: -- "more than one piece" is a count, not a measurement against a physical
#: size -- so it contributes no entry here, nor do the detectors whose
#: findings are structural (open path, raster content, duplicate geometry,
#: overlap).
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
#: min_perimeter_in`` and ``excessive_complexity_max_node_count`` have no
#: cleanup counterpart -- ``cut_svg``'s own cleanup never
#: simplifies node count directly (``curve_tolerance`` governs potrace's own
#: curve fitting, not a physical threshold this table could sit strictly
#: above the same way an area or width can) -- see :mod:`vectorpress.
#: validate.excessive_complexity` for how the three combine.
#:
#: ``excessive_complexity_min_perimeter_in``: below this perimeter, "nodes per inch" is not judged at all -- a plain
#: 4-6 node dot or sliver a few hundredths of an inch across otherwise reads
#: as tens of nodes per inch purely from being tiny, nothing to do with
#: genuine complexity (exactly what :mod:`vectorpress.validate.
#: accidental_dot`/:mod:`vectorpress.validate.tiny_isolated_shape` already
#: name). ``0.75`` sits comfortably above every such piece this fixture
#: catalog's own dot/sliver subjects (``gumboot_chiton``, ``bat_star``)
#: produce at either the catalog default or ``kelp_forest_mini_pack``'s own
#: smaller reference-size override (their own perimeters top out around
#: 0.52in at the catalog default, smaller still at the override), and
#: comfortably below a genuine second piece's own perimeter (``owl_limpet``'s
#: detached island, upward of 1.5in at the catalog default).
#:
#: ``excessive_complexity_max_nodes_per_in``: ``11.0`` sits above every
#: real-art fixture outline at the catalog default, while
#: ``coralline_algae``'s finely rippled outline clears it (~13.4 nodes/in).
#: Both ``excessive_complexity`` measures that take a size are judged at the
#: catalog reference size, never a product's override (ADR 0010), so these
#: values mean the same thing at every product size.
#:
#: ``stray_object_off_canvas_tolerance_in``: :mod:`vectorpress.validate.
#: stray_object`'s own off-canvas check applies this tolerance to a
#: ``<path>`` element only
#: (every other element tag keeps an exact, tolerance-free check): this
#: package's own curve-flattening can disagree with the document's own
#: written ``viewBox`` by a fraction of a user unit of pure rounding noise
#: (§36's :data:`~vectorpress.domain.numeric_format.DECIMAL_PLACES`
#: absorbs everything past the fourth decimal place everywhere *else* this
#: tool writes a number, but the ``viewBox`` text and a freshly
#: re-flattened path bbox are two *independent* roundings of numbers that
#: were never exactly equal to begin with). Measured directly (not
#: assumed) against every ``<path>`` in every fixture asset's own
#: generated cut file, at both the catalog default (3in) and
#: ``kelp_forest_mini_pack``'s own override (1in): the single largest
#: discrepancy anywhere is ``bat_star``'s own, ``0.0001`` user units
#: (~1.15e-6in at the catalog's 3in default) -- everything else is exactly
#: ``0.0``. ``0.01in`` sits four orders of magnitude above that measured
#: noise floor -- a comfortable margin for a different platform's own
#: last-bit curve-sampling difference -- while staying far below anything
#: a genuinely stray, off-canvas ``<path>`` (the hand-authored stray-object
#: trip fixture places one tens of user units away) would ever measure.
THRESHOLDS: dict[str, float] = {
    "accidental_dot_max_dimension_in": 0.2,
    "tiny_isolated_shape_min_area_in2": 0.02,
    "small_hole_min_area_in2": 0.02,
    "narrow_feature_min_width_in": 0.1,
    "excessive_complexity_max_nodes_per_in": 11.0,
    "excessive_complexity_min_perimeter_in": 0.75,
    "excessive_complexity_max_node_count": 300.0,
    "stray_object_off_canvas_tolerance_in": 0.01,
}


def _claimed(findings: list[Finding]) -> set[tuple[int, int | None]]:
    """The ``(element_index, subpath_index)`` of every piece a detector's
    findings already claimed: how :func:`validate_cut_file`
    keeps dot, tiny-shape and disconnected-fragment classification mutually
    exclusive without each detector needing to know about the others --
    a piece is simply never offered to the next detector once one finding
    already names it. ``findings`` here is always :mod:`vectorpress.
    validate.accidental_dot`/:mod:`vectorpress.validate.tiny_isolated_shape`
    output, whose own ``subpath_index`` is always a concrete piece index,
    never ``None`` (an element-only reference is only ever built by the
    element- and subpath-level detectors, which never call this) -- the wider ``int | None``
    element type is only to match :class:`~vectorpress.domain.finding.
    PathReference`'s own declared field type."""
    return {
        (finding.path_reference.element_index, finding.path_reference.subpath_index)
        for finding in findings
    }


def _unclaimed(pieces: list[Piece], claimed: set[tuple[int, int | None]]) -> list[Piece]:
    return [piece for piece in pieces if (piece.element_index, piece.subpath_index) not in claimed]


def validate_cut_file(
    svg_bytes: bytes, reference_size_in: float, *, catalog_reference_size_in: float
) -> ValidationResult:
    """Validate one cut file's bytes against every §9 detector, at
    ``reference_size_in`` physical inches (§9.1); each detector contributes
    its own findings to the same result.

    ``catalog_reference_size_in`` is the size the cut file was actually
    cleaned and traced at (ADR 0009): the catalog default, unless the asset
    behind it set its own cleanup size (ADR 0012) -- the caller resolves
    which one applies (:func:`vectorpress.domain.reference_size.
    resolve_cleanup_size_in` for a catalog asset; the catalog default itself
    for ``vpress validate --file``, which has no asset to carry an
    override). :mod:`vectorpress.validate.excessive_complexity` alone is
    judged there rather than at ``reference_size_in`` (ADR 0010, ADR 0012):
    complexity is a property of the traced geometry, not of how large it is
    cut. Every other detector judges what can physically be cut at
    ``reference_size_in``.

    The bytes are parsed once (:func:`~vectorpress.validate._svg_document.
    parse_svg_document`), and three views are derived from that one parse:
    pieces and holes grouped by containment parity (:func:`~vectorpress.
    validate._pieces.parse_cut_file`), every subpath as authored
    (:func:`~vectorpress.validate._subpaths.parse_subpaths`), and every
    element as it sits in the document (:func:`~vectorpress.validate.
    _document_elements.parse_document_elements`).

    A piece is checked against :mod:`accidental_dot` first, then
    :mod:`tiny_isolated_shape`, then :mod:`disconnected_fragments` -- each
    detector only ever sees the pieces the one before it left unclaimed
    (:func:`_unclaimed`), so a piece is reported as exactly one of the
    three, never more than one ("one kind per shape", documented on
    :class:`~vectorpress.domain.finding.FindingKind`). Holes are an
    independent axis (:mod:`vectorpress.validate.small_hole`): a hole is
    never also a piece, so it never competes with any of the three.

    Every other detector -- narrow feature, excessive complexity, open
    path, raster content, stray object, duplicate geometry and overlap -- is
    a further independent axis, never part of that three-way exclusion and
    never claiming or excluding a piece for anyone else: a piece's (or a
    document's) own geometry can be narrow, disproportionately complex,
    unclosed, stray, duplicated or overlapping *on top of* whatever else it
    was already reported as. The last five run over the raw subpath and
    element views, never the piece/hole grouping -- a malformed subpath
    (unclosed, self-intersecting) cannot be reliably classified into that
    grouping to begin with, and :mod:`vectorpress.validate.overlap` in
    particular must not rely on it (that module's own docstring). The §8
    builder only ever emits closed, filled, non-overlapping, non-duplicated
    paths with no raster content and no stray elements, so none of these
    five kinds is ever tripped by a generated cut file (locked by
    ``tests/integration/test_validate.py``) -- only a hand-edited override
    can trip them (§9's own scope bullet 5: "validation runs on any SVG
    derivative, not only generated ones").

    Raises :class:`ValueError` for an SVG with no ``viewBox`` and no
    ``width``/``height`` to establish a scale from, or with unparseable path
    data, and :class:`xml.etree.ElementTree.ParseError` for malformed XML --
    a validation failure (§35), never reported as passing.
    """
    document = parse_svg_document(svg_bytes)
    parsed = parse_cut_file(document, reference_size_in)
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

    # Computed the same way ``parse_cut_file`` computes ``scale``, so when the
    # two sizes are equal the two scales are bit-identical.
    catalog_scale = svg_viewbox_longest_side(document) / catalog_reference_size_in
    complexity_findings = excessive_complexity.detect(
        parsed.pieces,
        catalog_scale,
        THRESHOLDS["excessive_complexity_max_nodes_per_in"],
        THRESHOLDS["excessive_complexity_min_perimeter_in"],
        THRESHOLDS["excessive_complexity_max_node_count"],
    )

    subpaths = parse_subpaths(document)
    view_box, elements = parse_document_elements(document)

    open_path_findings = open_path.detect(subpaths)
    raster_content_findings = raster_content.detect(elements)
    stray_object_findings = stray_object.detect(
        view_box, elements, scale, THRESHOLDS["stray_object_off_canvas_tolerance_in"]
    )
    duplicate_geometry_findings = duplicate_geometry.detect(subpaths)
    overlap_findings = overlap.detect(subpaths)

    findings: list[Finding] = [
        *dot_findings,
        *tiny_findings,
        *fragment_findings,
        *hole_findings,
        *narrow_findings,
        *complexity_findings,
        *open_path_findings,
        *raster_content_findings,
        *stray_object_findings,
        *duplicate_geometry_findings,
        *overlap_findings,
    ]
    return ValidationResult(findings=tuple(findings))
