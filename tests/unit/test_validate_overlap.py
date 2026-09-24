"""validate.overlap: the unintended-overlap findings-report tracer (§9,
§9.1, ADR 0006, ADR 0007, issue #41).

Every SVG here is hand-written, never produced by :mod:`vectorpress.
pipeline.cut_svg` -- ``validate_cut_file`` is a pure function of bytes plus
a reference size (ADR 0006), so a hand-edited override is checked by
exactly the same code a generated cut file is (§9's own scope bullet 5)."""

from vectorpress.domain.finding import FindingKind, ValidationOutcome
from vectorpress.validate.cut_file import validate_cut_file

REFERENCE_SIZE_IN = 3.0

_HEAD = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">'
_TAIL = b"</svg>"


# --- self-intersection ------------------------------------------------------------------------


def test_self_intersecting_bowtie_yields_one_overlap_finding() -> None:
    """A bowtie -- two edges on opposite sides of the ring crossing each
    other at the middle."""
    svg = _HEAD + b'<path d="M0,0 L100,100 L100,0 L0,100 Z"/>' + _TAIL

    result = validate_cut_file(svg, REFERENCE_SIZE_IN, catalog_reference_size_in=REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    findings = [f for f in result.findings if f.kind is FindingKind.OVERLAP]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.related_path_reference is None  # a self-intersection, not a pair
    assert finding.location is not None
    assert finding.location.min_x == 50.0
    assert finding.location.max_x == 50.0
    assert finding.location.min_y == 50.0
    assert finding.location.max_y == 50.0


def test_simple_convex_polygon_has_no_self_intersection() -> None:
    """Near miss: a plain, simple (non-self-crossing) square."""
    svg = _HEAD + b'<path d="M0,0 L100,0 L100,100 L0,100 Z"/>' + _TAIL

    result = validate_cut_file(svg, REFERENCE_SIZE_IN, catalog_reference_size_in=REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.OVERLAP not in kinds


# --- two shapes whose boundaries genuinely cross -----------------------------------------------


def test_two_overlapping_shapes_yield_one_overlap_finding_naming_both() -> None:
    """``b`` is smaller than ``a`` and its own centroid lands inside ``a``,
    so the piece/hole containment-parity model would misclassify it as a
    hole of ``a`` -- part of its own boundary genuinely sticks out past
    ``a``'s own edge, which only a real edge-crossing test (not that
    model) catches (this module's own docstring)."""
    svg = (
        _HEAD
        + b'<path id="a" d="M0,0 L60,0 L60,60 L0,60 Z"/>'
        + b'<path id="b" d="M40,40 L70,40 L70,70 L40,70 Z"/>'
        + _TAIL
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN, catalog_reference_size_in=REFERENCE_SIZE_IN)

    assert result.outcome is ValidationOutcome.NEEDS_REVIEW
    findings = [f for f in result.findings if f.kind is FindingKind.OVERLAP]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.path_reference.id == "a"
    assert finding.related_path_reference is not None
    assert finding.related_path_reference.id == "b"
    # No small_hole finding either: the misclassified "hole" is well above
    # the small-hole area threshold, and this test only cares that it is
    # not silently swallowed as a clean hole -- overlap is what catches it.
    assert FindingKind.SMALL_HOLE not in {f.kind for f in result.findings}


def test_a_proper_hole_is_not_an_overlap() -> None:
    """Near miss: a genuinely well-nested hole, fully inside its parent,
    boundaries never crossing."""
    svg = (
        _HEAD
        + b'<path fill-rule="evenodd" d="M0,0 L90,0 L90,90 L0,90 Z '
        + b'M40,40 L50,40 L50,50 L40,50 Z"/>'
        + _TAIL
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN, catalog_reference_size_in=REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.OVERLAP not in kinds


def test_two_disjoint_shapes_yield_no_overlap_finding() -> None:
    """Near miss: two shapes nowhere near each other."""
    svg = (
        _HEAD
        + b'<path id="a" d="M0,0 L20,0 L20,20 L0,20 Z"/>'
        + b'<path id="b" d="M50,50 L70,50 L70,70 L50,70 Z"/>'
        + _TAIL
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN, catalog_reference_size_in=REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.OVERLAP not in kinds


def test_two_identical_stacked_shapes_are_duplicate_not_overlap() -> None:
    """Two coincident rings' edges run collinear on top of each other,
    never crossing transversally -- :mod:`vectorpress.validate.
    duplicate_geometry`'s own concern, not this module's."""
    svg = (
        _HEAD
        + b'<path fill-rule="evenodd" d="M0,0 L90,0 L90,90 L0,90 Z '
        + b"M40,40 L60,40 L60,60 L40,60 Z "
        + b'M40,40 L60,40 L60,60 L40,60 Z"/>'
        + _TAIL
    )

    result = validate_cut_file(svg, REFERENCE_SIZE_IN, catalog_reference_size_in=REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.OVERLAP not in kinds
    assert FindingKind.DUPLICATE_GEOMETRY in kinds


def test_two_crossing_bare_line_segments_are_not_an_overlap() -> None:
    """Near miss (issue #41 review fix round 1): two open, two-point
    subpaths whose own segments genuinely cross are never tested here --
    a subpath under three points has no real interior, so neither
    self-intersection nor a pairwise ring crossing means anything for it;
    :mod:`vectorpress.validate.open_path` is the one detector a bare line
    segment reaches."""
    svg = _HEAD + b'<path d="M0,0 L40,40 M0,40 L40,0"/>' + _TAIL

    result = validate_cut_file(svg, REFERENCE_SIZE_IN, catalog_reference_size_in=REFERENCE_SIZE_IN)

    kinds = {finding.kind for finding in result.findings}
    assert FindingKind.OVERLAP not in kinds
