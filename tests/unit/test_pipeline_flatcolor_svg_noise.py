"""pipeline.flatcolor_svg against sources that are not cleanly flat (issue
#83): per-pixel noise inside a flat region, and artwork that is not
flat-color at all.

Reads ``tests/fixtures/flatcolor/noisy_flatcolor.png`` rather than building
every source in memory, unlike ``test_pipeline_flatcolor_svg.py``: the noise
has to be the same bytes on every machine, so it is committed, with the
script that generates it beside it.
"""

import importlib.util
import re
import time
from io import BytesIO
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from PIL import Image

from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import RECIPES
from vectorpress.pipeline.flatcolor_svg import generate

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "flatcolor"
NOISY_FLATCOLOR_PNG = FIXTURE_DIR / "noisy_flatcolor.png"
NOISY_FLATCOLOR_SCRIPT = FIXTURE_DIR / "generate_noisy_flatcolor_png.py"

TEAL_HEX = "#2a9d8f"
CREAM_HEX = "#e9d8a6"


def _production_parameters() -> dict[str, object]:
    return dict(RECIPES[DerivativeType.FLATCOLOR_SVG].parameters)


def _paths(svg_bytes: bytes) -> list[tuple[str, str]]:
    """Every ``(fill, d)`` pair, one per ``<path>`` element, in document
    order."""
    text = svg_bytes.decode("utf-8")
    return re.findall(r'<path fill="(#[0-9a-f]{6})"[^>]*\sd="([^"]*)"', text)


def _fixture_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_noisy_flatcolor_png", NOISY_FLATCOLOR_SCRIPT
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- noise inside a flat region folds away (issue #83) ----------------------


def test_a_noisy_flat_color_source_collapses_to_its_noiseless_palette() -> None:
    """Two visible colors, each really 27 near-identical shades: the
    derivative has the two noiseless colors as its only fills, larger region
    first."""
    result = generate(NOISY_FLATCOLOR_PNG.read_bytes(), _production_parameters())

    fills = [fill for fill, _d in _paths(result.output_bytes)]
    assert fills == [TEAL_HEX, CREAM_HEX]


def test_a_noisy_flat_color_source_traces_to_whole_regions_not_fragments() -> None:
    """The teal disk is one outline plus the hole the cream disk sits in;
    the cream disk is one outline. No shade of either became a scatter of
    fragments of its own."""
    result = generate(NOISY_FLATCOLOR_PNG.read_bytes(), _production_parameters())

    subpath_counts = {fill: d.count("M") for fill, d in _paths(result.output_bytes)}
    assert subpath_counts == {TEAL_HEX: 2, CREAM_HEX: 1}


def test_the_committed_noisy_fixture_is_what_its_script_generates() -> None:
    """Compared as decoded pixels, not file bytes: PNG compression is free
    to differ between zlib builds, the pixels are not."""
    script = _fixture_script()

    with Image.open(NOISY_FLATCOLOR_PNG) as committed:
        committed_pixels = np.array(committed.convert("RGBA"))

    assert np.array_equal(committed_pixels, np.array(script.noisy_pixels(), dtype=np.uint8))


# --- shade_merge_tolerance ---------------------------------------------------


def _two_shade_checkerboard_bytes(
    frequent: tuple[int, int, int], rare: tuple[int, int, int], size: int = 16
) -> bytes:
    """One opaque square of two shades: ``rare`` on every third pixel of
    every row, ``frequent`` everywhere else."""
    array = np.zeros((size, size, 4), dtype=np.uint8)
    array[:, :, :3] = frequent
    array[:, ::3, :3] = rare
    array[:, :, 3] = 255
    buffer = BytesIO()
    Image.fromarray(array, mode="RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_merged_colors_fill_is_its_most_frequent_shade_never_an_average() -> None:
    """Merging keeps "no palette invention": two shades 2 apart fold
    into one fill, and that fill is the more frequent of the two exactly."""
    source_bytes = _two_shade_checkerboard_bytes(frequent=(200, 100, 50), rare=(202, 100, 50))

    result = generate(source_bytes, _production_parameters())

    assert [fill for fill, _d in _paths(result.output_bytes)] == ["#c86432"]


def test_shade_merge_tolerance_controls_how_far_apart_two_shades_still_merge() -> None:
    """Two halves 10 apart in RGB are one color under the recipe's own
    tolerance and two under a tolerance tighter than their distance."""
    array = np.zeros((16, 16, 4), dtype=np.uint8)
    array[:, :10, :3] = (200, 100, 50)
    array[:, 10:, :3] = (210, 100, 50)
    array[:, :, 3] = 255
    buffer = BytesIO()
    Image.fromarray(array, mode="RGBA").save(buffer, format="PNG")
    source_bytes = buffer.getvalue()

    merged = generate(source_bytes, {"shade_merge_tolerance": 16.0})
    assert [fill for fill, _d in _paths(merged.output_bytes)] == ["#c86432"]

    distinct = generate(source_bytes, {"shade_merge_tolerance": 4.0})
    assert [fill for fill, _d in _paths(distinct.output_bytes)] == ["#c86432", "#d26432"]


# --- a source that is not flat-color fails fast (issue #83, §35) ------------


def _random_rgb_bytes(size: int = 300) -> bytes:
    """Every pixel opaque and its own random color: nothing here is a flat
    region, so whatever palette is chosen, each color's pixels are scattered
    across the whole image."""
    rng = np.random.default_rng(83)
    array = rng.integers(0, 256, size=(size, size, 4), dtype=np.uint8)
    array[:, :, 3] = 255
    buffer = BytesIO()
    Image.fromarray(array, mode="RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_source_that_is_not_flat_color_fails_naming_the_fragment_count_and_color() -> None:
    with pytest.raises(
        ValueError,
        match=r"source is not flat-color: \d+ fragments in color #[0-9a-f]{6} \(at most 1000\)",
    ):
        generate(_random_rgb_bytes(), _production_parameters())


def test_a_source_that_is_not_flat_color_fails_before_any_tracing() -> None:
    """The failure has to arrive instead of the trace, not after it.
    Tracing this source's sixteen scattered masks took about forty seconds
    on the machine issue #83 was fixed on; refusing it took under half of
    one, so ten seconds tells the two apart with room for a slow CI
    runner."""
    source_bytes = _random_rgb_bytes()

    started = time.perf_counter()
    with pytest.raises(ValueError, match="source is not flat-color"):
        generate(source_bytes, _production_parameters())

    assert time.perf_counter() - started < 10.0
