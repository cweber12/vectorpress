"""Generate ``noisy_flatcolor.png``: a flat-color source carrying seeded
per-pixel RGB noise (issue #83).

Committed alongside the PNG it writes so the fixture can be regenerated
deterministically, the same arrangement as
``tests/fixtures/catalog/generate_source_pngs.py``. Run it from the repo root
with:

    uv run python tests/fixtures/flatcolor/generate_noisy_flatcolor_png.py

The artwork is two hard-edged flat colors on a transparent background: a teal
disk with a smaller cream disk fully enclosed inside it. Every opaque pixel's
red, green and blue channels are then each nudged by -1, 0 or +1, so each of
the two colors a viewer sees is really 27 near-identical shades spread evenly
across its whole region -- noise *inside* a flat region, which
``min_color_share`` (built for thin anti-aliased seams) does not catch.

The nudge is drawn from ``(-1, 0, 0, +1)`` per channel, not uniformly: the
noiseless color stays the single most frequent shade of its region (one pixel
in eight) while still being a small minority of it. That mirrors the real
source issue #83 was measured on, whose modal teal shade held about 13% of
the ink.
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image

FIXTURE_PATH = Path(__file__).parent / "noisy_flatcolor.png"

SIZE = 300  # pixels; square
SEED = 83

Rgb = tuple[int, int, int]
Rgba = tuple[int, int, int, int]

TRANSPARENT: Rgba = (0, 0, 0, 0)
TEAL: Rgb = (42, 157, 143)
CREAM: Rgb = (233, 216, 166)

#: The two colors the artwork is drawn in, before noise -- what a correct
#: flat-color derivative's palette is.
NOISELESS_COLORS: tuple[Rgb, ...] = (TEAL, CREAM)

_CENTER = SIZE / 2
_TEAL_RADIUS = 130.0
_CREAM_RADIUS = 50.0
_NUDGES = (-1, 0, 0, 1)


def noiseless_pixels() -> list[list[Rgba]]:
    """The artwork before noise, as a row-major grid."""
    pixels: list[list[Rgba]] = []
    for y in range(SIZE):
        row: list[Rgba] = []
        for x in range(SIZE):
            distance = ((x + 0.5 - _CENTER) ** 2 + (y + 0.5 - _CENTER) ** 2) ** 0.5
            if distance <= _CREAM_RADIUS:
                row.append((*CREAM, 255))
            elif distance <= _TEAL_RADIUS:
                row.append((*TEAL, 255))
            else:
                row.append(TRANSPARENT)
        pixels.append(row)
    return pixels


def noisy_pixels() -> list[list[Rgba]]:
    """:func:`noiseless_pixels` with every opaque pixel's RGB nudged, in
    row-major order from one seeded generator; alpha is left alone."""
    rng = random.Random(SEED)
    pixels: list[list[Rgba]] = []
    for row in noiseless_pixels():
        noisy_row: list[Rgba] = []
        for r, g, b, a in row:
            if a == 0:
                noisy_row.append(TRANSPARENT)
                continue
            noisy_row.append(
                (r + rng.choice(_NUDGES), g + rng.choice(_NUDGES), b + rng.choice(_NUDGES), a)
            )
        pixels.append(noisy_row)
    return pixels


def main() -> None:
    image = Image.new("RGBA", (SIZE, SIZE))
    image.putdata([pixel for row in noisy_pixels() for pixel in row])
    image.save(FIXTURE_PATH, format="PNG", optimize=True)
    print(f"wrote {FIXTURE_PATH}")


if __name__ == "__main__":
    main()
