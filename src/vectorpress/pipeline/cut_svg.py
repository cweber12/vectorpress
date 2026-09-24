"""The cut-file SVG generator (§6.3, §8, §9.1, ADR 0007, issue #36).

Builds the same kind of binary ink mask :mod:`vectorpress.pipeline.silhouette_svg`
does (a pixel is ink when its alpha exceeds ``alpha_threshold``) from the
selected silhouette source, but -- unlike ``silhouette_svg`` -- cleans it
deterministically *before* tracing (ADR 0007's "generated cut file = silhouette
source + deterministic geometric cleanup at the reference size"):

- ink islands below a minimum physical area are dropped
- background holes below a minimum physical area are filled in
- a morphological opening sized from a minimum physical feature width erases
  anything narrower than that (a hairline spur, for example)

**No bridging or joining of disconnected fragments** (ADR 0007): a separate
piece whose area clears the island threshold is left exactly where it is, as
its own subpath -- nothing here ever draws a piece towards another.

Every threshold above is expressed in physical units (square inches, inches)
rather than pixels, because a pixel is not a fixed size -- only physical units
are meaningful across sources traced at different resolutions (§9.1). Turning
a physical threshold into a pixel one takes a scale: pixels per inch, derived
from the *uncleaned* ink mask's own bounding box (its longest side, in pixels,
mapped onto ``reference_size_in`` -- the effective parameter
:mod:`vectorpress.pipeline.generate` merges in from the catalog's reference
size, ADR 0004, issue #36) rather than the cleaned-up geometry's bounding box:
cleanup only ever removes noise that was never part of the piece's own
nominal extent (a detached piece large enough to survive already sits inside
that extent; a speck, pinhole or spur too small to survive never defined it),
so the two bounding boxes coincide in every case this generator is meant for,
and using the uncleaned one avoids a circular "the scale depends on the
cleanup, which depends on the scale" dependency.

Tracing and rendering reuse :mod:`vectorpress.pipeline._potrace_trace`'s
``trace_subpaths`` and :mod:`vectorpress.pipeline.svg_document`'s
``render_svg`` exactly as :mod:`vectorpress.pipeline.silhouette_svg` does --
one black filled compound path, even-odd, §8-clean by construction. Potrace's
own speckle suppression (``turdsize``) is turned off here (``speckle_size=0``):
this generator's own island removal already covers it, working in physical
units potrace's pixel-count parameter cannot express.

Connected-component labelling (for island and hole detection) and morphology
(for the opening) come from ``scipy.ndimage`` -- plain numpy has neither --
through :mod:`vectorpress.pipeline._ndimage_cleanup`, the one place that
talks to it directly (that module's own docstring explains why, mirroring
:mod:`vectorpress.pipeline._potrace_trace`'s split for ``potracer``).
``scipy`` ships prebuilt wheels for cp312 on both ubuntu-latest and
windows-latest (manylinux and win_amd64), so it installs with no system
package the same way ``potracer`` does; its labelling and binary morphology
operate on boolean arrays with a fixed structuring element -- integer,
combinatorial operations with no floating-point step -- so, like potrace's
own tracing, they produce identical output on both platforms for identical
input.
"""

import importlib.metadata
from collections.abc import Mapping
from io import BytesIO

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from vectorpress.pipeline._ndimage_cleanup import (
    fill_small_holes,
    open_narrow_features,
    remove_small_islands,
)
from vectorpress.pipeline._potrace_trace import trace_subpaths
from vectorpress.pipeline.generator import GeneratorOutput
from vectorpress.pipeline.svg_document import Fill, render_svg

#: This recipe's generator name (:attr:`vectorpress.domain.recipe.Recipe.generator`).
GENERATOR_NAME = "cut_svg"

#: Fallback parameter values, used only when ``parameters`` omits a key --
#: matches :mod:`vectorpress.pipeline.silhouette_svg`'s own defaults for the
#: parameter the two share (``alpha_threshold``), plus this generator's own
#: physical cleanup thresholds and its coarser curve tolerance (§6.3).
_DEFAULT_ALPHA_THRESHOLD = 127
_DEFAULT_ISLAND_MIN_AREA_IN2 = 0.01
_DEFAULT_HOLE_MIN_AREA_IN2 = 0.01
_DEFAULT_OPENING_WIDTH_IN = 0.06
_DEFAULT_CURVE_TOLERANCE = 0.5
#: Matches :data:`vectorpress.domain.catalog_config.DEFAULT_REFERENCE_SIZE_IN`
#: -- this module never imports ``domain.catalog_config`` itself (a generator
#: takes only bytes and parameters, ADR 0006), so the number is repeated, not
#: shared, as the fallback for a caller (a standalone unit test, typically)
#: that omits ``reference_size_in`` entirely rather than merging it in the
#: way :mod:`vectorpress.pipeline.generate` does for a real catalog.
_DEFAULT_REFERENCE_SIZE_IN = 3.0

