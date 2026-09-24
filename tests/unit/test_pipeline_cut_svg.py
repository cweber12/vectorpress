"""pipeline.cut_svg: the cut-file SVG generator (§6.3, §8, §9.1, ADR 0007,
issue #36).

Builds its own tiny source PNGs with Pillow, in memory, rather than reading
the fixture catalog: this module's job is the generator's physical-unit
cleanup and tracing behaviour, not catalog wiring
(``tests/integration/test_generate.py`` exercises that end to end, and reads
the real ``owl_limpet`` fixture -- ``tests/fixtures/catalog/generate_source_pngs.py``
-- to prove the same cleanup against a purpose-built subject). No filesystem
is touched anywhere in this file -- the generator takes bytes, not a path
(ADR 0006).

Most cleanup tests hold ``reference_size_in`` fixed and vary a threshold
between a value near zero (nothing gets cleaned) and a value certain to
exceed any feature in the fixture (everything below the main body gets
cleaned) -- proving each parameter controls the outcome without depending on
exact pixels-per-inch arithmetic, the same style
``pipeline.silhouette_svg``'s own ``test_speckle_size_discards_small_subpaths``
uses for its one cleanup parameter.
"""

import re
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from vectorpress.pipeline.cut_svg import generate
from vectorpress.pipeline.silhouette_svg import generate as generate_silhouette

Rgba = tuple[int, int, int, int]

TRANSPARENT: Rgba = (0, 0, 0, 0)
OPAQUE: Rgba = (110, 90, 60, 255)

SIZE = 32


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


def _blob(size: int, cx: float, cy: float, radius: float) -> list[list[bool]]:
    return [[(x - cx) ** 2 + (y - cy) ** 2 <= radius**2 for x in range(size)] for y in range(size)]


def _blob_bytes(size: int = SIZE, cx: float = 16, cy: float = 16, radius: float = 12) -> bytes:
    mask = _blob(size, cx, cy, radius)
    grid = [[OPAQUE if mask[y][x] else TRANSPARENT for x in range(size)] for y in range(size)]
    return _source_bytes(grid)


def _blob_with_small_island_bytes(size: int = SIZE) -> bytes:
    """A main blob plus a small (2x2, 4px^2) island, isolated far from it --
    small enough that a large-enough ``island_min_area_in2`` drops it, and a
    near-zero one keeps it."""
    main = _blob(size, cx=10, cy=16, radius=8)
    island_cells = {(27, 3), (28, 3), (27, 4), (28, 4)}
    grid = [
        [OPAQUE if main[y][x] or (x, y) in island_cells else TRANSPARENT for x in range(size)]
        for y in range(size)
    ]
    return _source_bytes(grid)


def _blob_with_pinhole_bytes(size: int = SIZE) -> bytes:
    """A main blob with a small (2x2, 4px^2) hole carved from its own
    interior -- far from the boundary, so it never merges with the
    exterior background."""
    main = _blob(size, cx=16, cy=16, radius=12)
    pinhole_cells = {(15, 15), (16, 15), (15, 16), (16, 16)}
    grid = [
        [OPAQUE if main[y][x] and (x, y) not in pinhole_cells else TRANSPARENT for x in range(size)]
        for y in range(size)
    ]
    return _source_bytes(grid)


def _blob_with_spur_bytes(size: int = SIZE) -> bytes:
    """A main blob with a 1px-tall, 6px-long hairline spur off its right
    edge -- narrower than any opening width that also leaves the (far
    wider) main body intact."""
    main = _blob(size, cx=12, cy=16, radius=9)
    spur_cells = {(x, 16) for x in range(21, 27)}
    grid = [
        [OPAQUE if main[y][x] or (x, y) in spur_cells else TRANSPARENT for x in range(size)]
        for y in range(size)
    ]
    return _source_bytes(grid)


