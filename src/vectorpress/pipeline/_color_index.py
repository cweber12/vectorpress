# pyright: basic
"""The one place that talks to ``scipy.spatial`` directly (issue #83).

Isolated in its own small, non-strict module for the same reason
:mod:`vectorpress.pipeline._ndimage_cleanup` isolates ``scipy.ndimage``:
the boundary this module exposes (:class:`ColorIndex`) is completely typed,
so :mod:`vectorpress.pipeline.flatcolor_svg` stays fully strict-checked.
"""

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree


class ColorIndex:
    """Which of a fixed set of RGB colors lie near a given one, without
    measuring the distance to every color in the set each time it is asked.
    """

    def __init__(self, colors: NDArray[np.int64]) -> None:
        """``colors`` is ``(U, 3)``; every answer this index gives is row
        numbers into it."""
        self._colors = colors
        self._tree = KDTree(colors)

    def within(self, color: NDArray[np.int64], distance: float) -> NDArray[np.intp]:
        """The rows of every indexed color at most ``distance`` (Euclidean,
        in RGB) from ``color``, ascending.

        The tree measures in floating point, so it is asked for slightly
        more than ``distance`` and its answer is then cut back with exact
        integer arithmetic: a color exactly ``distance`` away is always
        included, on every platform (§36).
        """
        candidates = np.asarray(
            self._tree.query_ball_point(color, r=distance * (1 + 1e-9) + 1e-9), dtype=np.intp
        )
        diffs = self._colors[candidates] - color
        exact = (diffs * diffs).sum(axis=1) <= distance * distance
        return np.sort(candidates[exact])
