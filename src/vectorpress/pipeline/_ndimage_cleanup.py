# pyright: basic
"""The one place that talks to ``scipy.ndimage`` directly (issue #36).

``scipy.ndimage``'s own inline type hints resolve several of the functions
used here (``label``, ``sum``, ``binary_opening``) to broad overloaded
unions pyright cannot narrow from a plain call -- so broad that, left alone,
they infect even straightforward tuple-unpacking and indexing several lines
downstream. Every such call is immediately narrowed here with
:func:`typing.cast` to the concrete shape ``scipy.ndimage``'s own
documentation guarantees for the arguments this module always passes it
(e.g. ``label`` always returns ``(label_array, num_features)`` when called
without its optional ``output`` array, which nothing here ever supplies).
Isolating every touch of its API in this one small, non-strict module keeps
:mod:`vectorpress.pipeline.cut_svg` and
:mod:`vectorpress.pipeline.flatcolor_svg` themselves fully strict-checked:
the boundary this module exposes (plain ``NDArray[np.bool_]`` in, plain
``NDArray[np.bool_]`` or ``int`` out) is completely typed, so no ``Unknown``
leaks past it -- the same split :mod:`vectorpress.pipeline._potrace_trace`
uses for ``potracer``.
"""

from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage as ndi

#: 8-connectivity for connected-component labelling: two ink pixels sharing
#: only a corner still count as one island, and two background pixels
#: sharing only a corner still count as one hole -- the same neighborliness a
#: viewer would judge "one piece" or "one hole" by, by eye.
_CONNECTIVITY = np.ones((3, 3), dtype=bool)


def _label(mask: NDArray[np.bool_]) -> tuple[NDArray[np.int32], int]:
    """``scipy.ndimage.label`` narrowed to the ``(labels, count)`` shape it
    always returns for a plain call with no ``output`` array (every call in
    this module)."""
    return cast("tuple[NDArray[np.int32], int]", ndi.label(mask, structure=_CONNECTIVITY))


def _areas(mask: NDArray[np.bool_], labels: NDArray[np.int32], count: int) -> NDArray[np.float64]:
    """The pixel area (``True`` count) of each of ``labels``'s ``1..count``
    components, as a plain float array indexed ``[label_id - 1]``."""
    return cast("NDArray[np.float64]", ndi.sum(mask, labels, index=np.arange(1, count + 1)))


def count_islands(mask: NDArray[np.bool_]) -> int:
    """How many connected ``True`` components ``mask`` has, of any size
    (issue #83)."""
    _labels, count = _label(mask)
    return count


def remove_small_islands(mask: NDArray[np.bool_], min_area_px: float) -> NDArray[np.bool_]:
    """Every connected ``True`` component of ``mask`` whose pixel area is
    below ``min_area_px`` is dropped; every component at or above it --
    however far from the rest -- is kept exactly where it is (ADR 0007: "no
    automatic bridging or joining")."""
    labels, count = _label(mask)
    if count == 0:
        return mask
    areas = _areas(mask, labels, count)
    keep = np.zeros(count + 1, dtype=bool)
    keep[1:] = areas >= min_area_px
    return keep[labels]


def fill_small_holes(mask: NDArray[np.bool_], min_area_px: float) -> NDArray[np.bool_]:
    """Every ``False`` (background) component fully enclosed by ``True``
    pixels (it never touches the array's own edge, so it is a hole, not the
    exterior) whose pixel area is below ``min_area_px`` is filled in
    (flipped to ``True``); a background component that reaches the edge is
    the exterior and is never touched, however small the array makes it
    look; a hole at or above the threshold is left alone -- this only ever
    fills what counts as noise, never a real hole (ADR 0007)."""
    background = ~mask
    labels, count = _label(background)
    if count == 0:
        return mask

    border_labels: set[int] = (
        set(labels[0, :].tolist())
        | set(labels[-1, :].tolist())
        | set(labels[:, 0].tolist())
        | set(labels[:, -1].tolist())
    )
    border_labels.discard(0)

    areas = _areas(background, labels, count)
    fill = np.zeros(count + 1, dtype=bool)
    for label_id in range(1, count + 1):
        if label_id not in border_labels and areas[label_id - 1] < min_area_px:
            fill[label_id] = True
    return mask | fill[labels]


def _disk_structure(radius: int) -> NDArray[np.bool_]:
    """A round structuring element of ``radius`` pixels (odd-sized
    ``(2r+1, 2r+1)``), used for the morphological opening below -- a disk
    rather than a square so the opening's effect does not depend on a
    feature's own orientation."""
    offsets = np.arange(-radius, radius + 1)
    y, x = np.meshgrid(offsets, offsets, indexing="ij")
    result: NDArray[np.bool_] = (x * x + y * y) <= radius * radius
    return result


def open_narrow_features(mask: NDArray[np.bool_], width_px: float) -> NDArray[np.bool_]:
    """Erase anything narrower than ``width_px`` (a hairline spur, for
    example) with a morphological opening (erode, then dilate back) sized
    from it, leaving a solid region far wider than ``width_px`` -- like a
    piece's own main body -- essentially unchanged. A sub-pixel or
    zero-radius structuring element would have no effect at all, so it is
    skipped rather than passed to ``scipy.ndimage`` as a no-op disk."""
    radius = round(width_px / 2)
    if radius < 1:
        return mask
    return cast("NDArray[np.bool_]", ndi.binary_opening(mask, structure=_disk_structure(radius)))