def _two_separate_blobs_bytes(size: int = SIZE) -> bytes:
    """Two same-size, far-apart blobs, both comfortably above any island
    threshold used below -- neither is noise, so cleanup must leave both,
    never bridged into one (ADR 0007)."""
    left = _blob(size, cx=8, cy=16, radius=6)
    right = _blob(size, cx=24, cy=16, radius=6)
    grid = [
        [OPAQUE if left[y][x] or right[y][x] else TRANSPARENT for x in range(size)]
        for y in range(size)
    ]
    return _source_bytes(grid)


# --- SVG parsing helpers (test-only: verify the geometry potrace/our own ------------
# renderer and cleanup pass produced, not a general-purpose SVG engine) ------------


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


def _parse_polygons(path_d: str, *, curve_steps: int = 24) -> list[list[tuple[float, float]]]:
    """Flatten a ``d`` string of only ``M``/``L``/``C``/``Z`` absolute
    commands (what :mod:`vectorpress.pipeline.svg_document` ever writes)
    into one polygon per subpath, Bézier curves sampled into line
    segments."""
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
            current.extend(_flatten_cubic(pos, p1, p2, p3, steps=curve_steps))
            pos = p3
        elif command == "Z":
            pass
    if current:
        polygons.append(current)
    return polygons


def _is_filled(polygons: list[list[tuple[float, float]]], point: tuple[float, float]) -> bool:
    """Even-odd fill-rule point membership, matching
    :func:`vectorpress.pipeline.svg_document.render_svg`'s own choice."""
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
    result = generate(_blob_bytes(), {})

    _min_x, _min_y, width, height = _view_box(result.output_bytes)
    assert width < SIZE
    assert height < SIZE


def test_view_box_matches_the_curve_geometry_not_its_control_points() -> None:
    result = generate(_blob_bytes(), {})

    min_x, min_y, width, height = _view_box(result.output_bytes)
    max_x, max_y = min_x + width, min_y + height

    sampled_points = [
        point
        for polygon in _parse_polygons(_path_d(result.output_bytes), curve_steps=2000)
        for point in polygon
    ]
    sampled_xs = [x for x, _y in sampled_points]
    sampled_ys = [y for _x, y in sampled_points]

    tolerance = 1e-4
    assert min(sampled_xs) == pytest.approx(min_x, abs=tolerance)
    assert max(sampled_xs) == pytest.approx(max_x, abs=tolerance)
    assert min(sampled_ys) == pytest.approx(min_y, abs=tolerance)
    assert max(sampled_ys) == pytest.approx(max_y, abs=tolerance)


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
    source_bytes = _blob_with_small_island_bytes()

    first = generate(source_bytes, {})
    second = generate(source_bytes, {})

    assert first.output_bytes == second.output_bytes


def test_reports_the_potracer_numpy_and_scipy_versions_it_used() -> None:
    import importlib.metadata

    import numpy as np

    result = generate(_blob_bytes(), {})

    assert result.library_versions == {
        "potracer": importlib.metadata.version("potracer"),
        "numpy": np.__version__,
        "scipy": importlib.metadata.version("scipy"),
    }


def test_defaults_are_used_when_parameters_is_empty() -> None:
    result = generate(_blob_bytes(), {})

    assert _parse_polygons(_path_d(result.output_bytes))


# --- island removal (ADR 0007, §9.1) ------------------------------------------------


def test_small_island_below_the_area_threshold_is_removed() -> None:
    source_bytes = _blob_with_small_island_bytes()

    kept = generate(source_bytes, {"island_min_area_in2": 1e-9})
    assert len(_parse_polygons(_path_d(kept.output_bytes))) == 2

    # Comfortably above the island's own area but well below the main
    # body's -- removes only the island, never the whole shape.
    removed = generate(source_bytes, {"island_min_area_in2": 0.5})
    assert len(_parse_polygons(_path_d(removed.output_bytes))) == 1


