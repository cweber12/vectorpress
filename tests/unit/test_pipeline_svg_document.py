"""pipeline.svg_document: the shared §8-clean SVG document builder (issue
#24 review fix round 1, finding 4).

Feeds hand-built :class:`~vectorpress.pipeline.svg_document.Subpath`
geometry directly -- no PNG, no potrace -- so this tests the module's own
math (true Bézier bbox extrema, degenerate-subpath dropping, deterministic
number formatting) independent of what a real tracer happens to produce.
``tests/unit/test_pipeline_silhouette_svg.py`` only exercises this module
indirectly, through actual traced output, which never happens to include a
genuinely degenerate subpath -- so "no zero-area subpaths" (§8) was
previously assumed, not tested.
"""

import pytest

from vectorpress.pipeline.svg_document import (
    CornerSegment,
    CurveSegment,
    Fill,
    Subpath,
    format_number,
    render_path_d,
    render_svg,
    tight_viewbox,
)

# --- format_number: deterministic, trimmed, sign-safe (§36) ------------------------


def test_format_number_trims_trailing_zeros() -> None:
    assert format_number(3.5) == "3.5"


def test_format_number_trims_a_whole_number_to_no_decimal_point_at_all() -> None:
    assert format_number(3.0) == "3"


def test_format_number_keeps_up_to_four_decimal_places() -> None:
    assert format_number(1 / 3) == "0.3333"


def test_format_number_rounds_the_fifth_decimal_place() -> None:
    assert format_number(0.123456) == "0.1235"


def test_format_number_preserves_a_negative_sign() -> None:
    assert format_number(-2.5) == "-2.5"


def test_format_number_normalises_negative_zero_to_zero() -> None:
    """A tiny negative float that rounds to zero at four decimal places
    must not serialise as the literal text ``-0`` (§36: deterministic,
    and not a confusing value for a design tool to read)."""
    assert format_number(-0.00001) == "0"
    assert format_number(-0.0) == "0"


def test_format_number_of_exactly_zero_is_zero() -> None:
    assert format_number(0.0) == "0"


# --- degenerate subpaths are dropped (§8: "no zero-area subpaths") -----------------


def _point_subpath(point: tuple[float, float] = (1.0, 1.0)) -> Subpath:
    """A single-point "subpath": a corner segment whose vertex and end both
    equal its own start -- the simplest possible zero-area degenerate case
    (e.g. a one-pixel speck that ``speckle_size`` failed to catch, or a
    tracer quirk)."""
    return Subpath(start=point, segments=(CornerSegment(through=point, end=point),))


def _flat_line_subpath() -> Subpath:
    """A "subpath" that is a straight line back and forth along one axis --
    every point collinear, so its bounding box has zero height: degenerate
    even though it is not a single point."""
    return Subpath(
        start=(0.0, 5.0),
        segments=(
            CornerSegment(through=(4.0, 5.0), end=(8.0, 5.0)),
            CornerSegment(through=(4.0, 5.0), end=(0.0, 5.0)),
        ),
    )


def _square_subpath() -> Subpath:
    """A real, non-degenerate 4x4 square, corners only (straight lines)."""
    return Subpath(
        start=(0.0, 0.0),
        segments=(
            CornerSegment(through=(4.0, 0.0), end=(4.0, 0.0)),
            CornerSegment(through=(4.0, 4.0), end=(4.0, 4.0)),
            CornerSegment(through=(0.0, 4.0), end=(0.0, 4.0)),
            CornerSegment(through=(0.0, 0.0), end=(0.0, 0.0)),
        ),
    )


def test_render_svg_drops_a_single_point_degenerate_subpath() -> None:
    """The degenerate point contributes nothing to the document: it is
    absent from the rendered path data and the viewBox is exactly the real
    square's own bounds, not expanded to include the stray point."""
    output = render_svg(
        [Fill(fill="#000000", subpaths=[_square_subpath(), _point_subpath((100.0, 100.0))])]
    )

    text = output.decode("utf-8")
    assert "100" not in text
    assert 'viewBox="0 0 4 4"' in text


def test_render_svg_drops_a_zero_height_flat_line_subpath() -> None:
    output = render_svg([Fill(fill="#000000", subpaths=[_square_subpath(), _flat_line_subpath()])])

    text = output.decode("utf-8")
    assert 'viewBox="0 0 4 4"' in text
    assert text.count("M") == 1  # only the square's own subpath was rendered


def test_render_svg_raises_when_every_subpath_is_degenerate() -> None:
    with pytest.raises(ValueError, match="no non-degenerate geometry"):
        render_svg([Fill(fill="#000000", subpaths=[_point_subpath()])])


def test_render_svg_raises_for_no_subpaths_at_all() -> None:
    with pytest.raises(ValueError, match="no non-degenerate geometry"):
        render_svg([])


