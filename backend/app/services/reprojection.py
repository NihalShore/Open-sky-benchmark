"""WCS-based image and variance reprojection onto a reference grid."""
from __future__ import annotations

from numbers import Integral

import numpy as np
from astropy.wcs import WCS


class ReprojectionError(ValueError):
    """Raised when image planes cannot be reprojected safely."""


def _project_grid(
    source_shape: tuple[int, int],
    image_wcs: WCS,
    reference_wcs: WCS,
    output_shape: tuple[int, int],
):
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

    height, width = source_shape
    edge_tolerance = 1e-6
    inside = (
        np.isfinite(source_x)
        & np.isfinite(source_y)
        & (source_x >= -edge_tolerance)
        & (source_y >= -edge_tolerance)
        & (source_x <= width - 1 + edge_tolerance)
        & (source_y <= height - 1 + edge_tolerance)
    )
    x = np.clip(source_x[inside], 0, width - 1)
    y = np.clip(source_y[inside], 0, height - 1)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    dx = x - x0
    dy = y - y0
    weights = (
        (1 - dx) * (1 - dy),
        dx * (1 - dy),
        (1 - dx) * dy,
        dx * dy,
    )
    indices = ((y0, x0), (y0, x1), (y1, x0), (y1, x1))
    return output_shape, inside, indices, weights


def reproject_to_reference_grid(
    image: np.ndarray,
    image_wcs: WCS,
    reference_wcs: WCS,
    output_shape: tuple[int, int],
) -> np.ndarray:
    """Bilinearly sample an image on the reference celestial pixel grid."""
    image = np.asarray(image, dtype=np.float64)
    if image.ndim != 2:
        raise ReprojectionError("Input image must be two-dimensional")
    output_shape, inside, indices, weights = _project_grid(
        image.shape, image_wcs, reference_wcs, output_shape
    )
    output = np.full(output_shape, np.nan, dtype=np.float32)
    if not np.any(inside):
        return output

    numerator = np.zeros(weights[0].shape, dtype=np.float64)
    denominator = np.zeros(weights[0].shape, dtype=np.float64)
    for (yy, xx), weight in zip(indices, weights):
        values = image[yy, xx]
        usable = np.isfinite(values) & (weight > 0)
        numerator[usable] += values[usable] * weight[usable]
        denominator[usable] += weight[usable]

    sampled = np.full(weights[0].shape, np.nan, dtype=np.float32)
    usable = denominator > 0
    sampled[usable] = (numerator[usable] / denominator[usable]).astype(np.float32)
    output[inside] = sampled
    return output


def reproject_variance_to_reference_grid(
    variance: np.ndarray,
    image_wcs: WCS,
    reference_wcs: WCS,
    output_shape: tuple[int, int],
) -> np.ndarray:
    """Reproject independent pixel variances through bilinear interpolation.

    For normalized interpolation weights w_i, output variance is
    sum(w_i**2 * variance_i). Missing source pixels are omitted and the
    remaining weights are normalized in the same way as image reprojection.
    """
    variance = np.asarray(variance, dtype=np.float64)
    if variance.ndim != 2:
        raise ReprojectionError("Variance map must be two-dimensional")
    finite = np.isfinite(variance)
    if np.any(variance[finite] < 0):
        raise ReprojectionError("Variance values must be non-negative")

    output_shape, inside, indices, weights = _project_grid(
        variance.shape, image_wcs, reference_wcs, output_shape
    )
    output = np.full(output_shape, np.nan, dtype=np.float32)
    if not np.any(inside):
        return output

    numerator = np.zeros(weights[0].shape, dtype=np.float64)
    denominator = np.zeros(weights[0].shape, dtype=np.float64)
    for (yy, xx), weight in zip(indices, weights):
        values = variance[yy, xx]
        usable = np.isfinite(values) & (weight > 0)
        numerator[usable] += values[usable] * np.square(weight[usable])
        denominator[usable] += weight[usable]

    sampled = np.full(weights[0].shape, np.nan, dtype=np.float32)
    usable = denominator > 0
    sampled[usable] = (numerator[usable] / np.square(denominator[usable])).astype(np.float32)
    output[inside] = sampled
    return output
