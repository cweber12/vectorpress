"""The flat-color SVG generator (§6.9, §8, issue #25).

Quantizes the selected flatcolor-role source to its own distinct opaque
colors -- ``max_colors`` caps how many, but a color's fill value is always
one the source actually contains, never an invented average ("no palette
invention") -- then traces one filled region per color and renders them
through :mod:`vectorpress.pipeline.svg_document`'s shared §8-clean builder,
the same tracer and cleaning pass :mod:`vectorpress.pipeline.silhouette_svg`
uses (issue #24), extended to several fills instead of one (issue #25).

A pixel is *ink* (opaque, part of some color region) when its alpha exceeds
``alpha_threshold``, exactly as :mod:`vectorpress.pipeline.silhouette_svg`
decides ink -- everything else is background and belongs to no region.
Every ink pixel is assigned to the palette color nearest it in RGB space;
an ink pixel whose own color is already in the palette is nearest to
itself (distance zero), so this single rule both places a palette color's
own pixels and folds every other pixel -- an anti-aliased edge blend
between two colors, or a color beyond ``max_colors``' cutoff -- onto the
palette color it most resembles, so no such pixel becomes a tiny region of
its own. Because every ink pixel maps to exactly one color, each color's
resulting region is disjoint from every other's: nesting one color fully
inside another still traces correctly (the outer color's own mask has a
hole where the inner color's pixels were reassigned away from it, the same
way :mod:`vectorpress.pipeline.silhouette_svg` traces a ring's hole).

Fills are emitted in the recipe's own deterministic order -- traced area
descending, then color, ascending -- so an enclosed color (typically the
smaller region) is listed, and therefore painted, after the region
enclosing it (issue #25 acceptance criterion 2), and so that re-running
against unchanged source bytes always emits fills in the same order (§36).
"""

import importlib.metadata
from collections import Counter
from collections.abc import Mapping
from io import BytesIO

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from vectorpress.pipeline._potrace_trace import trace_subpaths
from vectorpress.pipeline.generator import GeneratorOutput
from vectorpress.pipeline.svg_document import Fill, Subpath, render_svg

#: This recipe's generator name (:attr:`vectorpress.domain.recipe.Recipe.generator`).
GENERATOR_NAME = "flatcolor_svg"

#: Fallback parameter values, used only when ``parameters`` (normally
#: :attr:`vectorpress.domain.recipe.Recipe.parameters`) omits a key -- matches
#: :mod:`vectorpress.pipeline.silhouette_svg`'s tracing defaults, plus this
#: generator's own quantization parameter.
_DEFAULT_ALPHA_THRESHOLD = 127
_DEFAULT_CURVE_TOLERANCE = 0.2
_DEFAULT_SPECKLE_SIZE = 2
_DEFAULT_MAX_COLORS = 16

Rgb = tuple[int, int, int]


def _param_int(parameters: Mapping[str, object], key: str, default: int) -> int:
    value = parameters.get(key, default)
    if isinstance(value, bool):
        raise TypeError(f"{key} parameter must be a number, got a bool")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    raise TypeError(f"{key} parameter must be a number, got {value!r}")


def _param_float(parameters: Mapping[str, object], key: str, default: float) -> float:
    value = parameters.get(key, default)
    if isinstance(value, bool):
        raise TypeError(f"{key} parameter must be a number, got a bool")
    if isinstance(value, int | float):
        return float(value)
    raise TypeError(f"{key} parameter must be a number, got {value!r}")


def _hex_color(color: Rgb) -> str:
    r, g, b = color
    return f"#{r:02x}{g:02x}{b:02x}"


def _choose_palette(ink_color_counts: Counter[Rgb], max_colors: int) -> list[Rgb]:
    """Up to ``max_colors`` of the source's own opaque colors ("source
    colors are used exactly as fill values, no palette invention"): the
    most frequent among the ink pixels, ties (and the cap itself) broken by
    the color's own RGB value so the choice -- and its order -- never
    depends on dict/set iteration order (§36)."""
    ordered = sorted(ink_color_counts.items(), key=lambda item: (-item[1], item[0]))
    return [color for color, _count in ordered[:max_colors]]


def _quantize_to_masks(
    rgba: NDArray[np.uint8], alpha_threshold: int, max_colors: int
) -> list[tuple[Rgb, NDArray[np.bool_]]]:
    """Every ink pixel of ``rgba`` (an ``(H, W, 4)`` array), assigned to its
    nearest palette color: one ``(H, W)`` boolean mask per chosen palette
    color, ``True`` where that color owns the pixel.

    Nearest is squared Euclidean distance in RGB space, using the first
    palette color reached (numpy's own ``argmin`` tie-break) as the winner
    of an exact tie -- deterministic (§36), and never invents a blended
    color: every pixel ends up assigned to one of ``palette``'s own values.
    """
    height, width, _ = rgba.shape
    ink = rgba[:, :, 3] > alpha_threshold
    rgb = rgba[:, :, :3].astype(np.int64)

    ink_pixels = rgb[ink]
    ink_color_counts: Counter[Rgb] = Counter(map(tuple, ink_pixels.tolist()))
    if not ink_color_counts:
        raise ValueError("no opaque pixels to quantize into flat-color regions")

    palette = _choose_palette(ink_color_counts, max_colors)
    palette_array = np.array(palette, dtype=np.int64)  # (P, 3)

    diffs = ink_pixels[:, np.newaxis, :] - palette_array[np.newaxis, :, :]
    distances_squared = (diffs * diffs).sum(axis=2)  # (N, P)
    nearest_palette_index = distances_squared.argmin(axis=1)  # (N,)

    assignment = np.full(height * width, -1, dtype=np.int64)
    assignment[ink.reshape(-1)] = nearest_palette_index
    assignment = assignment.reshape(height, width)

    return [(color, assignment == index) for index, color in enumerate(palette)]


def generate(source_bytes: bytes, parameters: Mapping[str, object]) -> GeneratorOutput:
    """Produce the flat-color SVG from ``source_bytes`` (§6.9): one filled
    path per distinct opaque source color, no stroke, document bounds tight
    to the traced geometry (§8), fills ordered by traced area descending
    (then color) so a smaller, enclosed region paints above the region
    enclosing it.
    """
    alpha_threshold = _param_int(parameters, "alpha_threshold", _DEFAULT_ALPHA_THRESHOLD)
    curve_tolerance = _param_float(parameters, "curve_tolerance", _DEFAULT_CURVE_TOLERANCE)
    speckle_size = _param_int(parameters, "speckle_size", _DEFAULT_SPECKLE_SIZE)
    max_colors = _param_int(parameters, "max_colors", _DEFAULT_MAX_COLORS)

    with Image.open(BytesIO(source_bytes)) as source:
        rgba = np.array(source.convert("RGBA"))

    color_masks = _quantize_to_masks(rgba, alpha_threshold, max_colors)

    traced: list[tuple[int, Rgb, list[Subpath]]] = []
    for color, mask in color_masks:
        subpaths = trace_subpaths(mask, speckle_size=speckle_size, curve_tolerance=curve_tolerance)
        if subpaths:
            traced.append((int(mask.sum()), color, subpaths))

    traced.sort(key=lambda item: (-item[0], item[1]))
    fills = [Fill(fill=_hex_color(color), subpaths=subpaths) for _area, color, subpaths in traced]

    output_bytes = render_svg(fills, fill_rule="evenodd")
    return GeneratorOutput(
        output_bytes=output_bytes,
        library_versions={
            "potracer": importlib.metadata.version("potracer"),
            "numpy": np.__version__,
        },
    )
