"""End-to-end registration and comparison for calibrated image planes."""
from __future__ import annotations

from typing import Any

import numpy as np
from astropy.wcs import WCS

from app.services.difference import compare_aligned_images
from app.services.reprojection import (
    reproject_to_reference_grid,
    reproject_variance_to_reference_grid,
)


def compare_wcs_images(
    reference: np.ndarray,
    reference_wcs: WCS,
    target: np.ndarray,
    target_wcs: WCS,
    *,
    sigma_threshold: float = 5.0,
    max_candidates: int = 1000,
    minimum_coverage: float = 0.999,
    reference_variance: np.ndarray | None = None,
    target_variance: np.ndarray | None = None,
) -> dict[str, Any]:
    """Reproject target and compare coverage-matched pixels.

    Inputs must already use compatible units and photometric calibration.
    Optional variance maps are propagated through the same bilinear sampling
    weights, assuming independent input pixel errors. PSF matching, photometric
    scaling, and background matching are not performed here.
    """
    reference = np.asarray(reference, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if reference.ndim != 2 or target.ndim != 2:
        raise ValueError("Both inputs must be two-dimensional image planes")
    if not np.isfinite(minimum_coverage) or not 0 < minimum_coverage <= 1:
        raise ValueError("minimum_coverage must be in the interval (0, 1]")
    if (reference_variance is None) != (target_variance is None):
        raise ValueError("Provide both reference_variance and target_variance, or neither")

    aligned_target = reproject_to_reference_grid(
        target, target_wcs, reference_wcs, reference.shape
    )
    source_coverage = np.isfinite(target).astype(np.float64)
    coverage = reproject_to_reference_grid(
        source_coverage, target_wcs, reference_wcs, reference.shape
    )
    coverage = np.clip(coverage, 0.0, 1.0)
    coverage_mask = np.isfinite(coverage) & (coverage >= minimum_coverage)
    common_valid_mask = np.isfinite(reference) & coverage_mask & np.isfinite(aligned_target)

    masked_target = aligned_target.copy()
    masked_target[~coverage_mask] = np.nan
    result = compare_aligned_images(
        reference,
        masked_target,
        sigma_threshold=sigma_threshold,
        max_candidates=max_candidates,
    )
    result.update(
        {
            "aligned_target": aligned_target,
            "coverage_fraction": coverage,
            "coverage_mask": coverage_mask,
            "common_valid_mask": common_valid_mask,
            "reference_shape": tuple(reference.shape),
            "registration": "target_reprojected_to_reference_wcs_bilinear",
            "photometric_calibration": "caller_supplied_compatible_calibration",
            "uncertainty_propagation": False,
            "psf_matching": False,
            "photometric_scaling": False,
        }
    )

    if reference_variance is None or target_variance is None:
        return result

    reference_variance = np.asarray(reference_variance, dtype=np.float64)
    target_variance = np.asarray(target_variance, dtype=np.float64)
    if reference_variance.shape != reference.shape:
        raise ValueError("reference_variance must match the reference image shape")
    if target_variance.shape != target.shape:
        raise ValueError("target_variance must match the target image shape")
    if np.any(reference_variance[np.isfinite(reference_variance)] < 0):
        raise ValueError("reference_variance values must be non-negative")
    if np.any(target_variance[np.isfinite(target_variance)] < 0):
        raise ValueError("target_variance values must be non-negative")

    aligned_target_variance = reproject_variance_to_reference_grid(
        target_variance, target_wcs, reference_wcs, reference.shape
    )
    total_variance = reference_variance + aligned_target_variance
    uncertainty_mask = (
        common_valid_mask
        & np.isfinite(reference_variance)
        & np.isfinite(aligned_target_variance)
        & np.isfinite(total_variance)
        & (total_variance > 0)
    )
    noise_sigma = np.full(reference.shape, np.nan, dtype=np.float32)
    significance = np.full(reference.shape, np.nan, dtype=np.float32)
    candidates: list[dict[str, float | int]] = []
    background_offset: float | None = None
    candidate_count = 0

    if np.any(uncertainty_mask):
        noise_sigma[uncertainty_mask] = np.sqrt(total_variance[uncertainty_mask]).astype(np.float32)
        differences = result["difference"]
        background_offset = float(np.median(differences[uncertainty_mask]))
        significance[uncertainty_mask] = (
            (differences[uncertainty_mask] - background_offset)
            / noise_sigma[uncertainty_mask]
        ).astype(np.float32)
        locations = np.argwhere(
            uncertainty_mask & (np.abs(significance) >= sigma_threshold)
        )
        candidate_count = int(len(locations))
        ranked = sorted(
            locations,
            key=lambda point: abs(float(significance[tuple(point)])),
            reverse=True,
        )[:max_candidates]
        candidates = [
            {
                "y": int(y),
                "x": int(x),
                "significance": float(significance[y, x]),
                "difference": float(differences[y, x]),
            }
            for y, x in ranked
        ]

    result.update(
        {
            "aligned_target_variance": aligned_target_variance,
            "total_variance": total_variance,
            "noise_sigma_map": noise_sigma,
            "significance": significance,
            "uncertainty_valid_mask": uncertainty_mask,
            "uncertainty_background_offset": background_offset,
            "uncertainty_propagation": True,
            "uncertainty_assumption": "independent input pixels; bilinear interpolation weights squared",
            "candidate_count": candidate_count,
            "candidates": candidates,
            "status": "completed" if np.any(uncertainty_mask) else "no_valid_uncertainty_pixels",
        }
    )
    return result
