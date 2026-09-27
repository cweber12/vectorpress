"""pipeline.flatcolor_svg: the flat-color SVG generator (§6.9, §8, issue
#25).

Builds its own tiny source PNGs with Pillow, in memory, rather than reading
the fixture catalog: this module's job is the generator's quantization,
tracing and cleaning behaviour, not catalog wiring
(``tests/integration/test_generate.py`` exercises that end to end). No
filesystem is touched anywhere in this file -- the generator takes bytes,
not a path (ADR 0006).
"""

import re
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import RECIPES
from vectorpress.pipeline.flatcolor_svg import generate

Rgba = tuple[int, int, int, int]

TRANSPARENT: Rgba = (0, 0, 0, 0)
RED: Rgba = (220, 20, 20, 255)
GREEN: Rgba = (20, 160, 20, 255)
BLUE: Rgba = (20, 20, 220, 255)

SIZE = 16


def _source_bytes(pixels: list[list[Rgba]]) -> bytes:
    """An RGBA PNG's bytes, from a row-major grid of ``(r, g, b, a)`` pixels."""
    height = len(pixels)
    width = len(pixels[0])
    image = Image.new("RGBA", (width, height))
    for y, row in enumerate(pixels):
        for x, pixel in enumerate(row):
            image.putpixel((x, y), pixel)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _two_squares_bytes(size: int = SIZE) -> bytes:
    """A red square on the left, a green square on the right, each 6x6,
    separated by transparent pixels -- two disjoint, equal-area regions."""
    grid = [[TRANSPARENT for _ in range(size)] for _ in range(size)]
    for y in range(2, 8):
        for x in range(2, 8):
            grid[y][x] = RED
        for x in range(9, 15):
            grid[y][x] = GREEN
    return _source_bytes(grid)


def _nested_squares_bytes(size: int = SIZE) -> bytes:
    """A large blue square (10x10) with a smaller red square (4x4) fully
    enclosed inside it -- the "region fully enclosed by another" case."""
    grid = [[TRANSPARENT for _ in range(size)] for _ in range(size)]
    for y in range(3, 13):
        for x in range(3, 13):
            grid[y][x] = BLUE
    for y in range(6, 10):
        for x in range(6, 10):
            grid[y][x] = RED
    return _source_bytes(grid)


def _solid_square_bytes(size: int = SIZE, color: Rgba = RED) -> bytes:
    grid = [[color for _ in range(size)] for _ in range(size)]
    return _source_bytes(grid)


