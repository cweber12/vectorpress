# Flat-color generator sources

Source images for `flatcolor_svg` tests, outside the fixture catalog
(`tests/fixtures/catalog/`): they exercise the generator on its own, so they need no
asset, and adding one to the catalog would change every catalog-wide count and
snapshot for a case the catalog's own wiring has nothing to do with.

- `noisy_flatcolor.png` -- a 300x300 teal disk with a cream disk enclosed in it, on a
  transparent background, every opaque pixel's RGB nudged by seeded noise of at most
  1 per channel (issue #83). Two colors to a viewer, 54 distinct shades to the
  generator, 28 of them clearing the recipe's `min_color_share` on their own.
  Written by `generate_noisy_flatcolor_png.py`; regenerate it with:

      uv run python tests/fixtures/flatcolor/generate_noisy_flatcolor_png.py

  `tests/unit/test_pipeline_flatcolor_svg_noise.py` checks that the committed file
  still holds the pixels the script produces.
