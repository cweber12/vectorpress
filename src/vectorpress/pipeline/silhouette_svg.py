"""The solid silhouette SVG generator (§6.2, §8, issue #24).

Builds a binary ink mask from the selected silhouette source's alpha
channel (a pixel is ink when its alpha is above a threshold), traces it to
filled paths, and renders them through
:mod:`vectorpress.pipeline.svg_document`'s shared §8-clean builder: a
single black-filled compound path, no stroke, document bounds tight to the
traced geometry.

Tracer choice: ``potracer`` (PyPI), a pure-Python line-for-line port of
Peter Selinger's potrace. It ships one universal wheel
(``py2.py3-none-any``) with no compiled extension, so it installs from a
prebuilt wheel on ubuntu and windows alike with no system package -- the
issue's hard constraint. Being ordinary Python arithmetic with no threading
or SIMD, it is deterministic in the same sense
``pipeline.transparent_png``'s encoder is: the same input always walks the
same sequence of operations regardless of OS. The one residual risk is
libm-level last-bit differences in transcendental functions (``sqrt``,
``atan2``, ``cos``) between platforms' C libraries;
:mod:`vectorpress.pipeline.svg_document`'s fixed-precision number
formatting absorbs that before it can reach the output text (its own
docstring explains why). The alternative considered, ``vtracer``, is a
compiled Rust extension with per-platform wheels -- meeting the "prebuilt
wheel" half of the constraint but not the "identical output" half with the
same confidence, since a compiled, potentially parallel tracer offers no
equivalent guarantee against cross-platform floating-point divergence.
"""

import importlib.metadata
from collections.abc import Mapping
from io import BytesIO

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from vectorpress.pipeline._potrace_trace import trace_subpaths
from vectorpress.pipeline.generator import GeneratorOutput
from vectorpress.pipeline.svg_document import Fill, render_svg

#: This recipe's generator name (:attr:`vectorpress.domain.recipe.Recipe.generator`).
GENERATOR_NAME = "silhouette_svg"

#: Fallback parameter values, used only when ``parameters`` (normally
#: :attr:`vectorpress.domain.recipe.Recipe.parameters`) omits a key -- every
#: unit test that is not exercising a specific parameter calls this
#: generator with ``{}`` and still gets sensible tracing.
_DEFAULT_ALPHA_THRESHOLD = 127
_DEFAULT_CURVE_TOLERANCE = 0.2
_DEFAULT_SPECKLE_SIZE = 2

#: Solid black fill (§6.2: "a single-color silhouette version").
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
    ``alpha_threshold`` -- the recipe's "a pixel is ink when its alpha is
    above a threshold"."""
    with Image.open(BytesIO(source_bytes)) as source:
        alpha = np.array(source.convert("RGBA").getchannel("A"))
    return alpha > alpha_threshold


def generate(source_bytes: bytes, parameters: Mapping[str, object]) -> GeneratorOutput:
    """Produce the solid silhouette SVG from ``source_bytes`` (§6.2): a
    single black filled path (or compound path, for a shape with holes or
    detached islands), no stroke, document bounds tight to the traced
    geometry (§8).
    """
    alpha_threshold = _param_int(parameters, "alpha_threshold", _DEFAULT_ALPHA_THRESHOLD)
    curve_tolerance = _param_float(parameters, "curve_tolerance", _DEFAULT_CURVE_TOLERANCE)
    speckle_size = _param_int(parameters, "speckle_size", _DEFAULT_SPECKLE_SIZE)

    mask = _ink_mask(source_bytes, alpha_threshold)
    subpaths = trace_subpaths(mask, speckle_size=speckle_size, curve_tolerance=curve_tolerance)

    output_bytes = render_svg([Fill(fill=_FILL, subpaths=subpaths)], fill_rule="evenodd")
    return GeneratorOutput(
        output_bytes=output_bytes,
        library_versions={
            "potracer": importlib.metadata.version("potracer"),
            "numpy": np.__version__,
        },
    )