def test_two_separate_qualifying_pieces_are_never_bridged_into_one() -> None:
    """ADR 0007: "no automatic bridging or joining" -- two pieces both well
    above the island threshold stay two separate subpaths, whatever the
    threshold, and both remain independently filled."""
    source_bytes = _two_separate_blobs_bytes()

    result = generate(source_bytes, {"island_min_area_in2": 1e-9})

    polygons = _parse_polygons(_path_d(result.output_bytes))
    assert len(polygons) == 2
    assert _is_filled(polygons, (8, 16)) is True
    assert _is_filled(polygons, (24, 16)) is True
    # the gap between them is genuinely background, not accidentally bridged.
    assert _is_filled(polygons, (16, 16)) is False


# --- hole filling (ADR 0007, §9.1) --------------------------------------------------


def test_small_pinhole_below_the_area_threshold_is_filled() -> None:
    source_bytes = _blob_with_pinhole_bytes()

    kept_open = generate(source_bytes, {"hole_min_area_in2": 1e-9})
    polygons_open = _parse_polygons(_path_d(kept_open.output_bytes))
    assert len(polygons_open) == 2  # outer boundary plus the pinhole's own subpath
    assert _is_filled(polygons_open, (15.5, 15.5)) is False  # the pinhole itself

    filled = generate(source_bytes, {"hole_min_area_in2": 100.0})
    polygons_filled = _parse_polygons(_path_d(filled.output_bytes))
    assert len(polygons_filled) == 1  # no more hole subpath
    assert _is_filled(polygons_filled, (15.5, 15.5)) is True


# --- morphological opening (ADR 0007, §9.1) -----------------------------------------


def test_hairline_spur_narrower_than_the_opening_width_is_erased() -> None:
    """The spur (1px tall) disappears under a wide-enough opening, while the
    far-wider main body still traces to a single, still-filled subpath --
    the opening does not erase real geometry, only what is narrower than
    it."""
    source_bytes = _blob_with_spur_bytes()
    # y=16.5, not the pixel-row-center y=16, to land inside the spur's
    # traced extent rather than exactly on a polygon edge (an ambiguous
    # ray-cast case for the point-in-fill helper below, not a real
    # boundary question).
    spur_tip = (24, 16.5)

    with_spur = generate(source_bytes, {"opening_width_in": 1e-9})
    assert _is_filled(_parse_polygons(_path_d(with_spur.output_bytes)), spur_tip) is True

    # Comfortably wider than the spur's own thickness but far narrower than
    # the main body's -- an opening this size erases only the spur.
    without_spur = generate(source_bytes, {"opening_width_in": 0.75})
    polygons = _parse_polygons(_path_d(without_spur.output_bytes))
    assert len(polygons) == 1
    assert _is_filled(polygons, (12, 16)) is True  # the main body itself survives
    assert _is_filled(polygons, spur_tip) is False  # the spur's own tip is gone


# --- reference size (§9.1, issue #36) -----------------------------------------------


def test_reference_size_in_scales_which_features_count_as_noise() -> None:
    """The same fixed-area threshold reads as more or fewer pixels depending
    on ``reference_size_in`` (§9.1: "the reference size used should be
    recorded with the validation result" implies thresholds are meaningless
    without it) -- a small reference size (the same pixels packed into fewer
    physical inches) raises pixels-per-inch, so a fixed physical threshold
    converts to *more* pixels and removes the island; a large reference size
    lowers pixels-per-inch enough that the same threshold converts to fewer
    pixels than the island's own area, so it survives."""
    source_bytes = _blob_with_small_island_bytes()
    parameters = {"island_min_area_in2": 0.05}

    removed = generate(source_bytes, {**parameters, "reference_size_in": 1.0})
    assert len(_parse_polygons(_path_d(removed.output_bytes))) == 1

    kept = generate(source_bytes, {**parameters, "reference_size_in": 20.0})
    assert len(_parse_polygons(_path_d(kept.output_bytes))) == 2


# --- other parameters (alpha threshold, curve tolerance) ---------------------------


