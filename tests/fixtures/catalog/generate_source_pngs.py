"""Generate the fixture catalog's tiny source PNGs and its brand mark.

Committed alongside the PNGs it writes (issue #4, issue #3) so they can be
regenerated deterministically without a new dependency: stdlib ``zlib``
and ``struct`` are enough to write a valid, tiny, uncompressed-per-row
PNG. Run it from the repo root with:

    uv run python tests/fixtures/catalog/generate_source_pngs.py

This script is a fixture author's tool; vectorpress itself never writes
under an asset's ``sources/`` directory (ADR 0003, ADR 0007, §21), and
never writes the brand mark either (ADR 0005: hand-authored, tool-read-only).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

FIXTURE_CATALOG_ROOT = Path(__file__).parent
FIXTURE_ASSETS_DIR = FIXTURE_CATALOG_ROOT / "assets"

SIZE = 8  # pixels; square, tiny on purpose (CLAUDE.md, fixture README)

# (asset ID, filename under its sources/, role, RGBA fill color).
# ochre_sea_star gets two roles (silhouette + lineart) to exercise an
# asset with several sources (issue #4 acceptance criteria).
SOURCE_IMAGES = [
    ("ochre_sea_star", "silhouette.png", "silhouette", (196, 93, 38, 255)),
    ("ochre_sea_star", "lineart.png", "lineart", (20, 20, 20, 255)),
    ("purple_sea_urchin", "silhouette.png", "silhouette", (91, 46, 130, 255)),
    ("giant_green_anemone", "silhouette.png", "silhouette", (58, 140, 92, 255)),
]

# (filename under the catalog root, RGBA fill color). The placeholder brand
# mark that tests/fixtures/catalog/brand.toml's mark_file points at (issue #3).
MARK_IMAGE = ("mark.png", (28, 74, 122, 255))


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def make_png(size: int, rgba: tuple[int, int, int, int]) -> bytes:
    """A minimal valid PNG: one solid RGBA color, no filtering, no interlace."""
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    scanline = b"\x00" + bytes(rgba) * size  # leading filter-type byte: None
    raw = scanline * size
    idat = zlib.compress(raw, level=9)
    return (
        b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    )


def main() -> None:
    for asset_id, filename, _role, rgba in SOURCE_IMAGES:
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
