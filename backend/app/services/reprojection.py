"""WCS-based image reprojection onto a reference pixel grid."""
from __future__ import annotations

from numbers import Integral
from typing import Any

import numpy as np
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales, wcs_to_celestial_frame


class ReprojectionError(ValueError):
    """Raised when image planes cannot be reprojected safely."""


def _compute_bilinear_grid(
    source_shape: tuple[int, int],
    image_wcs: WCS,
    reference_wcs: WCS,
    output_shape: tuple[int, int],
) -> tuple[
    tuple[int, int],
    np.ndarray,
    tuple[tuple[np.ndarray, np.ndarray], ...],
    tuple[np.ndarray, ...],
    dict[str, Any],
]:
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
        # Transform via SkyCoord so differing frames (e.g. Galactic vs ICRS)
        # and swapped axis orders (DEC/RA vs RA/DEC) are properly aligned.
        sky = target_wcs.pixel_to_world(xx, yy)
        source_x, source_y = source_wcs.world_to_pixel(sky)
        src_scales = proj_plane_pixel_scales(source_wcs) * 3600.0
        ref_scales = proj_plane_pixel_scales(target_wcs) * 3600.0
        src_scale = float(np.sqrt(src_scales[0] * src_scales[1]))
        ref_scale = float(np.sqrt(ref_scales[0] * ref_scales[1]))
        diagnostics = {
            "source_frame": wcs_to_celestial_frame(source_wcs).name,
            "reference_frame": wcs_to_celestial_frame(target_wcs).name,
            "source_pixel_scale_arcsec": src_scale,
            "reference_pixel_scale_arcsec": ref_scale,
            "pixel_scale_ratio": float(src_scale / ref_scale) if ref_scale > 0 else None,
        }
    except ReprojectionError:
        raise
    except Exception as exc:
        raise ReprojectionError(f"Could not transform WCS coordinates: {exc}") from exc

    height, width = source_shape
    # WCS round-trips can put an exact edge pixel a few ulps outside the grid.
    edge_tolerance = 1e-6
    inside = (
        np.isfinite(source_x)
        & np.isfinite(source_y)
        & (source_x >= -edge_tolerance)
        & (source_y >= -edge_tolerance)
        & (source_x <= width - 1 + edge_tolerance)
        & (source_y <= height - 1 + edge_tolerance)
    )
    if not np.any(inside):
        return output_shape, inside, (), (), diagnostics

    x = np.clip(source_x[inside], 0, width - 1)
    y = np.clip(source_y[inside], 0, height - 1)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    dx = x - x0
    dy = y - y0

    indices = ((y0, x0), (y0, x1), (y1, x0), (y1, x1))
    weights = (
        (1.0 - dx) * (1.0 - dy),
        dx * (1.0 - dy),
        (1.0 - dx) * dy,
        dx * dy,
    )
    return output_shape, inside, indices, weights, diagnostics


def _sample_from_grid(
    image: np.ndarray,
    output_shape: tuple[int, int],
    inside: np.ndarray,
    indices: tuple[tuple[np.ndarray, np.ndarray], ...],
    weights: tuple[np.ndarray, ...],
) -> tuple[np.ndarray, np.ndarray]:
    output = np.full(output_shape, np.nan, dtype=np.float32)
    coverage = np.zeros(output_shape, dtype=np.float32)
    if not np.any(inside):
        return output, coverage

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
    coverage[inside] = np.clip(denominator, 0.0, 1.0).astype(np.float32)
    return output, coverage


def reproject_with_coverage(
    image: np.ndarray,
    image_wcs: WCS,
    reference_wcs: WCS,
    output_shape: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Bilinearly sample an image and return (reprojected, coverage_fraction, diagnostics)."""
    image = np.asarray(image, dtype=np.float64)
    if image.ndim != 2:
        raise ReprojectionError("Input image must be two-dimensional")
    out_shape, inside, indices, weights, diagnostics = _compute_bilinear_grid(
        image.shape, image_wcs, reference_wcs, output_shape
    )
    reprojected, coverage = _sample_from_grid(image, out_shape, inside, indices, weights)
    return reprojected, coverage, diagnostics


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
    reprojected, _, _ = reproject_with_coverage(
        image, image_wcs, reference_wcs, output_shape
    )
    return reprojected