def test_alpha_threshold_controls_which_pixels_count_as_ink() -> None:
    half_opaque = [[(*OPAQUE[:3], 100) for _ in range(8)] for _ in range(8)]
    source_bytes = _source_bytes(half_opaque)

    result = generate(source_bytes, {"alpha_threshold": 50})
    assert _parse_polygons(_path_d(result.output_bytes))

    with pytest.raises(ValueError):
        generate(source_bytes, {"alpha_threshold": 150})


def test_curve_tolerance_changes_the_traced_geometry() -> None:
    source_bytes = _blob_bytes()

    tight = generate(source_bytes, {"curve_tolerance": 0.05})
    loose = generate(source_bytes, {"curve_tolerance": 5.0})

    assert tight.output_bytes != loose.output_bytes


# --- the real owl_limpet fixture (issue #36 acceptance criterion 3) ---------------

_OWL_LIMPET_SILHOUETTE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "catalog"
    / "assets"
    / "owl_limpet"
    / "sources"
    / "silhouette.png"
)


def test_owl_limpet_cleanup_removes_the_speck_pinhole_and_spur_but_not_silhouette_svg() -> None:
    """Acceptance criterion 3: against the real fixture source (see
    ``tests/fixtures/catalog/generate_source_pngs.py``'s
    ``_owl_limpet_silhouette_with_cleanup_noise``), the speck, pinhole and
    spur are all gone from the cut SVG at the recipe's default parameters
    and the catalog's default 3-inch reference size, but every one of them
    is present in ``silhouette_svg`` (no cleanup at all) built from the same
    source -- proof the cleanup, not some quirk of the source itself, is
    what removes them."""
    source_bytes = _OWL_LIMPET_SILHOUETTE.read_bytes()

    cut_polygons = _parse_polygons(_path_d(generate(source_bytes, {}).output_bytes))
    silhouette_polygons = _parse_polygons(
        _path_d(generate_silhouette(source_bytes, {}).output_bytes)
    )

    speck_point = (70.5, 20.5)
    pinhole_point = (33.5, 47.5)
    # y=48.5, not the pixel-row-center y=48, for the same ambiguous-edge
    # reason ``test_hairline_spur_narrower_than_the_opening_width_is_erased``
    # above avoids the exact row center.
    spur_point = (70, 48.5)

    assert _is_filled(cut_polygons, speck_point) is False
    assert _is_filled(silhouette_polygons, speck_point) is True

    assert _is_filled(cut_polygons, pinhole_point) is True  # filled in, no longer a hole
    assert _is_filled(silhouette_polygons, pinhole_point) is False  # still a real hole

    assert _is_filled(cut_polygons, spur_point) is False
    assert _is_filled(silhouette_polygons, spur_point) is True


def test_owl_limpet_detached_piece_survives_as_its_own_subpath_never_bridged() -> None:
    """Acceptance criterion 3, second half: the detached piece (well above
    the island threshold) survives cleanup as its own separate subpath --
    exactly two subpaths (the cleaned main body and the piece), neither
    merged into the other (ADR 0007's "no automatic bridging or
    joining")."""
    source_bytes = _OWL_LIMPET_SILHOUETTE.read_bytes()

    result = generate(source_bytes, {})
    polygons = _parse_polygons(_path_d(result.output_bytes))

    assert len(polygons) == 2
    main_body_point = (15, 48)
    detached_piece_point = (84, 48)
    assert _is_filled(polygons, main_body_point) is True
    assert _is_filled(polygons, detached_piece_point) is True
    # the gap between the main body (right edge ~67, spur removed) and the
    # piece (left edge ~75) is genuine background, never bridged.
    assert _is_filled(polygons, (71, 48.5)) is False


def test_no_ink_at_all_raises() -> None:
    """Mirrors ``silhouette_svg``'s own failure for a fully transparent
    source (PRD 02 ruling: a raising generator is reported ``failed``,
    never ``impossible``, by ``pipeline.generate``)."""
    empty = _source_bytes([[TRANSPARENT] * 8 for _ in range(8)])

    with pytest.raises(ValueError):
        generate(empty, {})
