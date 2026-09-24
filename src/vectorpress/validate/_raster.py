# pyright: basic
"""The one place :mod:`vectorpress.validate` talks to ``scipy.ndimage``
directly, mirroring :mod:`vectorpress.pipeline._ndimage_cleanup`'s own
split for the same library and :mod:`vectorpress.validate._svg_document`'s
own split for ``svgelements``: every touch of a third-party array/morphology
API is isolated in this one small module, so :mod:`vectorpress.validate.
narrow_feature` stays a plain, fully-typed function over these two small
typed helpers.

**Why rasterize at all, here.** :mod:`vectorpress.validate._pieces`
already turns a cut file's path data into exact polygons, but "narrower than
a minimum physical width" has no closed-form answer over an arbitrary
polygon the way area or a bounding box does, and any deterministic method
will do. A morphological opening (erode by half the minimum width, then
dilate) is the same technique :mod:`vectorpress.pipeline.cut_svg`'s own
cleanup already uses to erase a hairline spur (:func:`vectorpress.pipeline.
_ndimage_cleanup.open_narrow_features`) -- reused here as a *measurement*
instead of a cleanup step: whatever an opening at the validation threshold's width erases
from a piece's own raster is, by construction, narrower than that threshold
somewhere along its own length.

:mod:`vectorpress.validate` never imports :mod:`vectorpress.pipeline`
(CLAUDE.md's layering guardrail, this package's own sibling-layer rule) --
this module is its own small copy of the disk-structuring-element logic
``pipeline._ndimage_cleanup`` already has, the same duplication
:mod:`vectorpress.pipeline.silhouette_svg` / ``flatcolor_svg``'s own
``_ink_mask`` helpers already accept for a self-contained boundary module.

**Rasterization is a deterministic, vectorized point-in-polygon scan** (no
external rasterization library -- CLAUDE.md: only ``svgelements``, ``numpy``
and ``scipy`` are installed), one row of pixel centers at a time: every ring
edge that crosses that row's horizontal scanline contributes an x crossing,
and a pixel is ink when its own center falls after an odd number of
crossings -- the same even-odd rule :func:`vectorpress.validate.
_pieces.point_in_polygon` applies per point, generalized here to
every ring of one piece (its own outer contour plus its immediate holes) at
once, exactly how a compound ``fill-rule="evenodd"`` path already renders.
Only ``+``, ``-``, ``*``, ``/`` and a stable sort run per pixel -- no
trigonometry, so no libm last-bit platform difference to absorb here (unlike
``svgelements``' own curve sampling); the morphological opening below
(``scipy.ndimage.binary_opening``) is the same integer, combinatorial
operation ``pipeline._ndimage_cleanup``'s own docstring already documents as
identical across platforms for identical input. A finding's own numbers are
still rounded at the point :mod:`vectorpress.validate.narrow_feature` builds
them (§36), the same belt-and-suspenders rule every other detector follows.
"""

from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage as ndi

Point = tuple[float, float]

#: The morphological opening's own structuring-element radius, in pixels,
#: fixed regardless of the narrow-feature threshold's physical value or the
#: document's own scale: :func:`pixel_size_for_min_width` picks
#: the raster's own resolution so the threshold width always spans exactly
#: ``2 * _STRUCTURE_RADIUS_PX`` pixels, so every raster's own quantization
#: error is the same fixed fraction of the threshold it measures against,
#: and a real disk this size (not a degenerate 0- or 1-pixel one) always
#: has a genuine narrowing effect.
_STRUCTURE_RADIUS_PX = 8

#: A one- or two-pixel sliver left over from rasterization's own
#: quantization (a ring edge grazing a pixel row) is not a real narrow
#: feature -- this floors what counts as a genuine opening-removed region,
#: keeping only differences above a negligible area.
_NEGLIGIBLE_DIFF_AREA_PX = 4

#: A morphological opening does not only erase genuinely narrow strips: a
#: disk of radius :data:`_STRUCTURE_RADIUS_PX` cannot fit snugly into any
#: sharp *convex corner* either (nothing sharper than the disk's own
#: curvature can survive erosion there), so every right-angle or acute
#: vertex a piece has -- however unremarkable, a plain rectangle's own four
#: corners included -- sheds a small, roughly compact "corner fillet" region
#: the same opening removes. That region is compact (its own width and
#: length are comparable) where a genuine narrow feature -- a neck, a
#: tentacle, a bridge -- is elongated (much longer than it is wide): this
#: ratio (the square root of the larger to the smaller eigenvalue of the
#: region's own pixel-coordinate covariance -- a rotation-invariant
#: "length/width" measure, so a diagonal neck is judged the same as an
#: axis-aligned one) tells the two apart. Empirically (this module's own
#: fixed-shape test probes), a 90-degree corner's own fillet measures about
#: 2.0 at :data:`_STRUCTURE_RADIUS_PX` = 8; a deliberately narrow neck
#: measures upward of 7. This threshold sits well clear of the corner case
#: on the compact side, while still well below any genuinely elongated
#: narrow region.
_MIN_ELONGATION = 3.0

