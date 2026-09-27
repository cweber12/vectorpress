# pyright: basic
# (calls scipy.ndimage directly as its oracle -- the same split
# pipeline/_ndimage_cleanup.py documents for scipy's loose types)
"""pipeline._ndimage_cleanup.open_narrow_features: the cut file's
morphological opening, computed from distance transforms (issue #86).

The disk-structuring-element ``binary_opening`` it replaced is kept here as
the oracle. Its cost grew with pixels times disk area, and since the disk
radius comes from pixels per inch, that is roughly size^4 in the source's
side length (10.5s at 2508px). The distance-transform version must produce
the identical mask -- same pixels, so the same traced cut file, the same
output hash, and no provenance change (ADR 0004).
"""

import numpy as np
import pytest
from numpy.typing import NDArray
from scipy import ndimage as ndi

from vectorpress.pipeline._ndimage_cleanup import open_narrow_features


def _disk(radius: int) -> NDArray[np.bool_]:
    offsets = np.arange(-radius, radius + 1)
    y, x = np.meshgrid(offsets, offsets, indexing="ij")
    return (x * x + y * y) <= radius * radius


def _binary_opening(mask: NDArray[np.bool_], width_px: float) -> NDArray[np.bool_]:
    """The pre-issue-#86 implementation."""
    radius = round(width_px / 2)
    if radius < 1:
        return mask
    return np.asarray(ndi.binary_opening(mask, structure=_disk(radius)), dtype=bool)


def _blobby_mask(seed: int, size: int, smoothing: float) -> NDArray[np.bool_]:
    """Smoothed noise, thresholded: blobs, thin necks, spurs and holes of
    every width, many of them touching the array's own edge."""
    rng = np.random.default_rng(seed)
    noise = ndi.gaussian_filter(rng.random((size, size)), smoothing)
    return noise > np.median(noise)


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("width_px", [0.4, 2.0, 5.0, 9.0, 16.0, 31.0])
def test_matches_binary_opening_with_a_disk(seed: int, width_px: float) -> None:
    mask = _blobby_mask(seed, 96, smoothing=2.0 + seed)

    assert np.array_equal(open_narrow_features(mask, width_px), _binary_opening(mask, width_px))


@pytest.mark.parametrize(
    "mask",
    [
        np.ones((40, 40), dtype=bool),  # all ink: the edge still erodes it
        np.zeros((40, 40), dtype=bool),  # no ink at all
        np.pad(np.ones((3, 30), dtype=bool), 5),  # a bar narrower than the disk: erodes to nothing
    ],
    ids=["full", "empty", "too-thin-to-survive"],
)
def test_matches_binary_opening_at_the_extremes(mask: NDArray[np.bool_]) -> None:
    assert np.array_equal(open_narrow_features(mask, 8.0), _binary_opening(mask, 8.0))
