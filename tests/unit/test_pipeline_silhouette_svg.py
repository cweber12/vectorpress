"""pipeline.silhouette_svg: the solid silhouette SVG generator (§6.2, §8,
issue #24).

Builds its own tiny source PNGs with Pillow, in memory, rather than reading
the fixture catalog: this module's job is the generator's tracing and
cleaning behaviour, not catalog wiring
(``tests/integration/test_generate.py`` exercises that end to end). No
filesystem is touched anywhere in this file -- the generator takes bytes,
not a path (ADR 0006).

The three shapes mirror ``tests/fixtures/catalog/generate_source_pngs.py``'s
fixture silhouettes exactly (same centers and radii) so these unit-level
assertions and the fixture-catalog snapshots describe the same geometry.
"""

import re
from io import BytesIO

from PIL import Image

from vectorpress.pipeline.silhouette_svg import generate

Rgba = tuple[int, int, int, int]

TRANSPARENT: Rgba = (0, 0, 0, 0)
OPAQUE: Rgba = (196, 93, 38, 255)

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


def _blob_bytes(size: int = SIZE, cx: float = 7.5, cy: float = 7.5, radius: float = 5.5) -> bytes:
    grid = [
        [OPAQUE if (x - cx) ** 2 + (y - cy) ** 2 <= radius**2 else TRANSPARENT for x in range(size)]
        for y in range(size)
    ]
    return _source_bytes(grid)


def _ring_bytes(
    size: int = SIZE, cx: float = 7.5, cy: float = 7.5, outer: float = 6.5, inner: float = 3.0
) -> bytes:
    grid: list[list[Rgba]] = []
    for y in range(size):
        row: list[Rgba] = []
        for x in range(size):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            row.append(OPAQUE if inner**2 <= d2 <= outer**2 else TRANSPARENT)
        grid.append(row)
    return _source_bytes(grid)


def _blob_with_island_bytes(size: int = SIZE) -> bytes:
    def blob(cx: float, cy: float, radius: float) -> list[list[bool]]:
        return [
            [(x - cx) ** 2 + (y - cy) ** 2 <= radius**2 for x in range(size)] for y in range(size)
        ]

    main = blob(5.5, 5.5, 3.6)
    island_cells = {(12, 2), (13, 2), (12, 3), (13, 3)}
    grid = [
        [OPAQUE if main[y][x] or (x, y) in island_cells else TRANSPARENT for x in range(size)]
        for y in range(size)
    ]
    return _source_bytes(grid)


# --- SVG parsing helpers (test-only: verify the geometry potrace/our own ------------
# renderer produced, not a general-purpose SVG engine) -----------------------------


def _path_d(svg_bytes: bytes) -> str:
    match = re.search(r'\sd="([^"]*)"', svg_bytes.decode("utf-8"))
    assert match is not None, "no path d attribute found"
    return match.group(1)


def _view_box(svg_bytes: bytes) -> tuple[float, float, float, float]:
    match = re.search(r'viewBox="([^"]*)"', svg_bytes.decode("utf-8"))
    assert match is not None, "no viewBox attribute found"
    min_x, min_y, width, height = (float(n) for n in match.group(1).split())
    return min_x, min_y, width, height


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


_COMMAND_RE = re.compile(r"([MLCZ])([^MLCZ]*)")


def _parse_polygons(path_d: str) -> list[list[tuple[float, float]]]:
    """Flatten a ``d`` string of only ``M``/``L``/``C``/``Z`` absolute
    commands (what :mod:`vectorpress.pipeline.svg_document` ever writes)
    into one polygon per subpath, Bézier curves sampled into line segments,
    for point-in-fill testing below."""
    polygons: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    pos = (0.0, 0.0)
    for command, arg_text in _COMMAND_RE.findall(path_d):
        numbers = [float(n) for n in re.split(r"[,\s]+", arg_text.strip()) if n]
        if command == "M":
            if current:
                polygons.append(current)
            pos = (numbers[0], numbers[1])
            current = [pos]
        elif command == "L":
            pos = (numbers[0], numbers[1])
            current.append(pos)
        elif command == "C":
            p1, p2, p3 = (
                (numbers[0], numbers[1]),
                (numbers[2], numbers[3]),
                (numbers[4], numbers[5]),
            )
            current.extend(_flatten_cubic(pos, p1, p2, p3))
            pos = p3
        elif command == "Z":
            pass
    if current:
        polygons.append(current)
    return polygons


