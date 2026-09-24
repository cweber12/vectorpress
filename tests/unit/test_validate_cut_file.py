"""validate.cut_file: the disconnected-fragments, accidental-dot,
tiny-isolated-shape and small-hole findings-report tracer (§9, §9.1, §35,
ADR 0006, ADR 0007, issue #37, issue #39).

Every SVG here is hand-written, never produced by
:mod:`vectorpress.pipeline.cut_svg` (``tests/integration/test_validate.py``
exercises the real fixture catalog end to end) -- ``validate_cut_file`` is a
pure function of bytes plus a reference size (ADR 0006), so a hand-edited
override is checked by exactly the same code a generated cut file is."""

import xml.etree.ElementTree as ET

import pytest

from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.finding import FindingKind, ValidationOutcome
from vectorpress.domain.recipe import RECIPES
from vectorpress.validate.cut_file import THRESHOLDS, validate_cut_file

REFERENCE_SIZE_IN = 3.0

_ONE_PIECE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="10" height="10">'
    b'<path d="M0,0 L10,0 L10,10 L0,10 Z"/></svg>'
)

_TWO_PIECE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 10" width="30" height="10">'
    b'<path d="M0,0 L10,0 L10,10 L0,10 Z M20,2 L28,2 L28,8 L20,8 Z"/></svg>'
)

_THREE_PIECE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 10" width="50" height="10">'
    b'<path d="M0,0 L10,0 L10,10 L0,10 Z'
    b" M20,2 L26,2 L26,8 L20,8 Z"
    b' M40,3 L45,3 L45,7 L40,7 Z"/></svg>'
)

# A donut -- one outer shell with one hole cut from it (even-odd) -- is a
# single physical piece, not two: the hole must not itself be counted as a
# disconnected fragment.
_RING_WITH_A_HOLE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="10" height="10" >'
    b'<path fill-rule="evenodd" d="M0,0 L10,0 L10,10 L0,10 Z M3,3 L7,3 L7,7 L3,7 Z"/></svg>'
)

_NO_VIEWBOX_NO_SIZE = (
    b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0,0 L10,0 L10,10 L0,10 Z"/></svg>'
)

_WIDTH_HEIGHT_ONLY_NO_VIEWBOX = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b'<path d="M0,0 L10,0 L10,10 L0,10 Z"/></svg>'
)


# --- one piece passes, two pieces need review (issue #37 acceptance criteria) --------------