#: Padding (in pixels) around a piece's own tight bounding box so a feature
#: right at the edge of it still has background on every side for the
#: opening and the connected-component labelling below to see, the same
#: "treat the array edge as background" caution
#: :func:`vectorpress.pipeline._ndimage_cleanup.fill_small_holes` documents
#: for its own border handling.
_PAD_PX = _STRUCTURE_RADIUS_PX + 2


def pixel_size_for_min_width(min_width_user_units: float) -> float:
    """SVG user units per raster pixel so that ``min_width_user_units`` (the
    narrow-feature threshold, already converted from physical inches to this
    document's own user units) spans exactly ``2 * _STRUCTURE_RADIUS_PX``
    pixels."""
    return min_width_user_units / (2 * _STRUCTURE_RADIUS_PX)


@dataclass(frozen=True)
class Raster:
    """One piece's own boolean ink grid plus the mapping back to SVG user
    units: ``mask[row, col]`` is ink at the pixel whose center
    sits at ``(origin_x + (col + 0.5) * pixel_size, origin_y + (row + 0.5) *
    pixel_size)``."""

    mask: NDArray[np.bool_]
    origin_x: float
    origin_y: float
    pixel_size: float


def _disk_structure(radius: int) -> NDArray[np.bool_]:
    """A round structuring element of ``radius`` pixels -- the same shape
    :func:`vectorpress.pipeline._ndimage_cleanup._disk_structure` builds,
    duplicated rather than imported (``validate`` never imports
    ``pipeline``, CLAUDE.md's layering guardrail)."""
    offsets = np.arange(-radius, radius + 1)
    y, x = np.meshgrid(offsets, offsets, indexing="ij")
    result: NDArray[np.bool_] = (x * x + y * y) <= radius * radius
    return result


def rasterize_piece(
    outer_ring: tuple[Point, ...],
    hole_rings: tuple[tuple[Point, ...], ...],
    pixel_size: float,
) -> Raster:
    """``outer_ring`` minus ``hole_rings`` (even-odd) as a boolean
    grid at ``pixel_size`` SVG user units per pixel, tightly cropped to the
    piece's own bounding box plus :data:`_PAD_PX` pixels of background
    padding on every side."""
    rings = (outer_ring, *hole_rings)
    xs = [x for ring in rings for x, _y in ring]
    ys = [y for ring in rings for _x, y in ring]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    width_px = int((max_x - min_x) / pixel_size) + 1 + 2 * _PAD_PX
    height_px = int((max_y - min_y) / pixel_size) + 1 + 2 * _PAD_PX
    origin_x = min_x - _PAD_PX * pixel_size
    origin_y = min_y - _PAD_PX * pixel_size

    edges = [
        (x1, y1, x2, y2)
        for ring in rings
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True)
        if y1 != y2
    ]
    edges_arr = np.array(edges, dtype=np.float64).reshape(-1, 4)

    mask = np.zeros((height_px, width_px), dtype=bool)
    col_centers_x = origin_x + (np.arange(width_px) + 0.5) * pixel_size
    for row in range(height_px):
        row_center_y = origin_y + (row + 0.5) * pixel_size
        y1 = edges_arr[:, 1]
        y2 = edges_arr[:, 3]
        crossing = (y1 > row_center_y) != (y2 > row_center_y)
        if not crossing.any():
            continue
        x1 = edges_arr[crossing, 0]
        cy1 = edges_arr[crossing, 1]
        x2 = edges_arr[crossing, 2]
        cy2 = edges_arr[crossing, 3]
        crossing_xs = np.sort(x1 + (row_center_y - cy1) * (x2 - x1) / (cy2 - cy1))
        counts = np.searchsorted(crossing_xs, col_centers_x, side="right")
        mask[row] = (counts % 2) == 1

    return Raster(mask=mask, origin_x=origin_x, origin_y=origin_y, pixel_size=pixel_size)