def _is_filled(polygons: list[list[tuple[float, float]]], point: tuple[float, float]) -> bool:
    """Even-odd fill-rule point membership, ray-casting a horizontal ray
    from ``point`` and counting crossings across every subpath combined --
    exactly how SVG's ``fill-rule="evenodd"`` decides fill (matches
    :func:`vectorpress.pipeline.svg_document.render_svg`'s own choice)."""
    px, py = point
    crossings = 0
    for polygon in polygons:
        n = len(polygon)
        for i in range(n):
            x1, y1 = polygon[i]
            x2, y2 = polygon[(i + 1) % n]
            if (y1 > py) != (y2 > py):
                x_at_y = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
                if x_at_y > px:
                    crossings += 1
    return crossings % 2 == 1


# --- shape structure (acceptance criterion 2, 3's subpath counts) -----------------


def test_blob_traces_to_one_subpath() -> None:
    result = generate(_blob_bytes(), {})

    polygons = _parse_polygons(_path_d(result.output_bytes))
    assert len(polygons) == 1


def test_ring_traces_to_two_subpaths_an_outer_and_a_hole() -> None:
    result = generate(_ring_bytes(), {})

    polygons = _parse_polygons(_path_d(result.output_bytes))
    assert len(polygons) == 2


def test_ring_fill_rule_and_winding_make_the_inner_subpath_a_hole() -> None:
    """Acceptance criterion 2: a point at the ring's own center (inside the
    hole) is not filled; a point in the solid band is."""
    result = generate(_ring_bytes(), {})

    polygons = _parse_polygons(_path_d(result.output_bytes))
    assert _is_filled(polygons, (7.5, 7.5)) is False  # the hole's center
    assert _is_filled(polygons, (7.5, 3.0)) is True  # the solid annulus band


def test_blob_with_detached_island_traces_to_two_disjoint_subpaths() -> None:
    result = generate(_blob_with_island_bytes(), {})

    polygons = _parse_polygons(_path_d(result.output_bytes))
    assert len(polygons) == 2
    # both subpaths are filled, independently -- neither is a hole in the other.
    main_center = (5.5, 5.5)
    island_center = (12.5, 2.5)
    assert _is_filled(polygons, main_center) is True
    assert _is_filled(polygons, island_center) is True


# --- §8: true vector, clean bounds, nothing but the artwork ------------------------


def test_output_has_no_image_element_or_raster_data() -> None:
    result = generate(_blob_bytes(), {})

    text = result.output_bytes.decode("utf-8")
    assert "<image" not in text
    assert "data:image" not in text


def test_output_is_one_filled_black_path_with_no_stroke() -> None:
    result = generate(_blob_bytes(), {})

    text = result.output_bytes.decode("utf-8")
    assert text.count("<path") == 1
    assert 'fill="#000000"' in text
    assert 'stroke="none"' in text


def test_output_has_no_groups_metadata_comments_or_editor_namespaces() -> None:
    result = generate(_blob_bytes(), {})

    text = result.output_bytes.decode("utf-8")
    assert "<g" not in text
    assert "<metadata" not in text
    assert "<!--" not in text
    assert "inkscape" not in text.lower()
    assert "illustrator" not in text.lower()


def test_view_box_is_tight_to_the_geometry_not_the_full_source_canvas() -> None:
    """The blob is inset within its 16x16 source canvas (§8: "use clean
    document bounds") -- the viewBox must be smaller than the source, not
    equal to it."""
    result = generate(_blob_bytes(), {})

    _min_x, _min_y, width, height = _view_box(result.output_bytes)
    assert width < SIZE
    assert height < SIZE


