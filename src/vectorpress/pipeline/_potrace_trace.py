# pyright: basic
"""The one place that talks to ``potrace`` directly (issue #24).

``potracer`` ships no type stubs and no ``py.typed`` marker, so pyright
infers its types from source -- which, being an unannotated line-for-line
C port, resolves to ``Unknown`` almost everywhere. Isolating every touch of
its API in this one small, non-strict module keeps
:mod:`vectorpress.pipeline.silhouette_svg` itself fully strict-checked: the
boundary this module exposes (:func:`trace_subpaths`) is completely typed,
so no ``Unknown`` leaks past it.
"""

import numpy as np
import potrace
from numpy.typing import NDArray

from vectorpress.pipeline.svg_document import CornerSegment, CurveSegment, Segment, Subpath


def trace_subpaths(
    mask: NDArray[np.bool_], *, speckle_size: int, curve_tolerance: float
) -> list[Subpath]:
    """Trace ``mask`` to filled subpaths with potrace.

    ``potrace.Bitmap`` inverts whatever boolean array it is given (verified
    empirically against this library version: passing a mask where ``True``
    means ink traces the *background* instead), so the mask is inverted
    here to cancel that out -- the net effect is what every other potrace
    binding takes for granted: ``True`` is the region traced as filled.

    ``turnpolicy`` (the tie-break at an otherwise-ambiguous pixel) and
    ``alphamax`` (corner-smoothing threshold) are not recipe parameters
    (issue #24 names exactly three: alpha threshold, curve tolerance,
    speckle size), so potrace's own defaults are used for both.
    """
    bitmap = potrace.Bitmap(~mask)
    traced = bitmap.trace(
        turdsize=speckle_size,
        turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY,
        alphamax=1.0,
        opticurve=True,
        opttolerance=curve_tolerance,
    )

    subpaths: list[Subpath] = []
    for curve in traced:
        segments: list[Segment] = []
        for potrace_segment in curve:
            end = potrace_segment.end_point
            if potrace_segment.is_corner:
                through = potrace_segment.c
                segments.append(CornerSegment(through=(through.x, through.y), end=(end.x, end.y)))
            else:
                c1 = potrace_segment.c1
                c2 = potrace_segment.c2
                segments.append(CurveSegment(c1=(c1.x, c1.y), c2=(c2.x, c2.y), end=(end.x, end.y)))
        start = curve.start_point
        subpaths.append(Subpath(start=(start.x, start.y), segments=tuple(segments)))
    return subpaths