def _lanczos_downsampled_two_color_bytes(scale: int = 4, small_size: int = 200) -> bytes:
    """A genuinely anti-aliased two-color image (review fix round 1, issue
    #25), not a hand-crafted uniform blend seam: a hard-edged red/green
    split drawn at ``scale`` times ``small_size``, then downsampled with
    Pillow's LANCZOS filter -- the way a real illustration reaches this
    generator. LANCZOS's ringing spreads the boundary across several output
    pixels, each its own slightly different blend shade (verified: at
    ``scale=4, small_size=200`` this yields 8 distinct opaque colors -- the
    2 true ones plus 6 blend shades -- none of the blend shades over 0.5%
    of the image's ink pixels, comfortably under the recipe's default 1%
    ``min_color_share``), unlike the single uniform blend color the
    hand-made test above uses."""
    large_size = small_size * scale
    big = Image.new("RGBA", (large_size, large_size), RED)
    draw = ImageDraw.Draw(big)
    mid = large_size // 2
    draw.rectangle([mid, 0, large_size, large_size], fill=GREEN)
    small = big.resize((small_size, small_size), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    small.save(buffer, format="PNG")
    return buffer.getvalue()


def _concentric_disks_bytes(size: int = SIZE) -> bytes:
    """A round blue disk with a smaller round red disk inside it -- curved
    boundaries, unlike the squares above, so curve-fitting tolerance
    actually has geometry to smooth."""
    cx, cy = size / 2, size / 2
    grid: list[list[Rgba]] = []
    for y in range(size):
        row: list[Rgba] = []
        for x in range(size):
            distance = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
            if distance <= 2.5:
                row.append(RED)
            elif distance <= 6.5:
                row.append(BLUE)
            else:
                row.append(TRANSPARENT)
        grid.append(row)
    return _source_bytes(grid)


# --- SVG parsing helpers (test-only: verify the geometry our own renderer --
# produced, not a general-purpose SVG engine) --------------------------------


def _paths(svg_bytes: bytes) -> list[tuple[str, str]]:
    """Every ``(fill, d)`` pair, one per ``<path>`` element, in document
    order."""
    text = svg_bytes.decode("utf-8")
    return re.findall(r'<path fill="(#[0-9a-f]{6})"[^>]*\sd="([^"]*)"', text)


def _view_box(svg_bytes: bytes) -> tuple[float, float, float, float]:
    match = re.search(r'viewBox="([^"]*)"', svg_bytes.decode("utf-8"))
    assert match is not None, "no viewBox attribute found"
    min_x, min_y, width, height = (float(n) for n in match.group(1).split())
    return min_x, min_y, width, height


_COMMAND_RE = re.compile(r"([MLCZ])([^MLCZ]*)")


def _flatten_cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 24,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        points.append((x, y))
    return points


def _flatten_all_path_points(svg_bytes: bytes) -> list[tuple[float, float]]:
    """Every point on every subpath of every ``<path>`` in ``svg_bytes``,
    Bézier curves flattened into line segments -- for an "is everything
    inside the viewBox" check, not a general-purpose SVG engine."""
    points: list[tuple[float, float]] = []
    for _fill, d in _paths(svg_bytes):
        pos = (0.0, 0.0)
        for command, arg_text in _COMMAND_RE.findall(d):
            numbers = [float(n) for n in re.split(r"[,\s]+", arg_text.strip()) if n]
            if command in ("M", "L"):
                pos = (numbers[0], numbers[1])
                points.append(pos)
            elif command == "C":
                p1, p2, p3 = (
                    (numbers[0], numbers[1]),
                    (numbers[2], numbers[3]),
                    (numbers[4], numbers[5]),
                )
                points.extend(_flatten_cubic(pos, p1, p2, p3))
                pos = p3
    return points


# --- quantization: one fill per distinct opaque color, exact source colors --


def test_two_disjoint_colors_trace_to_two_fills_with_the_exact_source_colors() -> None:
    result = generate(_two_squares_bytes(), {})

    paths = _paths(result.output_bytes)
    fills = {fill for fill, _d in paths}
    assert fills == {"#dc1414", "#14a014"}  # RED, GREEN as hex, exactly


def test_fill_count_matches_the_number_of_distinct_opaque_source_colors() -> None:
    result = generate(_nested_squares_bytes(), {})

    paths = _paths(result.output_bytes)
    assert len(paths) == 2  # blue and red only -- no invented third color


def test_a_single_flat_color_source_traces_to_one_fill() -> None:
    result = generate(_solid_square_bytes(), {})

    paths = _paths(result.output_bytes)
    assert len(paths) == 1
    assert paths[0][0] == "#dc1414"


# --- nesting: an enclosed region is present and painted above its enclosure -


def test_enclosed_region_is_present_and_painted_above_the_region_enclosing_it() -> None:
    """Acceptance criterion 2: the smaller red square, fully inside the
    blue one, must both exist in the output and come after (so it paints on
    top of) blue's own ``<path>``."""
    result = generate(_nested_squares_bytes(), {})

    text = result.output_bytes.decode("utf-8")
    assert 'fill="#dc1414"' in text  # the enclosed region is present
    assert text.index('fill="#1414dc"') < text.index('fill="#dc1414"')


def test_the_enclosing_regions_own_path_has_a_hole_where_the_enclosed_color_sits() -> None:
    """The blue square's mask excludes the red square's pixels, so potrace
    traces blue with a hole there (evenodd fill rule keeps it a hole,
    exactly as ``silhouette_svg``'s own ring case does) -- not just red
    painted on top of a fully solid blue underneath."""
    result = generate(_nested_squares_bytes(), {})

    paths = _paths(result.output_bytes)
    blue_d = next(d for fill, d in paths if fill == "#1414dc")
    assert blue_d.count("M") == 2  # outer boundary and the inner hole


# --- §8: true vector, clean bounds, nothing but the artwork -----------------


def test_output_has_no_image_element_or_raster_data() -> None:
    result = generate(_two_squares_bytes(), {})

    text = result.output_bytes.decode("utf-8")
    assert "<image" not in text
    assert "data:image" not in text


def test_output_paths_have_no_stroke_and_no_groups_metadata_comments() -> None:
    result = generate(_two_squares_bytes(), {})

    text = result.output_bytes.decode("utf-8")
    assert text.count("<path") == 2
    assert text.count('stroke="none"') == 2
    assert "<g" not in text
    assert "<metadata" not in text
    assert "<!--" not in text
    assert "inkscape" not in text.lower()
    assert "illustrator" not in text.lower()


def test_view_box_is_tight_to_the_geometry_not_the_full_source_canvas() -> None:
    result = generate(_two_squares_bytes(), {})

    _min_x, _min_y, width, height = _view_box(result.output_bytes)
    assert width < SIZE
    assert height < SIZE


def test_nothing_is_outside_the_view_box() -> None:
    result = generate(_two_squares_bytes(), {})

    min_x, min_y, width, height = _view_box(result.output_bytes)
    max_x, max_y = min_x + width, min_y + height
    for x, y in _flatten_all_path_points(result.output_bytes):
        assert min_x - 1e-6 <= x <= max_x + 1e-6
        assert min_y - 1e-6 <= y <= max_y + 1e-6


def test_width_and_height_match_the_view_box_so_proportions_hold() -> None:
    result = generate(_two_squares_bytes(), {})

    text = result.output_bytes.decode("utf-8")
    _min_x, _min_y, vb_width, vb_height = _view_box(result.output_bytes)
    width_match = re.search(r'\swidth="([^"]*)"', text)
    height_match = re.search(r'\sheight="([^"]*)"', text)
    assert width_match is not None
    assert height_match is not None
    assert float(width_match.group(1)) == vb_width
    assert float(height_match.group(1)) == vb_height


# --- fill order: area descending, then color (§36 determinism + nesting) ---


def test_fills_are_ordered_by_traced_area_descending() -> None:
    """The nested squares' outer (blue, area 100 minus the 16-pixel hole =
    84) comes before the smaller enclosed one (red, area 16)."""
    result = generate(_nested_squares_bytes(), {})

    paths = _paths(result.output_bytes)
    assert [fill for fill, _d in paths] == ["#1414dc", "#dc1414"]


def test_equal_area_fills_are_ordered_by_color_as_a_tie_break() -> None:
    """The two 6x6 squares (36 pixels each) tie on area, so the ascending
    hex color breaks the tie deterministically (§36)."""
    result = generate(_two_squares_bytes(), {})

    paths = _paths(result.output_bytes)
    assert [fill for fill, _d in paths] == ["#14a014", "#dc1414"]  # green < red, sorted ascending


# --- determinism (§36) -------------------------------------------------------


def test_generation_is_byte_deterministic() -> None:
    source_bytes = _nested_squares_bytes()

    first = generate(source_bytes, {})
    second = generate(source_bytes, {})

    assert first.output_bytes == second.output_bytes


def test_reports_the_potracer_numpy_and_scipy_versions_it_used() -> None:
    import importlib.metadata

    import numpy as np

    result = generate(_two_squares_bytes(), {})

    assert result.library_versions == {
        "potracer": importlib.metadata.version("potracer"),
        "numpy": np.__version__,
        "scipy": importlib.metadata.version("scipy"),
    }


# --- quantization and tracing parameters (issue #25) -------------------------


def test_max_colors_caps_the_number_of_fills() -> None:
    """Three distinct colors, capped to two: only the two most frequent
    survive as their own fill; the third's pixels fold into whichever
    survivor they are nearest -- never a third, invented color."""
    grid = [[TRANSPARENT for _ in range(SIZE)] for _ in range(SIZE)]
    for y in range(2, 14):
        for x in range(2, 6):
            grid[y][x] = RED
        for x in range(6, 10):
            grid[y][x] = GREEN
        for x in range(10, 14):
            grid[y][x] = BLUE
    source_bytes = _source_bytes(grid)

    uncapped = generate(source_bytes, {})
    assert len(_paths(uncapped.output_bytes)) == 3

    capped = generate(source_bytes, {"max_colors": 2})
    paths = _paths(capped.output_bytes)
    assert len(paths) == 2
    fills = {fill for fill, _d in paths}
    assert fills <= {"#dc1414", "#14a014", "#1414dc"}


def test_a_blended_edge_pixel_folds_into_the_nearest_palette_color() -> None:
    """Isolates the nearest-palette-color *folding* mechanism on its own,
    independent of ``min_color_share`` (tested separately below): a pixel
    colored exactly halfway between two real palette colors must not become
    a third, tiny region of its own -- it is folded into whichever of the
    two palette colors it is nearest (a tie is broken toward the more
    frequent, thus first, palette color -- deterministic, §36). ``max_colors``
    is capped here only to force this single uniform blend color out of the
    palette regardless of its share, so this test exercises folding in
    isolation; ``test_a_genuinely_anti_aliased_boundary_folds_to_only_the_
    true_flat_colors_at_production_defaults`` below covers the real case --
    many distinct, individually low-share blend shades excluded by
    ``min_color_share`` at the recipe's own default parameters, no
    ``max_colors`` override needed."""
    grid = [[TRANSPARENT for _ in range(SIZE)] for _ in range(SIZE)]
    for y in range(2, 14):
        for x in range(2, 7):
            grid[y][x] = RED
        for x in range(9, 14):
            grid[y][x] = GREEN
    # A one-pixel-wide blended seam between the two colors.
    blend: Rgba = (
        (RED[0] + GREEN[0]) // 2,
        (RED[1] + GREEN[1]) // 2,
        (RED[2] + GREEN[2]) // 2,
        255,
    )
    for y in range(2, 14):
        grid[y][7] = blend
        grid[y][8] = blend
    source_bytes = _source_bytes(grid)

    # Capped to the two real colors: this uniform blend is a full 24-pixel
    # column (16.7% of the ink), well above any reasonable min_color_share,
    # so max_colors is what forces it out here -- see the docstring above.
    result = generate(source_bytes, {"max_colors": 2})

    paths = _paths(result.output_bytes)
    fills = {fill for fill, _d in paths}
    assert fills == {"#dc1414", "#14a014"}  # only the two real colors, never the blend


def test_a_genuinely_anti_aliased_boundary_folds_at_production_defaults() -> None:
    """Review fix round 1, issue #25: a real anti-aliased image (LANCZOS
    downsampling, not a hand-made uniform blend), run through ``generate``
    with the *recipe's own production parameters*
    (``RECIPES[FLATCOLOR_SVG].parameters``) -- no ``max_colors`` override
    engineered to force folding, unlike the test above. Confirmed this would
    have failed before ``min_color_share`` existed: with it forced to ``0``
    (no share filtering, the old behaviour), the same source's 6 distinct
    blend shades all survive as their own fills alongside the 2 real
    colors, since 8 is under ``max_colors``' default of 16."""
    source_bytes = _lanczos_downsampled_two_color_bytes()

    result = generate(source_bytes, dict(RECIPES[DerivativeType.FLATCOLOR_SVG].parameters))

    fills = {fill for fill, _d in _paths(result.output_bytes)}
    assert fills == {"#dc1414", "#14a014"}


def test_min_color_share_controls_which_colors_count_as_genuinely_flat() -> None:
    """A small but real 4-pixel green region among 96 red pixels (4% share)
    survives a permissive threshold as its own fill, and is folded away --
    like a stray blend shade -- once the threshold is raised above its
    share."""
    grid = [[TRANSPARENT for _ in range(SIZE)] for _ in range(SIZE)]
    for y in range(2, 14):
        for x in range(2, 10):
            grid[y][x] = RED
    for y in (6, 7):
        for x in (11, 12):
            grid[y][x] = GREEN
    source_bytes = _source_bytes(grid)

    permissive = generate(source_bytes, {"min_color_share": 0.01})
    assert {fill for fill, _d in _paths(permissive.output_bytes)} == {"#dc1414", "#14a014"}

    strict = generate(source_bytes, {"min_color_share": 0.5})
    assert {fill for fill, _d in _paths(strict.output_bytes)} == {"#dc1414"}  # green folded in


def test_alpha_threshold_controls_which_pixels_count_as_opaque() -> None:
    """A pixel is ink (part of some color region) when its alpha is above
    the threshold: a uniformly half-opaque square is traced under a low
    threshold and left with nothing to quantize under a threshold above its
    alpha."""
    half_opaque = [[(*RED[:3], 100) for _ in range(8)] for _ in range(8)]
    source_bytes = _source_bytes(half_opaque)

    result = generate(source_bytes, {"alpha_threshold": 50})
    assert _paths(result.output_bytes)

    with pytest.raises(ValueError, match="no opaque pixels"):
        generate(source_bytes, {"alpha_threshold": 150})


def test_speckle_size_discards_a_color_regions_small_subpath() -> None:
    """A detached, 4-pixel red speck next to the main red square is
    discarded once ``speckle_size`` is raised above its area -- the same
    ``turdsize`` behaviour ``silhouette_svg`` already relies on, applied per
    color here."""
    grid = [[TRANSPARENT for _ in range(SIZE)] for _ in range(SIZE)]
    for y in range(2, 8):
        for x in range(2, 8):
            grid[y][x] = RED
    speck_cells = {(12, 2), (13, 2), (12, 3), (13, 3)}
    for x, y in speck_cells:
        grid[y][x] = RED
    source_bytes = _source_bytes(grid)

    kept = generate(source_bytes, {"speckle_size": 2})
    kept_red_d = next(d for fill, d in _paths(kept.output_bytes) if fill == "#dc1414")
    assert kept_red_d.count("M") == 2  # the main square plus the speck

    discarded = generate(source_bytes, {"speckle_size": 5})
    discarded_red_d = next(d for fill, d in _paths(discarded.output_bytes) if fill == "#dc1414")
    assert discarded_red_d.count("M") == 1  # only the main square


def test_curve_tolerance_changes_the_traced_geometry() -> None:
    """A much looser curve-fitting tolerance changes the emitted path data
    -- proof the parameter reaches the tracer, independent of
    ``domain.recipe``'s identity-hash wiring (tested separately). Uses round
    disks, not the squares above: a square's boundary is already straight
    lines regardless of tolerance, so it cannot exercise curve fitting at
    all."""
    source_bytes = _concentric_disks_bytes()

    tight = generate(source_bytes, {"curve_tolerance": 0.05})
    loose = generate(source_bytes, {"curve_tolerance": 5.0})

    assert tight.output_bytes != loose.output_bytes


def test_defaults_are_used_when_parameters_is_empty() -> None:
    """Every other test in this file calls ``generate`` with ``{}`` and
    already exercises this; asserted explicitly once so the fallback
    defaults themselves are the thing under test."""
    result = generate(_two_squares_bytes(), {})

    assert _paths(result.output_bytes)


def test_a_large_image_with_few_colors_quantizes_quickly_and_correctly() -> None:
    """Review fix round 1, issue #25: quantization must scale with the
    number of *distinct* ink colors, not the number of ink pixels. A
    per-pixel ``(N, P)`` distance array would be ~384 MB just for this
    image's 1,000,000 ink pixels at the recipe's default 16-color cap (and
    ~6 GB for a realistic 4000x4000 source) -- this stays fast because the
    distance array this module actually builds is sized to the 3 *distinct*
    colors here, not the pixel count."""
    import numpy as np

    size = 1000
    array = np.zeros((size, size, 4), dtype=np.uint8)
    array[:, : size // 3, :] = (*RED[:3], 255)
    array[:, size // 3 : 2 * size // 3, :] = (*GREEN[:3], 255)
    array[:, 2 * size // 3 :, :] = (*BLUE[:3], 255)
    buffer = BytesIO()
    Image.fromarray(array, mode="RGBA").save(buffer, format="PNG")
    source_bytes = buffer.getvalue()

    result = generate(source_bytes, {})

    fills = {fill for fill, _d in _paths(result.output_bytes)}
    assert fills == {"#dc1414", "#14a014", "#1414dc"}


def test_raises_for_a_fully_transparent_source() -> None:
    """No opaque pixels at all leaves nothing to quantize -- the generator
    raises rather than emitting an empty document (``generate_asset``
    reports this as ``failed``, not ``impossible``: a source was selected,
    it just had nothing usable in it)."""
    source_bytes = _source_bytes([[TRANSPARENT for _ in range(8)] for _ in range(8)])

    with pytest.raises(ValueError, match="no opaque pixels"):
        generate(source_bytes, {})