def test_one_piece_svg_passes_with_no_findings() -> None:
    result = validate_cut_file(_ONE_PIECE, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.PASS
    assert result.findings == ()


def test_two_piece_svg_reports_exactly_one_disconnected_fragment_finding() -> None:
    result = validate_cut_file(_TWO_PIECE, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind is FindingKind.DISCONNECTED_FRAGMENTS


def test_two_piece_finding_is_located_at_the_smaller_pieces_own_bbox() -> None:
    """The smaller square (100 area units) is the one "beyond the largest"
    (10x10 = 100 area units for the first, 8x6 = 48 for the second -- the
    second is smaller, so it is the reported fragment, located at its own
    bounding box, not the larger piece's)."""
    result = validate_cut_file(_TWO_PIECE, REFERENCE_SIZE_IN)

    finding = result.findings[0]
    assert finding.location.min_x == pytest.approx(20.0)
    assert finding.location.min_y == pytest.approx(2.0)
    assert finding.location.max_x == pytest.approx(28.0)
    assert finding.location.max_y == pytest.approx(8.0)


def test_two_piece_finding_names_its_path_reference() -> None:
    """A path reference so an editor can navigate to it (issue #37): the
    element (this SVG's only ``<path>``, so index 0) and the offending
    subpath's index within it (the second subpath, index 1)."""
    result = validate_cut_file(_TWO_PIECE, REFERENCE_SIZE_IN)

    reference = result.findings[0].path_reference
    assert reference.element_index == 0
    assert reference.subpath_index == 1


def test_three_pieces_report_two_findings_neither_for_the_largest() -> None:
    result = validate_cut_file(_THREE_PIECE, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 2
    subpath_indices = {finding.path_reference.subpath_index for finding in result.findings}
    assert subpath_indices == {1, 2}  # subpath 0 is the largest piece, never a finding


def test_findings_are_in_a_deterministic_document_order() -> None:
    """Findings are ordered by path reference (element, then subpath index),
    not by area or any other incidental ordering (issue #37's "findings in a
    deterministic order")."""
    result = validate_cut_file(_THREE_PIECE, REFERENCE_SIZE_IN)

    ordered = [f.path_reference.subpath_index for f in result.findings]
    assert ordered == sorted(ordered)


def test_a_hole_in_a_ring_is_not_a_disconnected_fragment() -> None:
    """A donut is one physical piece with a hole cut out of it, not two
    pieces -- the hole must not itself be flagged (ADR 0007's "the design is
    more than one separate cut piece", not "more than one subpath")."""
    result = validate_cut_file(_RING_WITH_A_HOLE, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.PASS
    assert result.findings == ()


# --- physical scale: fails visibly with neither a viewBox nor width/height (§35) -----------


def test_svg_with_no_viewbox_and_no_width_or_height_fails_visibly() -> None:
    with pytest.raises(ValueError):
        validate_cut_file(_NO_VIEWBOX_NO_SIZE, REFERENCE_SIZE_IN)


def test_width_and_height_alone_are_enough_without_a_viewbox() -> None:
    """Falls back to ``width``/``height`` per issue #37's "falling back to
    width/height" -- only the *absence of both* fails."""
    result = validate_cut_file(_WIDTH_HEIGHT_ONLY_NO_VIEWBOX, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.PASS


def test_unparseable_svg_fails_visibly() -> None:
    with pytest.raises(ET.ParseError):
        validate_cut_file(b"not an svg document at all", REFERENCE_SIZE_IN)


# --- accidental dot, tiny isolated shape, small hole (issue #39) -------------------------
#
# Every SVG below shares one viewBox ("0 0 300 100") and REFERENCE_SIZE_IN
# (3.0in), so the physical scale is always 300 / 3.0 = 100 user units per
# inch -- THRESHOLDS' physical values convert to round user-unit numbers:
# accidental_dot_max_dimension_in (0.2in) is 20 user units,
# tiny_isolated_shape_min_area_in2 / small_hole_min_area_in2 (0.02in^2 each)
# is 200 square user units. A large main body (a 90x90 square, area 8100,
# dimension 90) anchors every SVG as the unambiguous largest piece -- never
# itself a dot/tiny-shape/fragment candidate (ADR 0007, issue #37).

_MAIN_BODY = "M0,0 L90,0 L90,90 L0,90 Z"

# A 5x5 square (area 25, dimension 5): well under both the dot threshold
# (20 units) and the tiny-shape area threshold (200 sq units) -- the dot
# check runs first, so this is reported as a dot, never a tiny shape.
_DOT_BELOW_THRESHOLD = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
    b'<path d="' + _MAIN_BODY.encode() + b" M200,0 L205,0 L205,5 L200,5 Z" + b'"/></svg>'
)

# A 25x25 square (area 625, dimension 25): at or above both thresholds, so
# neither the dot nor the tiny-shape check claims it -- it is still a real
# extra piece, so it is reported as a disconnected fragment instead (ADR
# 0007 has no size threshold for that kind at all).
_DOT_SIZED_PIECE_ABOVE_THRESHOLD = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
    b'<path d="' + _MAIN_BODY.encode() + b" M200,0 L225,0 L225,25 L200,25 Z" + b'"/></svg>'
)

# A 50x3 rectangle (area 150, dimension 50): area is under the tiny-shape
# threshold (200 sq units), but its dimension (50) is well above the dot
# threshold (20 units) -- not compact enough to read as a dot, so it falls
# through to the tiny-shape check instead (a thin sliver, issue #39's own
# example).
_SLIVER_BELOW_THRESHOLD = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
    b'<path d="' + _MAIN_BODY.encode() + b" M200,0 L250,0 L250,3 L200,3 Z" + b'"/></svg>'
)

# A 50x5 rectangle (area 250, dimension 50): area now at or above the
# tiny-shape threshold too, so neither the dot nor the tiny-shape check
# claims it -- reported as a disconnected fragment instead.
_SLIVER_SIZED_PIECE_ABOVE_THRESHOLD = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
    b'<path d="' + _MAIN_BODY.encode() + b" M200,0 L250,0 L250,5 L200,5 Z" + b'"/></svg>'
)

# The main body with a 10x10 hole (area 100) cut from its own interior
# (evenodd): under the small-hole threshold (200 sq units), and this
# document has no other piece at all, so the only finding is the hole.
_PINHOLE_BELOW_THRESHOLD = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
    b'<path fill-rule="evenodd" d="'
    + _MAIN_BODY.encode()
    + b" M40,40 L50,40 L50,50 L40,50 Z"
    + b'"/></svg>'
)

