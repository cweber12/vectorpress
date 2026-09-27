"""The flat-color SVG generator (§6.9, §8, issue #25, issue #83).

Quantizes the selected flatcolor-role source to its own genuinely flat
opaque colors -- ``max_colors`` caps how many, but a color's fill value is
always one the source actually contains, never an invented average ("no
palette invention") -- then traces one filled region per color and renders
them through :mod:`vectorpress.pipeline.svg_document`'s shared §8-clean
builder, the same tracer and cleaning pass
:mod:`vectorpress.pipeline.silhouette_svg` uses (issue #24), extended to
several fills instead of one (issue #25).

A pixel is *ink* (opaque, part of some color region) when its alpha exceeds
``alpha_threshold``, exactly as :mod:`vectorpress.pipeline.silhouette_svg`
decides ink -- everything else is background and belongs to no region. The
palette is chosen only from colors making up at least ``min_color_share``
of the ink pixels (review fix round 1, issue #25): a real flat-color region
is a substantial share of the artwork, while a real anti-aliased edge blend
between two colors is confined to a thin seam and so is a tiny share of it,
however many distinct blend shades that seam breaks into and regardless of
whether the total color count is under ``max_colors`` -- both failure modes
the naive "just take the ``max_colors`` most frequent colors" rule missed.
Before that share is measured, shades within ``shade_merge_tolerance`` of a
more frequent shade are counted as that shade (issue #83): per-pixel noise
*inside* a flat region -- AI-generated "flat" artwork carries it -- spreads
one visible color across hundreds of near-identical shades, evenly over the
whole region, so several of them clear ``min_color_share`` on their own and
the palette fills up with near-duplicates of one color. The shade that
stands for the rest is the most frequent of them, so the fill is still a
color the source contains.
Every ink pixel -- including one whose own color did not clear the palette
threshold -- is then assigned to the palette color nearest it in RGB space;
an ink pixel whose own color is already in the palette is nearest to
itself (distance zero), so this single rule both places a palette color's
own pixels and folds every other pixel onto the palette color it most
resembles, so no such pixel becomes a tiny region of its own. Because every
ink pixel maps to exactly one color, each color's resulting region is
disjoint from every other's: nesting one color fully inside another still
traces correctly (the outer color's own mask has a hole where the inner
color's pixels were reassigned away from it, the same way
:mod:`vectorpress.pipeline.silhouette_svg` traces a ring's hole).

A source whose colors do not form regions at all is refused rather than
traced (issue #83, §35): when any color's pixels are more than
``max_fragments_per_color`` separate fragments, generation fails naming the
count and the color. The tracer's time grows with the fragment count times
the image size, so such a source would otherwise run for minutes to hours.

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

from vectorpress.pipeline._color_index import ColorIndex
from vectorpress.pipeline._ndimage_cleanup import count_islands
from vectorpress.pipeline._potrace_trace import trace_subpaths
from vectorpress.pipeline.generator import GeneratorOutput
from vectorpress.pipeline.svg_document import Fill, Subpath, render_svg

#: This recipe's generator name (:attr:`vectorpress.domain.recipe.Recipe.generator`).
GENERATOR_NAME = "flatcolor_svg"

#: Fallback parameter values, used only when ``parameters`` (normally
#: :attr:`vectorpress.domain.recipe.Recipe.parameters`) omits a key -- matches
#: :mod:`vectorpress.pipeline.silhouette_svg`'s tracing defaults, plus this
#: generator's own quantization parameters and fragment ceiling.
_DEFAULT_ALPHA_THRESHOLD = 127
_DEFAULT_CURVE_TOLERANCE = 0.2
_DEFAULT_SPECKLE_SIZE = 2
_DEFAULT_MAX_COLORS = 16
_DEFAULT_MIN_COLOR_SHARE = 0.01
_DEFAULT_SHADE_MERGE_TOLERANCE = 16.0
_DEFAULT_MAX_FRAGMENTS_PER_COLOR = 1000

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


def _merge_near_identical_shades(
    unique_colors: NDArray[np.int64], unique_counts: NDArray[np.int64], tolerance: float
) -> Counter[Rgb]:
    """``unique_colors``' ink pixel counts with every shade within
    ``tolerance`` (Euclidean RGB distance) of a more frequent shade folded
    into that shade's count (issue #83): per-pixel noise spreads one visible
    color across many near-identical shades, evenly over its whole region,
    so no single one of them says how much of the artwork that color really
    is.

    Greedy, most frequent first: the most frequent shade not yet folded
    anywhere becomes a representative and takes every remaining shade
    within ``tolerance`` of it. A representative is therefore always a shade
    the source actually contains -- the most frequent of the ones it stands
    for, never an average of them ("no palette invention"). Ties are broken
    by the shade's own RGB value (§36).
    """
    order = np.lexsort(
        (unique_colors[:, 2], unique_colors[:, 1], unique_colors[:, 0], -unique_counts)
    )
    colors = unique_colors[order]
    counts = unique_counts[order]
    index = ColorIndex(colors)
    unfolded = np.ones(colors.shape[0], dtype=np.bool_)

    merged: Counter[Rgb] = Counter()
    for row in range(colors.shape[0]):
        if not unfolded[row]:
            continue
        near = index.within(colors[row], tolerance)
        folded = near[unfolded[near]]
        r, g, b = (int(channel) for channel in colors[row])
        merged[(r, g, b)] = int(counts[folded].sum())
        unfolded[folded] = False
    return merged


def _choose_palette(
    ink_color_counts: Counter[Rgb], max_colors: int, min_color_share: float
) -> list[Rgb]:
    """Up to ``max_colors`` of the source's own genuinely flat opaque
    colors ("source colors are used exactly as fill values, no palette
    invention"): the most frequent among the ink pixels, restricted first to
    colors making up at least ``min_color_share`` of every ink pixel (review
    fix round 1, issue #25) -- a real flat-fill region is a substantial
    share of the artwork; a stray anti-aliased blend shade, however many
    distinct ones a boundary breaks into, is not. Ties (and the cap itself)
    are broken by the color's own RGB value so the choice -- and its order
    -- never depends on dict/set iteration order (§36).

    Falls back to every color, unfiltered, if the share threshold would
    leave nothing standing (e.g. a source with no single color anywhere
    near dominant -- a photographic gradient, not real flat-color art):
    quantizing to *something* is still better than raising, and this is the
    same "no acceptable source is worse than an imperfect one" spirit
    ``alpha_threshold`` already has no equivalent fallback for, since ink
    with zero colors is already covered by the empty-``ink_color_counts``
    check its caller makes.
    """
    total_ink_pixels = sum(ink_color_counts.values())
    minimum_count = min_color_share * total_ink_pixels
    flat_colors = {
        color: count for color, count in ink_color_counts.items() if count >= minimum_count
    }
    candidates = flat_colors if flat_colors else ink_color_counts
    ordered = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))
    return [color for color, _count in ordered[:max_colors]]


def _quantize_to_masks(
    rgba: NDArray[np.uint8],
    alpha_threshold: int,
    max_colors: int,
    min_color_share: float,
    shade_merge_tolerance: float,
) -> list[tuple[Rgb, NDArray[np.bool_]]]:
    """Every ink pixel of ``rgba`` (an ``(H, W, 4)`` array), assigned to its
    nearest palette color: one ``(H, W)`` boolean mask per chosen palette
    color, ``True`` where that color owns the pixel.

    Nearest is squared Euclidean distance in RGB space, using the first
    palette color reached (numpy's own ``argmin`` tie-break) as the winner
    of an exact tie -- deterministic (§36), and never invents a blended
    color: every pixel ends up assigned to one of ``palette``'s own values.

    Works over each *unique* ink color exactly once (review fix round 1,
    issue #25), not over every ink pixel: the distance array this builds is
    ``(U, P)`` where ``U`` is the count of distinct ink colors, not ``(N,
    P)`` where ``N`` is the count of ink pixels. Real artwork's distinct
    color count is bounded by its edges (antialiasing) and its palette, not
    its resolution -- ``U`` stays in the thousands even for a many-megapixel
    source -- so this avoids the ``N``-pixel version's multi-gigabyte
    allocation on production-size artwork (a 4000x4000 source with 16
    palette colors was ~6 GB of intermediate ``int64`` differences alone).
    """
    height, width, _ = rgba.shape
    ink = rgba[:, :, 3] > alpha_threshold

    # Mask before widening to int64 (not the other way around): this casts
    # only the ink pixels, not the whole -- possibly fully-opaque -- image.
    ink_pixels = rgba[:, :, :3][ink].astype(np.int64)  # (N, 3)
    if ink_pixels.size == 0:
        raise ValueError("no opaque pixels to quantize into flat-color regions")

    unique_colors, inverse, unique_counts = np.unique(
        ink_pixels, axis=0, return_inverse=True, return_counts=True
    )  # unique_colors: (U, 3); inverse: (N,), each ink pixel's row in unique_colors
    inverse = inverse.reshape(-1)  # numpy >=2.0 returns an (N, 1) column; flatten to (N,)
    ink_color_counts = _merge_near_identical_shades(
        unique_colors, unique_counts, shade_merge_tolerance
    )

    palette = _choose_palette(ink_color_counts, max_colors, min_color_share)
    palette_array = np.array(palette, dtype=np.int64)  # (P, 3)

    # Nearest palette color per *unique* ink color -- (U, P) distances, not (N, P).
    diffs = unique_colors[:, np.newaxis, :] - palette_array[np.newaxis, :, :]
    distances_squared = (diffs * diffs).sum(axis=2)  # (U, P)
    nearest_palette_index_by_unique_color = distances_squared.argmin(axis=1)  # (U,)

    # Broadcast each unique color's nearest-palette answer back out to every
    # ink pixel that had it, via the (N,) index np.unique already computed.
    nearest_palette_index = nearest_palette_index_by_unique_color[inverse]  # (N,)

    assignment = np.full(height * width, -1, dtype=np.int64)
    assignment[ink.reshape(-1)] = nearest_palette_index
    assignment = assignment.reshape(height, width)

    return [(color, assignment == index) for index, color in enumerate(palette)]


def _raise_if_fragmented(
    color_masks: list[tuple[Rgb, NDArray[np.bool_]]], max_fragments_per_color: int
) -> None:
    """Refuse a source whose colors do not form regions (issue #83, §35):
    when any color's mask is more than ``max_fragments_per_color`` separate
    fragments, the artwork is not flat-color -- a photograph, a gradient,
    noise too strong for ``shade_merge_tolerance`` -- and tracing it would
    take minutes to hours to produce a derivative nobody could use. Checked
    for every color before any is traced, so the failure costs one labelling
    pass per color, not a trace.

    Every fragment counts, including one ``speckle_size`` would discard: the
    tracer still has to find it before it can discard it.
    """
    for color, mask in color_masks:
        fragment_count = count_islands(mask)
        if fragment_count > max_fragments_per_color:
            raise ValueError(
                f"source is not flat-color: {fragment_count} fragments in color "
                f"{_hex_color(color)} (at most {max_fragments_per_color})"
            )


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
    min_color_share = _param_float(parameters, "min_color_share", _DEFAULT_MIN_COLOR_SHARE)
    shade_merge_tolerance = _param_float(
        parameters, "shade_merge_tolerance", _DEFAULT_SHADE_MERGE_TOLERANCE
    )
    max_fragments_per_color = _param_int(
        parameters, "max_fragments_per_color", _DEFAULT_MAX_FRAGMENTS_PER_COLOR
    )

    with Image.open(BytesIO(source_bytes)) as source:
        rgba = np.array(source.convert("RGBA"))

    color_masks = _quantize_to_masks(
        rgba, alpha_threshold, max_colors, min_color_share, shade_merge_tolerance
    )
    _raise_if_fragmented(color_masks, max_fragments_per_color)

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
            "scipy": importlib.metadata.version("scipy"),
        },
    )