def test_render_svg_raises_when_every_fill_is_entirely_degenerate() -> None:
    """Several fills, each entirely degenerate, still add up to nothing
    renderable (not just a single empty fill)."""
    with pytest.raises(ValueError, match="no non-degenerate geometry"):
        render_svg(
            [
                Fill(fill="#ff0000", subpaths=[_point_subpath()]),
                Fill(fill="#00ff00", subpaths=[_flat_line_subpath()]),
            ]
        )


# --- several fills: one <path> per fill, in the order given, viewBox spans all ----


def test_render_svg_emits_one_path_per_fill_in_the_given_order() -> None:
    small_square = Subpath(
        start=(1.0, 1.0),
        segments=(
            CornerSegment(through=(2.0, 1.0), end=(2.0, 1.0)),
            CornerSegment(through=(2.0, 2.0), end=(2.0, 2.0)),
            CornerSegment(through=(1.0, 2.0), end=(1.0, 2.0)),
            CornerSegment(through=(1.0, 1.0), end=(1.0, 1.0)),
        ),
    )
    output = render_svg(
        [
            Fill(fill="#ff0000", subpaths=[_square_subpath()]),
            Fill(fill="#00ff00", subpaths=[small_square]),
        ]
    )

    text = output.decode("utf-8")
    red_index = text.index('fill="#ff0000"')
    green_index = text.index('fill="#00ff00"')
    assert red_index < green_index  # document order matches the given fill order
    assert text.count("<path") == 2
    assert 'viewBox="0 0 4 4"' in text  # tight to the union of both fills' geometry


def test_render_svg_drops_a_fill_whose_own_subpaths_are_all_degenerate() -> None:
    """§8: "no invisible elements" -- a fill contributing nothing visible
    gets no ``<path>`` element at all, not an empty one."""
    output = render_svg(
        [
            Fill(fill="#000000", subpaths=[_square_subpath()]),
            Fill(fill="#ff0000", subpaths=[_point_subpath((100.0, 100.0))]),
        ]
    )

    text = output.decode("utf-8")
    assert text.count("<path") == 1
    assert "#ff0000" not in text


# --- tight_viewbox: true curve extrema, not control points (review fix round 1) ----


def test_tight_viewbox_of_straight_corners_is_exact() -> None:
    """Straight lines have no interior extrema: the tight bbox of a
    corners-only subpath is exactly its vertices, computable by hand."""
    assert tight_viewbox([_square_subpath()]) == (0.0, 0.0, 4.0, 4.0)


def test_tight_viewbox_of_a_curve_is_tighter_than_its_control_polygon() -> None:
    """The exact segment from the real ``ochre_sea_star`` fixture snapshot
    that the review flagged: its control points reach down to x=2.6531,
    but the curve itself never gets past x≈3.0398 -- verified here against
    a value computed independently, by sampling the curve very finely
    (2000 steps), not by re-deriving svg_document's own extrema formula."""
    segment = CurveSegment(c1=(2.6531, 10.2531), c2=(2.6531, 5.7469), end=(4.2, 4.2))
    subpath = Subpath(start=(4.2, 11.8), segments=(segment,))

    min_x, min_y, width, height = tight_viewbox([subpath])
    max_x, max_y = min_x + width, min_y + height

    # Independent fine-sampling check (De Casteljau evaluation, not svg_document's).
    p0, p1, p2, p3 = subpath.start, segment.c1, segment.c2, segment.end
    steps = 2000
    sampled_xs: list[float] = []
    sampled_ys: list[float] = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        sampled_xs.append(
            mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        )
        sampled_ys.append(
            mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        )

    tolerance = 1e-4
    assert min_x == pytest.approx(min(sampled_xs), abs=tolerance)
    assert max_x == pytest.approx(max(sampled_xs), abs=tolerance)
    assert min_y == pytest.approx(min(sampled_ys), abs=tolerance)
    assert max_y == pytest.approx(max(sampled_ys), abs=tolerance)

    # And explicitly: the curve never reaches its control points' own x=2.6531.
    assert min_x > 2.6531
    assert min_x < 3.05


# --- render_path_d: command mapping -------------------------------------------------


def test_render_path_d_maps_a_corner_to_two_line_commands() -> None:
    segment = CornerSegment(through=(1.0, 2.0), end=(3.0, 4.0))
    subpath = Subpath(start=(0.0, 0.0), segments=(segment,))

    assert render_path_d([subpath]) == "M0,0L1,2L3,4Z"


def test_render_path_d_maps_a_curve_to_one_c_command() -> None:
    segment = CurveSegment(c1=(1.0, 2.0), c2=(3.0, 4.0), end=(5.0, 6.0))
    subpath = Subpath(start=(0.0, 0.0), segments=(segment,))

    assert render_path_d([subpath]) == "M0,0C1,2 3,4 5,6Z"


def test_render_path_d_concatenates_multiple_subpaths() -> None:
    square = _square_subpath()

    d = render_path_d([square, square])

    assert d.count("M") == 2
    assert d.count("Z") == 2