# The same shape with a 20x20 hole (area 400): at or above the small-hole
# threshold, so it is a genuinely kept hole -- no finding at all, and this
# document's only piece is otherwise unremarkable, so the whole file passes.
_PINHOLE_SIZED_HOLE_ABOVE_THRESHOLD = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
    b'<path fill-rule="evenodd" d="'
    + _MAIN_BODY.encode()
    + b" M35,35 L55,35 L55,55 L35,55 Z"
    + b'"/></svg>'
)

# One document combining every kind at once (mutual exclusion, issue #39):
# the main body (subpath 0) with its own small hole (subpath 1), a dot
# (subpath 2), a sliver (subpath 3), and a genuine extra piece well above
# both area/dimension thresholds (subpath 4, a 30x30 = 900 sq unit square).
_ONE_OF_EACH_KIND = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
    b'<path fill-rule="evenodd" d="'
    + _MAIN_BODY.encode()
    + b" M40,40 L50,40 L50,50 L40,50 Z"  # hole: subpath 1
    + b" M200,0 L205,0 L205,5 L200,5 Z"  # dot: subpath 2
    + b" M220,0 L270,0 L270,3 L220,3 Z"  # sliver: subpath 3
    + b" M200,50 L230,50 L230,80 L200,80 Z"  # fragment: subpath 4
    + b'"/></svg>'
)


