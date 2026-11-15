"""WCS-based image reprojection onto a reference pixel grid."""
from __future__ import annotations

from numbers import Integral

import numpy as np
from astropy.wcs import WCS


class ReprojectionError(ValueError):
    """Raised when image planes cannot be reprojected safely."""


def reproject_to_reference_grid(
    image: np.ndarray,
    image_wcs: WCS,
    reference_wcs: WCS,
    output_shape: tuple[int, int],
) -> np.ndarray:
    """Bilinearly sample an image on the pixel grid described by reference_wcs.

    Both WCS objects must describe celestial coordinates. Pixels outside the
    input image, and output pixels with no finite input support, are NaN.
    """
    image = np.asarray(image, dtype=np.float64)
    if image.ndim != 2:
        raise ReprojectionError("Input image must be two-dimensional")
    if (
        not isinstance(output_shape, (tuple, list))
        or len(output_shape) != 2
        or any(isinstance(size, bool) or not isinstance(size, Integral) or size < 1 for size in output_shape)
    ):
        raise ReprojectionError("output_shape must contain two positive integer dimensions")
    output_shape = tuple(int(size) for size in output_shape)

    try:
        source_wcs = image_wcs.celestial
        target_wcs = reference_wcs.celestial
        if not source_wcs.has_celestial or not target_wcs.has_celestial:
            raise ReprojectionError("Both WCS objects must contain celestial axes")

        yy, xx = np.indices(output_shape, dtype=np.float64)
        world_lon, world_lat = target_wcs.pixel_to_world_values(xx, yy)
        source_x, source_y = source_wcs.world_to_pixel_values(world_lon, world_lat)
    except ReprojectionError:
        raise
    except Exception as exc:
        raise ReprojectionError(f"Could not transform WCS coordinates: {exc}") from exc

    height, width = image.shape
    inside = (
        np.isfinite(source_x)
        & np.isfinite(source_y)
        & (source_x >= 0)
        & (source_y >= 0)
        & (source_x <= width - 1)
        & (source_y <= height - 1)
    )
    output = np.full(output_shape, np.nan, dtype=np.float32)
    if not np.any(inside):
        return output

    x = np.clip(source_x[inside], 0, width - 1)
    y = np.clip(source_y[inside], 0, height - 1)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    dx = x - x0
    dy = y - y0

    samples = (
        (image[y0, x0], (1 - dx) * (1 - dy)),
        (image[y0, x1], dx * (1 - dy)),
        (image[y1, x0], (1 - dx) * dy),
        (image[y1, x1], dx * dy),
    )
    numerator = np.zeros(x.shape, dtype=np.float64)
    denominator = np.zeros(x.shape, dtype=np.float64)
    for values, weights in samples:
        usable = np.isfinite(values) & (weights > 0)
        numerator[usable] += values[usable] * weights[usable]
        denominator[usable] += weights[usable]

    sampled = np.full(x.shape, np.nan, dtype=np.float32)
    usable = denominator > 0
    sampled[usable] = (numerator[usable] / denominator[usable]).astype(np.float32)
    output[inside] = sampled
    return output