def test_nothing_is_outside_the_view_box() -> None:
    result = generate(_blob_bytes(), {})

    min_x, min_y, width, height = _view_box(result.output_bytes)
    max_x, max_y = min_x + width, min_y + height
    for polygon in _parse_polygons(_path_d(result.output_bytes)):
        for x, y in polygon:
            assert min_x - 1e-6 <= x <= max_x + 1e-6
            assert min_y - 1e-6 <= y <= max_y + 1e-6


def test_width_and_height_match_the_view_box_so_proportions_hold() -> None:
    result = generate(_blob_bytes(), {})

    text = result.output_bytes.decode("utf-8")
    _min_x, _min_y, vb_width, vb_height = _view_box(result.output_bytes)
    width_match = re.search(r'\swidth="([^"]*)"', text)
    height_match = re.search(r'\sheight="([^"]*)"', text)
    assert width_match is not None
    assert height_match is not None
    assert float(width_match.group(1)) == vb_width
    assert float(height_match.group(1)) == vb_height


# --- determinism (§36) --------------------------------------------------------------


def test_generation_is_byte_deterministic() -> None:
    source_bytes = _ring_bytes()

    first = generate(source_bytes, {})
    second = generate(source_bytes, {})

    assert first.output_bytes == second.output_bytes


def test_reports_the_potracer_and_numpy_versions_it_used() -> None:
    import importlib.metadata

    import numpy as np

    result = generate(_blob_bytes(), {})

    assert result.library_versions == {
        "potracer": importlib.metadata.version("potracer"),
        "numpy": np.__version__,
    }


# --- tracing parameters (issue #24: alpha threshold, curve tolerance, speckle size) --


def test_alpha_threshold_controls_which_pixels_count_as_ink() -> None:
    """A pixel is ink when its alpha is above the threshold: a uniformly
    half-opaque square is fully traced under a low threshold and produces
    no visible geometry at all under a threshold above its alpha."""
    half_opaque = [[(*OPAQUE[:3], 100) for _ in range(8)] for _ in range(8)]
    source_bytes = _source_bytes(half_opaque)

    result = generate(source_bytes, {"alpha_threshold": 50})
    assert _parse_polygons(_path_d(result.output_bytes))

    try:
        generate(source_bytes, {"alpha_threshold": 150})
    except ValueError:
        pass
    else:
        raise AssertionError("expected no ink above an alpha threshold higher than every pixel")


def test_speckle_size_discards_small_subpaths() -> None:
    """The detached island (pixel area 4) survives the recipe's default
    ``speckle_size`` (2) as its own subpath, but is discarded as a speckle
    once ``speckle_size`` is raised above its area."""
    source_bytes = _blob_with_island_bytes()

    kept = generate(source_bytes, {"speckle_size": 2})
    assert len(_parse_polygons(_path_d(kept.output_bytes))) == 2

    discarded = generate(source_bytes, {"speckle_size": 5})
    assert len(_parse_polygons(_path_d(discarded.output_bytes))) == 1


def test_curve_tolerance_changes_the_traced_geometry() -> None:
    """A much looser curve-fitting tolerance changes the emitted path data
    -- proof the parameter actually reaches the tracer, independent of
    ``domain.recipe``'s identity-hash wiring (tested separately)."""
    source_bytes = _blob_bytes()

    tight = generate(source_bytes, {"curve_tolerance": 0.05})
    loose = generate(source_bytes, {"curve_tolerance": 5.0})

    assert tight.output_bytes != loose.output_bytes


def test_defaults_are_used_when_parameters_is_empty() -> None:
    """Every other test in this file calls ``generate`` with ``{}`` and
    already exercises this; asserted explicitly once so the fallback
    defaults themselves are the thing under test."""
    result = generate(_blob_bytes(), {})

    assert _parse_polygons(_path_d(result.output_bytes))
