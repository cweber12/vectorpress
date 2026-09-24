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

    mark_filename, mark_rgba = MARK_IMAGE
    mark_path = FIXTURE_CATALOG_ROOT / mark_filename
    mark_path.write_bytes(make_png(SIZE, mark_rgba))
    print(f"wrote {mark_path}")


if __name__ == "__main__":
    main()