def _opened(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """``mask`` after a morphological opening at :data:`_STRUCTURE_RADIUS_PX`
    (erode, then dilate back) -- the same "erase anything narrower than
    this" operation :func:`vectorpress.pipeline._ndimage_cleanup.
    open_narrow_features` performs on a generated cut file's raw ink mask,
    run here purely to measure rather than to clean up."""
    return cast(
        "NDArray[np.bool_]",
        ndi.binary_opening(mask, structure=_disk_structure(_STRUCTURE_RADIUS_PX)),
    )


@dataclass(frozen=True)
class NarrowRegion:
    """One connected region a morphological opening removed from a piece's
    own raster: its own pixel bounding box (row/col, half-open
    on the max side) and the narrowest local width found within it, in
    pixels."""

    min_row: int
    min_col: int
    max_row: int
    max_col: int
    narrowest_width_px: float


def _elongation(rows: NDArray[np.float64], cols: NDArray[np.float64]) -> float:
    """A rotation-invariant "length over width" measure of one region's own
    pixel coordinates: the square root of the ratio between the
    larger and smaller eigenvalue of their covariance matrix, computed
    directly from the closed form for a 2x2 symmetric matrix (``+``, ``-``,
    ``*``, ``/`` and one ``sqrt`` -- no ``numpy.linalg`` call whose own
    routine choice could differ across platforms) -- ``1.0`` for a
    perfectly compact (circular) region, larger the more elongated it is,
    regardless of which way it points."""
    d_rows = rows - rows.mean()
    d_cols = cols - cols.mean()
    n = rows.size
    cov_rr = float((d_rows * d_rows).sum() / n)
    cov_cc = float((d_cols * d_cols).sum() / n)
    cov_rc = float((d_rows * d_cols).sum() / n)
    trace = cov_rr + cov_cc
    determinant = cov_rr * cov_cc - cov_rc * cov_rc
    discriminant = max(trace * trace / 4 - determinant, 0.0)
    half_spread = discriminant**0.5
    lambda_max = trace / 2 + half_spread
    lambda_min = trace / 2 - half_spread
    if lambda_min <= 1e-9:
        return float("inf")
    return (lambda_max / lambda_min) ** 0.5


def narrow_regions(raster: Raster) -> list[NarrowRegion]:
    """Every connected region an opening at :data:`_STRUCTURE_RADIUS_PX`
    erased from ``raster``'s own mask that is both above
    :data:`_NEGLIGIBLE_DIFF_AREA_PX` and elongated enough
    (:data:`_MIN_ELONGATION`) to be a genuine narrow feature rather than a
    sharp convex corner's own opening artifact -- a piece with
    nothing narrower than the threshold anywhere yields none. Ordered by
    document row-major position (top-left corner) for a deterministic
    finding order within one piece."""
    diff = raster.mask & ~_opened(raster.mask)
    if not diff.any():
        return []
    structure = np.ones((3, 3), dtype=bool)
    labels, count = cast("tuple[NDArray[np.int32], int]", ndi.label(diff, structure=structure))
    if count == 0:
        return []

    # A pixel's own local half-width: its own distance to the nearest
    # non-piece pixel (background or hole) in the *original*, unopened
    # mask. Every pixel an opening at this radius erased has distance
    # strictly below the structuring radius (that is exactly why erosion
    # removed it) -- the *largest* such value within one connected region is
    # its own widest surviving cross-section, close to (but always under)
    # the threshold along a region of roughly uniform width, and far more
    # robust than the *smallest* value, which is dominated by the region's
    # own ragged, one-pixel-wide raster boundary rather than the feature's
    # real geometry.
    distance = cast("NDArray[np.float64]", ndi.distance_transform_edt(raster.mask))

    regions: list[NarrowRegion] = []
    for label_id in range(1, count + 1):
        rows, cols = np.nonzero(labels == label_id)
        if rows.size < _NEGLIGIBLE_DIFF_AREA_PX:
            continue
        if _elongation(rows.astype(np.float64), cols.astype(np.float64)) < _MIN_ELONGATION:
            continue
        narrowest_width_px = float(2 * distance[rows, cols].max())
        regions.append(
            NarrowRegion(
                min_row=int(rows.min()),
                min_col=int(cols.min()),
                max_row=int(rows.max()) + 1,
                max_col=int(cols.max()) + 1,
                narrowest_width_px=narrowest_width_px,
            )
        )
    regions.sort(key=lambda region: (region.min_row, region.min_col))
    return regions