def test_dot_below_threshold_yields_exactly_one_accidental_dot_finding() -> None:
    result = validate_cut_file(_DOT_BELOW_THRESHOLD, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind is FindingKind.ACCIDENTAL_DOT
    assert finding.location.min_x == pytest.approx(200.0)
    assert finding.location.min_y == pytest.approx(0.0)
    assert finding.location.max_x == pytest.approx(205.0)
    assert finding.location.max_y == pytest.approx(5.0)
    assert finding.measured_value == pytest.approx(0.05)
    assert finding.threshold == pytest.approx(0.2)


def test_dot_sized_piece_above_threshold_is_never_reported_as_a_dot() -> None:
    """Issue #39's "the same shapes above threshold yield none": no
    ACCIDENTAL_DOT (nor TINY_ISOLATED_SHAPE) finding -- the piece is still a
    real extra piece, so it is reported as a disconnected fragment instead
    (ADR 0007's "no bridging": a kept extra piece is always flagged
    *somehow*, just never as noise once it clears both thresholds)."""
    result = validate_cut_file(_DOT_SIZED_PIECE_ABOVE_THRESHOLD, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.ACCIDENTAL_DOT not in kinds
    assert FindingKind.TINY_ISOLATED_SHAPE not in kinds
    assert kinds == {FindingKind.DISCONNECTED_FRAGMENTS}


def test_sliver_below_threshold_yields_exactly_one_tiny_isolated_shape_finding() -> None:
    """This sliver is 3 units tall -- under both the tiny-shape area
    threshold (200 sq units) and, independently, the narrow-feature width
    threshold (10 units, issue #40): narrow_feature is not one of the three
    mutually-exclusive piece-classification kinds (:class:`FindingKind`'s
    own "one kind per shape" note names only accidental_dot,
    tiny_isolated_shape and disconnected_fragments), so it fires alongside
    tiny_isolated_shape rather than competing with it -- see
    ``test_sliver_below_threshold_is_also_a_narrow_feature`` below."""
    result = validate_cut_file(_SLIVER_BELOW_THRESHOLD, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    finding = next(f for f in result.findings if f.kind is FindingKind.TINY_ISOLATED_SHAPE)
    assert finding.location.min_x == pytest.approx(200.0)
    assert finding.location.min_y == pytest.approx(0.0)
    assert finding.location.max_x == pytest.approx(250.0)
    assert finding.location.max_y == pytest.approx(3.0)
    assert finding.measured_value == pytest.approx(0.015)
    assert finding.threshold == pytest.approx(0.02)


def test_sliver_below_threshold_is_also_a_narrow_feature() -> None:
    """Issue #40: narrow_feature and tiny_isolated_shape are independent
    axes over the same piece -- this sliver is both small in area and
    narrow in width, so it carries exactly one finding of each kind, never
    a conflict between them."""
    result = validate_cut_file(_SLIVER_BELOW_THRESHOLD, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert kinds == {FindingKind.TINY_ISOLATED_SHAPE, FindingKind.NARROW_FEATURE}


def test_sliver_sized_piece_above_threshold_is_never_reported_as_tiny() -> None:
    """Issue #39's "the same shapes above threshold yield none": no
    TINY_ISOLATED_SHAPE (nor ACCIDENTAL_DOT) finding -- reported as a
    disconnected fragment instead, the same reasoning as the dot case
    above. This sliver is still only 5 units tall, under the narrow-feature
    width threshold (10 units), so it also carries a NARROW_FEATURE finding
    (issue #40: an independent axis, not part of the three-way piece
    classification the first two assertions describe)."""
    result = validate_cut_file(_SLIVER_SIZED_PIECE_ABOVE_THRESHOLD, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.TINY_ISOLATED_SHAPE not in kinds
    assert FindingKind.ACCIDENTAL_DOT not in kinds
    assert kinds == {FindingKind.DISCONNECTED_FRAGMENTS, FindingKind.NARROW_FEATURE}


def test_pinhole_below_threshold_yields_exactly_one_small_hole_finding() -> None:
    result = validate_cut_file(_PINHOLE_BELOW_THRESHOLD, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind is FindingKind.SMALL_HOLE
    assert finding.location.min_x == pytest.approx(40.0)
    assert finding.location.min_y == pytest.approx(40.0)
    assert finding.location.max_x == pytest.approx(50.0)
    assert finding.location.max_y == pytest.approx(50.0)
    assert finding.measured_value == pytest.approx(0.01)
    assert finding.threshold == pytest.approx(0.02)


def test_hole_above_threshold_yields_no_findings_at_all() -> None:
    """Unlike the dot/sliver "above threshold" cases, a hole has no other
    detector competing for it -- a genuinely kept hole in an otherwise
    unremarkable single piece yields nothing at all, a clean pass."""
    result = validate_cut_file(_PINHOLE_SIZED_HOLE_ABOVE_THRESHOLD, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.PASS
    assert result.findings == ()


def test_mutual_exclusion_across_dot_tiny_shape_and_disconnected_fragment() -> None:
    """Issue #39's "one kind per shape": one document carrying a dot, a
    sliver, a genuine extra piece and a small hole all at once reports
    exactly one finding of each of those four kinds, each located at its own
    piece, and no piece's own path reference (element, subpath) appears
    under more than one of the three mutually-exclusive piece-classification
    kinds. The sliver (subpath 3, 50x3) is also narrower than the
    narrow-feature width threshold (issue #40) -- an independent axis, not
    part of that three-way exclusion -- so it carries a fifth finding,
    NARROW_FEATURE, on the very same piece as its own TINY_ISOLATED_SHAPE
    finding."""
    result = validate_cut_file(_ONE_OF_EACH_KIND, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 5

    by_kind = {finding.kind: finding for finding in result.findings}
    assert by_kind.keys() == {
        FindingKind.ACCIDENTAL_DOT,
        FindingKind.TINY_ISOLATED_SHAPE,
        FindingKind.DISCONNECTED_FRAGMENTS,
        FindingKind.SMALL_HOLE,
        FindingKind.NARROW_FEATURE,
    }
    assert by_kind[FindingKind.ACCIDENTAL_DOT].path_reference.subpath_index == 2
    assert by_kind[FindingKind.TINY_ISOLATED_SHAPE].path_reference.subpath_index == 3
    assert by_kind[FindingKind.DISCONNECTED_FRAGMENTS].path_reference.subpath_index == 4
    assert by_kind[FindingKind.SMALL_HOLE].path_reference.subpath_index == 1
    assert by_kind[FindingKind.NARROW_FEATURE].path_reference.subpath_index == 3

    # No piece (element, subpath) pair is claimed by more than one of the
    # three mutually-exclusive piece-classification kinds.
    exclusive_kinds = {
        FindingKind.ACCIDENTAL_DOT,
        FindingKind.TINY_ISOLATED_SHAPE,
        FindingKind.DISCONNECTED_FRAGMENTS,
    }
    claimed = [
        (finding.path_reference.element_index, finding.path_reference.subpath_index)
        for finding in result.findings
        if finding.kind in exclusive_kinds
    ]
    assert len(claimed) == len(set(claimed))


# --- cleanup vs. validation: every cleanup threshold is strictly smaller (issue #39) ------


def test_every_cut_svg_cleanup_threshold_is_strictly_below_its_validation_counterpart() -> None:
    """ADR 0007: cleanup removes what is plainly noise before tracing even
    happens; validation flags what is borderline for a human to decide.
    A later tweak to either set must keep cleanup strictly smaller than the
    validation threshold it sits under, or a shape/hole/feature cleanup
    would have kept could never even reach validation to be flagged (issue
    #40 extends this to the cut_svg opening width against the
    narrow-feature minimum width)."""
    cleanup_parameters = RECIPES[DerivativeType.CUT_SVG].parameters

    island_min_area_in2 = cleanup_parameters["island_min_area_in2"]
    hole_min_area_in2 = cleanup_parameters["hole_min_area_in2"]
    opening_width_in = cleanup_parameters["opening_width_in"]
    assert isinstance(island_min_area_in2, float)
    assert isinstance(hole_min_area_in2, float)
    assert isinstance(opening_width_in, float)

    assert island_min_area_in2 < THRESHOLDS["tiny_isolated_shape_min_area_in2"]
    assert hole_min_area_in2 < THRESHOLDS["small_hole_min_area_in2"]
    assert opening_width_in < THRESHOLDS["narrow_feature_min_width_in"]


# --- narrow feature: a dumbbell with a below/above-threshold neck (issue #40) -------------
#
# Both dumbbells share one viewBox ("0 0 300 100") and REFERENCE_SIZE_IN
# (3.0in), the same 100-user-units-per-inch scale every test above uses:
# narrow_feature_min_width_in (0.1in) is 10 user units. Two 30x30 lobes (at
# the left and right edges) are joined by a single horizontal neck, centered
# vertically -- only the neck's own height (its width, in the narrow-feature
# sense) differs between the two shapes.

_DUMBBELL_NARROW_NECK = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
    b'<path d="M0,35 L30,35 L30,47.5 L70,47.5 L70,35 L100,35 L100,65 L70,65 L70,52.5 '
    b'L30,52.5 L30,65 L0,65 Z"/></svg>'
)  # neck height 5 units (0.05in): below the 10-unit (0.1in) threshold.

_DUMBBELL_WIDE_NECK = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
    b'<path d="M0,35 L30,35 L30,40 L70,40 L70,35 L100,35 L100,65 L70,65 L70,60 '
    b'L30,60 L30,65 L0,65 Z"/></svg>'
)  # neck height 25 units (0.25in): comfortably above the 10-unit threshold.


def test_dumbbell_with_a_narrow_neck_yields_one_narrow_feature_finding_at_the_neck() -> None:
    result = validate_cut_file(_DUMBBELL_NARROW_NECK, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind is FindingKind.NARROW_FEATURE
    assert finding.path_reference.element_index == 0
    assert finding.path_reference.subpath_index == 0
    # Located around the neck (x between the two lobes, y around its own
    # 47.5-52.5 span) -- not the lobes themselves, and not the shape's own
    # sharp corners (filtered as opening artifacts, this module's own
    # ``_raster._MIN_ELONGATION``).
    assert finding.location.min_x == pytest.approx(30.625)
    assert finding.location.max_x == pytest.approx(69.375)
    assert finding.location.min_y == pytest.approx(47.5)
    assert finding.location.max_y == pytest.approx(52.5)
    assert finding.measured_value == pytest.approx(0.05)
    assert finding.threshold == pytest.approx(0.1)


def test_dumbbell_with_a_wide_neck_yields_no_narrow_feature_finding() -> None:
    """The same dumbbell, only the neck widened above the threshold (issue
    #40's own acceptance criterion): no NARROW_FEATURE finding -- and
    nothing else either, since this shape trips no other §9 kind."""
    result = validate_cut_file(_DUMBBELL_WIDE_NECK, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.PASS
    assert result.findings == ()


# --- excessive geometric complexity: node density and the absolute cap (issue #40) --------


def test_a_path_with_far_too_many_nodes_for_its_size_yields_one_excessive_complexity() -> None:
    """A jagged sawtooth outline along one edge of a small square: 40 tiny
    (0.05-unit amplitude) zigzag segments -- far more nodes than a nearly
    straight edge this short needs, well above
    ``excessive_complexity_max_nodes_per_in`` (issue #40's own "nodes per
    inch of perimeter"). The amplitude is deliberately tiny (unlike
    ``narrow_feature``'s own dumbbell fixture above) so this shape trips
    only excessive_complexity, not narrow_feature too."""
    teeth = 40
    amplitude = 0.05
    points = ["M0,0"]
    for i in range(teeth):
        x = 20 * i / teeth
        y = amplitude if i % 2 == 0 else -amplitude
        points.append(f"L{x:.4f},{y:.4f}")
    points.append("L20,0 L20,20 L0,20 Z")
    jagged_d = " ".join(points)
    jagged_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
        b'<path d="' + jagged_d.encode() + b'"/></svg>'
    )

    result = validate_cut_file(jagged_svg, REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind is FindingKind.EXCESSIVE_COMPLEXITY
    assert finding.path_reference.element_index == 0
    assert finding.path_reference.subpath_index == 0
    assert finding.measured_value is not None
    assert finding.threshold is not None
    assert finding.measured_value > finding.threshold


def test_a_simple_path_of_the_same_size_yields_no_excessive_complexity_finding() -> None:
    """A plain 20x20 square -- same physical size as the jagged shape above,
    four nodes instead of dozens -- trips no complexity finding."""
    simple_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" width="300" height="100">'
        b'<path d="M0,0 L20,0 L20,20 L0,20 Z"/></svg>'
    )

    result = validate_cut_file(simple_svg, REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.EXCESSIVE_COMPLEXITY not in kinds
