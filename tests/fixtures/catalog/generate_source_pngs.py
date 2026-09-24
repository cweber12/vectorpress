"""Generate the fixture catalog's tiny source PNGs and its brand mark.

Committed alongside the PNGs it writes (issue #4, issue #3, issue #23) so
they can be regenerated deterministically without a new dependency: stdlib
``zlib`` and ``struct`` are enough to write a valid, tiny, uncompressed-per-row
PNG. Run it from the repo root with:

    uv run python tests/fixtures/catalog/generate_source_pngs.py

This script is a fixture author's tool; vectorpress itself never writes
under an asset's ``sources/`` directory (ADR 0003, ADR 0007, §21), and
never writes the brand mark either (ADR 0005: hand-authored, tool-read-only).

Each ``silhouette.png`` is a real shape on a transparent background rather
than a solid-color square (issue #23): the transparent PNG generator's crop
and hole-preserving behaviour needs actual content to crop and actual holes
to preserve, which a single solid color cannot exercise.

``ochre_sea_star`` also gets a ``flatcolor.png`` (issue #25): three
concentric rings plus a small detached island, four flat, distinct colors on
a transparent background, with the innermost ring fully enclosed by the one
around it -- exactly what ``flatcolor_svg``'s quantize-then-trace-per-color
generator needs to exercise both nesting (a hole in one color's region where
another color's region sits) and a disjoint extra region.

Four more subjects (issue #39, §9, §9.1) each carry exactly one area-based
finding kind: ``gumboot_chiton`` (an accidental dot), ``bat_star`` (a tiny
isolated shape -- a thin sliver), ``keyhole_limpet`` (a very small hole), and
``turban_snail`` (a hole sized to pass at the catalog's default 3in
reference size but need review at a smaller product override -- §9.1's own
point that a threshold is only meaningful at a known output size). Every one
of these gets its own larger canvas, the same reasoning as ``owl_limpet``'s
below: a feature a handful of pixels across needs real room to place
precisely relative to both ``cut_svg``'s cleanup thresholds and
``validate.cut_file``'s own validation thresholds.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

FIXTURE_CATALOG_ROOT = Path(__file__).parent
FIXTURE_ASSETS_DIR = FIXTURE_CATALOG_ROOT / "assets"

SIZE = 16  # pixels; square, tiny on purpose (CLAUDE.md, fixture README)

Rgba = tuple[int, int, int, int]
Grid = list[list[bool]]

TRANSPARENT: Rgba = (0, 0, 0, 0)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def _encode_png(size: int, pixels: list[list[Rgba]]) -> bytes:
    """A minimal valid PNG: 8-bit RGBA, no filtering, no interlace, from a
    row-major grid of ``(r, g, b, a)`` pixels."""
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    raw = b"".join(
        b"\x00" + b"".join(bytes(px) for px in row) for row in pixels
    )  # filter type: None
    idat = zlib.compress(raw, level=9)
    return (
        b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    )


def make_png(size: int, rgba: Rgba) -> bytes:
    """A solid-color PNG (the brand mark and the lineart placeholder don't
    need a shape)."""
    return _encode_png(size, [[rgba] * size for _ in range(size)])


def make_shaped_png(size: int, mask: Grid, rgba: Rgba) -> bytes:
    """A PNG from a boolean mask: ``rgba`` where ``mask`` is ``True``,
    fully transparent elsewhere."""
    return _encode_png(
        size, [[rgba if mask[y][x] else TRANSPARENT for x in range(size)] for y in range(size)]
    )


def _solid_blob(size: int, *, cx: float, cy: float, radius: float) -> Grid:
    """A filled circle -- the solid silhouette shape (§6.2)."""
    return [[(x - cx) ** 2 + (y - cy) ** 2 <= radius**2 for x in range(size)] for y in range(size)]


def _ring(size: int, *, cx: float, cy: float, outer: float, inner: float) -> Grid:
    """A filled annulus -- a shape with a hole, to prove a crop preserves
    interior transparency instead of re-filling it."""
    grid: Grid = []
    for y in range(size):
        row: list[bool] = []
        for x in range(size):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            row.append(inner**2 <= d2 <= outer**2)
        grid.append(row)
    return grid


def _blob_with_detached_island(size: int) -> Grid:
    """A main blob plus a small, separate island with fully transparent
    pixels between them -- the tight bounding box must span both."""
    main = _solid_blob(size, cx=5.5, cy=5.5, radius=3.6)
    island_cells = {(12, 2), (13, 2), (12, 3), (13, 3)}
    return [[main[y][x] or (x, y) in island_cells for x in range(size)] for y in range(size)]


def _flatcolor_rings_with_island(
    size: int,
    *,
    cx: float,
    cy: float,
    ring_colors: list[tuple[float, Rgba]],
    island_cells: set[tuple[int, int]],
    island_color: Rgba,
) -> list[list[Rgba]]:
    """Concentric flat-color rings (issue #25's flatcolor fixture source):
    ``ring_colors`` is ``[(outer_radius, color), ...]`` from the outermost
    ring inward, each pixel colored by the first (smallest) radius it falls
    within -- so the innermost entry is a solid disk fully enclosed by every
    ring around it -- plus a small detached ``island_color`` region, all on
    a transparent background."""
    pixels: list[list[Rgba]] = []
    for y in range(size):
        row: list[Rgba] = []
        for x in range(size):
            if (x, y) in island_cells:
                row.append(island_color)
                continue
            distance = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
            pixel = TRANSPARENT
            for radius, color in ring_colors:
                if distance <= radius:
                    pixel = color
            row.append(pixel)
        pixels.append(row)
    return pixels


# (asset ID, filename under its sources/, role, mask factory, RGBA fill color).
# ochre_sea_star gets two roles (silhouette + lineart) to exercise an
# asset with several sources (issue #4 acceptance criteria); lineart stays a
# plain placeholder square since transparent_png never selects it (the
# silhouette role is preferred, issue #22).
SHAPED_SOURCE_IMAGES: list[tuple[str, str, str, Grid, Rgba]] = [
    (
        "ochre_sea_star",
        "silhouette.png",
        "silhouette",
        _solid_blob(SIZE, cx=7.5, cy=7.5, radius=5.5),
        (196, 93, 38, 255),
    ),
    (
        "purple_sea_urchin",
        "silhouette.png",
        "silhouette",
        _ring(SIZE, cx=7.5, cy=7.5, outer=6.5, inner=3.0),
        (91, 46, 130, 255),
    ),
    (
        "giant_green_anemone",
        "silhouette.png",
        "silhouette",
        _blob_with_detached_island(SIZE),
        (58, 140, 92, 255),
    ),
]

# (asset ID, filename, role, RGBA fill color): plain solid-color sources that
# don't need a shape.
SOLID_SOURCE_IMAGES: list[tuple[str, str, str, Rgba]] = [
    ("ochre_sea_star", "lineart.png", "lineart", (20, 20, 20, 255)),
]

# (asset ID, filename, role, pre-colored pixel grid): sources with more than
# one flat color, so a single mask + fill color (SHAPED_SOURCE_IMAGES' shape)
# cannot express them. ochre_sea_star's flatcolor.png (issue #25) is the only
# one so far; the other two fixture assets deliberately get no flatcolor
# source, so flatcolor_svg stays impossible for them.
MULTI_COLOR_SOURCE_IMAGES: list[tuple[str, str, str, list[list[Rgba]]]] = [
    (
        "ochre_sea_star",
        "flatcolor.png",
        "flatcolor",
        _flatcolor_rings_with_island(
            SIZE,
            cx=7.5,
            cy=7.5,
            ring_colors=[
                (6.5, (196, 93, 38, 255)),  # outer ring: ochre
                (4.5, (230, 210, 170, 255)),  # middle ring: cream
                (2.0, (91, 46, 130, 255)),  # inner disk: purple, fully enclosed
            ],
            island_cells={(12, 2), (13, 2), (12, 3), (13, 3)},
            island_color=(58, 140, 92, 255),  # detached island: green
        ),
    ),
]

# (asset ID, filename, role, mask factory, RGBA fill color, byte offset to
# truncate at): a deliberately broken source (issue #27, §35) -- valid PNG
# signature and IHDR chunk, cut off partway through the (single) IDAT chunk,
# with no IEND. Pillow's ``Image.open`` still succeeds (the header alone is
# enough to identify the format and read its size/mode), but forcing a full
# decode (``.convert("RGBA")``, which both transparent_png and silhouette_svg
# do) raises ``OSError: image file is truncated`` -- a generation failure,
# never a metadata problem, since source validation only checks that the
# declared file exists (README.md). 50 bytes lands inside the IDAT chunk for
# every mask this script can produce at ``SIZE`` 16 (the full PNG is under
# 100 bytes); acorn_barnacle is the only asset with a source built this way.
TRUNCATED_SOURCE_IMAGES: list[tuple[str, str, str, Grid, Rgba, int]] = [
    (
        "acorn_barnacle",
        "silhouette.png",
        "silhouette",
        _solid_blob(SIZE, cx=7.5, cy=7.5, radius=5.5),
        (150, 100, 50, 255),
        50,
    ),
]

# --- owl_limpet: the cut_svg cleanup fixture (issue #36) --------------------------
#
# 16x16 is too coarse for cut_svg's physical thresholds to mean anything (a
# single pixel is already a large fraction of the whole canvas), so this
# subject gets its own larger canvas -- big enough that a "noise" feature
# a few pixels across is convincingly smaller than the catalog's 3-inch
# reference size would make it look, and a "real" detached piece is
# convincingly bigger.
CUT_FILE_FIXTURE_SIZE = 96


def _owl_limpet_silhouette_with_cleanup_noise(size: int) -> Grid:
    """A silhouette carrying exactly one noise feature of each kind
    ``cut_svg``'s deterministic cleanup removes (issue #36 acceptance
    criterion 3), plus one piece large enough to survive -- so a test can
    show the cut file drops the first three while ``silhouette_svg`` (no
    cleanup at all) keeps them, and that the surviving piece stays its own
    disconnected subpath (ADR 0007: "no automatic bridging or joining").

    At this fixture's size, the recipe's default parameters
    (``island_min_area_in2``/``hole_min_area_in2`` 0.01, ``opening_width_in``
    0.06) and the catalog's default 3-inch reference size resolve to
    roughly 31 pixels per inch (the ink mask's own bounding box is 93px on
    its longest side) -- an island/hole threshold of about 9.6px^2 and an
    opening radius of 1px:

    - a main body (a solid disk) big enough to anchor the piece's overall
      bounding box and survive the opening untouched
    - a **speck**: a 2x2 (4px^2) island nowhere near either piece -- below
      the island threshold, so it disappears
    - a **pinhole**: a 2x2 (4px^2) hole carved out of the main body's own
      interior -- below the hole threshold, so it gets filled in
    - a **hairline spur**: a 1px-tall, 7px-long line off the main body's
      edge -- narrower than the opening's width, so it gets erased, while
      the main body itself (far wider than 2px) survives the same opening
      essentially unchanged
    - a **detached piece**: a second, smaller solid disk, positioned so nothing
      above ever touches it -- its own area (over 250px^2) clears the
      island threshold by more than an order of magnitude, so it survives
      as its own separate subpath, never bridged to the main body
    """

    def _blob(cx: float, cy: float, radius: float) -> Grid:
        return [
            [(x - cx) ** 2 + (y - cy) ** 2 <= radius**2 for x in range(size)] for y in range(size)
        ]

    main_body = _blob(cx=34, cy=48, radius=33)
    detached_piece = _blob(cx=84, cy=48, radius=9)

    speck_cells = {(70, 20), (71, 20), (70, 21), (71, 21)}
    pinhole_cells = {(33, 47), (34, 47), (33, 48), (34, 48)}
    # Stops at x=73: the detached piece's own leftmost ink pixel (at y=48)
    # is x=75, so the spur never touches it -- a bridge here would silently
    # turn "two pieces" into "one", defeating the fixture's own point.
    spur_cells = {(x, 48) for x in range(67, 74)}

    grid: Grid = []
    for y in range(size):
        row: list[bool] = []
        for x in range(size):
            ink = main_body[y][x] or detached_piece[y][x]
            if (x, y) in speck_cells or (x, y) in spur_cells:
                ink = True
            if (x, y) in pinhole_cells:
                ink = False
            row.append(ink)
        grid.append(row)
    return grid


# --- gumboot_chiton, bat_star, keyhole_limpet, turban_snail: issue #39's --
# area-finding fixtures -----------------------------------------------------
#
# Every one of these shares the same 300x300 canvas and the same main-body
# disk (radius 130px, centered at (150,150)) -- big enough, relative to each
# subject's own small extra feature, that the feature never changes the ink
# mask's own bounding box (``cut_svg``'s own module docstring: "the two
# bounding boxes coincide in every case this generator is meant for"), so
# every physical-unit measurement below is against a stable ~31px/in --
# actually 260px / 3in =~ 86.67px/in -- pixels-per-inch scale. Geometry was
# tuned empirically against the real ``cut_svg.generate`` +
# ``validate.cut_file.validate_cut_file`` pipeline (not hand-derived), since
# a morphological opening's effect on a shape's surviving extent is not a
# simple, predictable subtraction.
AREA_FINDING_FIXTURE_SIZE = 300
_AREA_FINDING_MAIN_BODY_CENTER = 150.0
_AREA_FINDING_MAIN_BODY_RADIUS = 130.0


def _area_finding_main_body(size: int) -> Grid:
    """The shared main body every fixture below anchors its own extra
    feature to -- always the document's largest piece by a wide margin, so
    it is never itself a dot/tiny-shape/hole candidate (ADR 0007, issue
    #37, issue #39)."""
    return _solid_blob(
        size,
        cx=_AREA_FINDING_MAIN_BODY_CENTER,
        cy=_AREA_FINDING_MAIN_BODY_CENTER,
        radius=_AREA_FINDING_MAIN_BODY_RADIUS,
    )


def _gumboot_chiton_silhouette_with_a_dot(size: int) -> Grid:
    """The main body plus one small, detached circular eye-spot (issue
    #39's own example): 14px across (radius 7, centered at (280,20), far
    outside the main body's own disk despite sharing its bounding square) --
    comfortably above ``cut_svg``'s own island-area cleanup floor (about
    double it, so it survives cleanup as a real piece) yet comfortably under
    ``validate.cut_file``'s accidental-dot dimension threshold (about
    0.15in at the catalog's default 3in reference size, against a 0.2in
    threshold): an accidental dot, and nothing else."""
    main_body = _area_finding_main_body(size)
    dot = _solid_blob(size, cx=280.0, cy=20.0, radius=7.0)
    return [[main_body[y][x] or dot[y][x] for x in range(size)] for y in range(size)]


def _bat_star_silhouette_with_a_sliver(size: int) -> Grid:
    """The main body plus one small, detached rectangle -- a broken-off arm
    tip -- 7px wide (just past the width a morphological opening this
    fixture's ``opening_width_in`` erases entirely, so it survives cleanup
    as a real piece) by 20px long (comfortably over the accidental-dot
    dimension threshold, so it is never mistaken for a dot), with a total
    area comfortably under the tiny-isolated-shape area threshold: a thin
    sliver, and nothing else."""
    main_body = _area_finding_main_body(size)
    sliver_cells = {(x, y) for x in range(250, 270) for y in range(20, 27)}
    return [[main_body[y][x] or (x, y) in sliver_cells for x in range(size)] for y in range(size)]


def _keyhole_limpet_silhouette_with_a_small_hole(size: int) -> Grid:
    """The main body with one small hole cut from its own center: 6px in
    radius -- comfortably above ``cut_svg``'s own hole-area cleanup floor
    (survives cleanup as a real hole) yet comfortably under
    ``validate.cut_file``'s small-hole area threshold at the catalog's
    default 3in reference size: a very small hole, and nothing else."""
    return _ring(
        size,
        cx=_AREA_FINDING_MAIN_BODY_CENTER,
        cy=_AREA_FINDING_MAIN_BODY_CENTER,
        outer=_AREA_FINDING_MAIN_BODY_RADIUS,
        inner=6.0,
    )


def _turban_snail_silhouette_with_a_borderline_hole(size: int) -> Grid:
    """The main body with one hole cut from its own center, 13px in radius
    -- sized so its *physical* area passes at the catalog's default 3in
    reference size (about 0.069in^2, well clear of the 0.02in^2 small-hole
    threshold) but needs review at a smaller product override (about
    0.008in^2 at 1in): §9.1's own point that a threshold is only meaningful
    at a known output size, and the extra acceptance criterion reassigned
    to issue #39 by controller ruling (issue #38's `kelp_forest_mini_pack`
    `reference_size_in` override)."""
    return _ring(
        size,
        cx=_AREA_FINDING_MAIN_BODY_CENTER,
        cy=_AREA_FINDING_MAIN_BODY_CENTER,
        outer=_AREA_FINDING_MAIN_BODY_RADIUS,
        inner=13.0,
    )


# (asset ID, filename, role, canvas size, mask, RGBA fill color): every
# source needing its own, larger canvas -- a distinct tuple shape from
# SHAPED_SOURCE_IMAGES above (which hardcodes the shared 16x16 ``SIZE``).
LARGE_CANVAS_SOURCE_IMAGES: list[tuple[str, str, str, int, Grid, Rgba]] = [
    (
        "owl_limpet",
        "silhouette.png",
        "silhouette",
        CUT_FILE_FIXTURE_SIZE,
        _owl_limpet_silhouette_with_cleanup_noise(CUT_FILE_FIXTURE_SIZE),
        (110, 90, 60, 255),
    ),
    (
        "gumboot_chiton",
        "silhouette.png",
        "silhouette",
        AREA_FINDING_FIXTURE_SIZE,
        _gumboot_chiton_silhouette_with_a_dot(AREA_FINDING_FIXTURE_SIZE),
        (120, 80, 50, 255),
    ),
    (
        "bat_star",
        "silhouette.png",
        "silhouette",
        AREA_FINDING_FIXTURE_SIZE,
        _bat_star_silhouette_with_a_sliver(AREA_FINDING_FIXTURE_SIZE),
        (200, 120, 60, 255),
    ),
    (
        "keyhole_limpet",
        "silhouette.png",
        "silhouette",
        AREA_FINDING_FIXTURE_SIZE,
        _keyhole_limpet_silhouette_with_a_small_hole(AREA_FINDING_FIXTURE_SIZE),
        (140, 130, 110, 255),
    ),
    (
        "turban_snail",
        "silhouette.png",
        "silhouette",
        AREA_FINDING_FIXTURE_SIZE,
        _turban_snail_silhouette_with_a_borderline_hole(AREA_FINDING_FIXTURE_SIZE),
        (90, 110, 70, 255),
    ),
]

# (filename under the catalog root, RGBA fill color). The placeholder brand
# mark that tests/fixtures/catalog/brand.toml's mark_file points at (issue #3).
MARK_IMAGE = ("mark.png", (28, 74, 122, 255))


def main() -> None:
    for asset_id, filename, _role, mask, rgba in SHAPED_SOURCE_IMAGES:
        out_dir = FIXTURE_ASSETS_DIR / asset_id / "sources"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        out_path.write_bytes(make_shaped_png(SIZE, mask, rgba))
        print(f"wrote {out_path}")

    for asset_id, filename, _role, rgba in SOLID_SOURCE_IMAGES:
        out_dir = FIXTURE_ASSETS_DIR / asset_id / "sources"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        out_path.write_bytes(make_png(SIZE, rgba))
        print(f"wrote {out_path}")

    for asset_id, filename, _role, pixels in MULTI_COLOR_SOURCE_IMAGES:
        out_dir = FIXTURE_ASSETS_DIR / asset_id / "sources"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        out_path.write_bytes(_encode_png(SIZE, pixels))
        print(f"wrote {out_path}")

    for asset_id, filename, _role, mask, rgba, truncate_to in TRUNCATED_SOURCE_IMAGES:
        out_dir = FIXTURE_ASSETS_DIR / asset_id / "sources"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        out_path.write_bytes(make_shaped_png(SIZE, mask, rgba)[:truncate_to])
        print(f"wrote {out_path} (truncated to {truncate_to} bytes)")

    for asset_id, filename, _role, size, mask, rgba in LARGE_CANVAS_SOURCE_IMAGES:
        out_dir = FIXTURE_ASSETS_DIR / asset_id / "sources"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        out_path.write_bytes(make_shaped_png(size, mask, rgba))
        print(f"wrote {out_path}")

    mark_filename, mark_rgba = MARK_IMAGE
    mark_path = FIXTURE_CATALOG_ROOT / mark_filename
    mark_path.write_bytes(make_png(SIZE, mark_rgba))
    print(f"wrote {mark_path}")


if __name__ == "__main__":
    main()