#: Solid black fill (§6.2/§6.3: a single-color cut file, same convention
#: ``silhouette_svg`` uses).
_FILL = "#000000"


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


def _ink_mask(source_bytes: bytes, alpha_threshold: int) -> NDArray[np.bool_]:
    """A boolean grid, ``True`` where a pixel's alpha exceeds
    ``alpha_threshold`` -- identical to
    :func:`vectorpress.pipeline.silhouette_svg._ink_mask`, kept as its own
    copy rather than a shared import so each generator module stays a
    self-contained bytes-in, bytes-out unit (matches the existing
    ``silhouette_svg`` / ``flatcolor_svg`` split, which duplicates the same
    small parameter helpers for the same reason)."""
    with Image.open(BytesIO(source_bytes)) as source:
        alpha = np.array(source.convert("RGBA").getchannel("A"))
    return alpha > alpha_threshold


def _bbox_longest_side_px(mask: NDArray[np.bool_]) -> int:
    """The longest side, in pixels, of ``mask``'s own tight bounding box
    (§9.1's "the longest side of the ink mask's bounding box") -- the same
    quantity the §8 builder's tight viewBox will end up expressing in output
    units, since cleanup never grows a shape's extent, only ever shrinks
    noise inside it (this module's own docstring).

    Raises ``ValueError`` when there is no ink at all: no bounding box, and
    nothing a cut file could be built from (mirrors
    ``silhouette_svg``/``flatcolor_svg``'s own "nothing to trace" failures,
    which the PRD 02 ruling reports ``failed``, never ``impossible``).
    """
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        raise ValueError("no ink to build a cut file from")
    height = int(ys.max()) - int(ys.min()) + 1
    width = int(xs.max()) - int(xs.min()) + 1
    return max(height, width)


def generate(source_bytes: bytes, parameters: Mapping[str, object]) -> GeneratorOutput:
    """Produce the cut-file SVG from ``source_bytes`` (§6.3): the selected
    silhouette source, cleaned deterministically at the effective reference
    size (island/hole removal, then a morphological opening, ADR 0007), then
    traced and rendered the same §8-clean way ``silhouette_svg`` is -- one
    black filled (or compound) path, no stroke, document bounds tight to
    what survives cleanup.
    """
    alpha_threshold = _param_int(parameters, "alpha_threshold", _DEFAULT_ALPHA_THRESHOLD)
    island_min_area_in2 = _param_float(
        parameters, "island_min_area_in2", _DEFAULT_ISLAND_MIN_AREA_IN2
    )
    hole_min_area_in2 = _param_float(parameters, "hole_min_area_in2", _DEFAULT_HOLE_MIN_AREA_IN2)
    opening_width_in = _param_float(parameters, "opening_width_in", _DEFAULT_OPENING_WIDTH_IN)
    curve_tolerance = _param_float(parameters, "curve_tolerance", _DEFAULT_CURVE_TOLERANCE)
    reference_size_in = _param_float(parameters, "reference_size_in", _DEFAULT_REFERENCE_SIZE_IN)

    mask = _ink_mask(source_bytes, alpha_threshold)
    pixels_per_inch = _bbox_longest_side_px(mask) / reference_size_in

    cleaned = remove_small_islands(mask, island_min_area_in2 * pixels_per_inch**2)
    cleaned = fill_small_holes(cleaned, hole_min_area_in2 * pixels_per_inch**2)
    cleaned = open_narrow_features(cleaned, opening_width_in * pixels_per_inch)

    subpaths = trace_subpaths(cleaned, speckle_size=0, curve_tolerance=curve_tolerance)

    output_bytes = render_svg([Fill(fill=_FILL, subpaths=subpaths)], fill_rule="evenodd")
    return GeneratorOutput(
        output_bytes=output_bytes,
        library_versions={
            "potracer": importlib.metadata.version("potracer"),
            "numpy": np.__version__,
            "scipy": importlib.metadata.version("scipy"),
        },
    )
