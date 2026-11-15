"""Coverage-aware difference imaging for already aligned image planes."""
from __future__ import annotations

from typing import Any

import numpy as np


class DifferenceImageError(ValueError):
    """Raised when two image planes cannot be compared safely."""


def compare_aligned_images(
    reference: np.ndarray,
    target: np.ndarray,
    *,
    sigma_threshold: float = 5.0,
    max_candidates: int = 1000,
) -> dict[str, Any]:
    """Subtract same-grid images and flag robust high-significance residuals.

    Inputs must already share a pixel grid, units, and compatible calibration.
    This function does not estimate astrometric shifts or photometric scaling.
    """
    reference = np.asarray(reference, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)

    if reference.ndim != 2 or target.ndim != 2:
        raise DifferenceImageError("Both inputs must be two-dimensional image planes")
    if reference.shape != target.shape:
        raise DifferenceImageError("Image planes must have identical shapes")
    if not np.isfinite(sigma_threshold) or sigma_threshold <= 0:
        raise DifferenceImageError("sigma_threshold must be positive and finite")
    if max_candidates < 1:
        raise DifferenceImageError("max_candidates must be at least 1")

    valid = np.isfinite(reference) & np.isfinite(target)
    valid_count = int(np.count_nonzero(valid))
    if valid_count < 3:
        raise DifferenceImageError("At least three overlapping finite pixels are required")

    difference = np.full(reference.shape, np.nan, dtype=np.float32)
    difference[valid] = (target[valid] - reference[valid]).astype(np.float32)

    residuals = difference[valid].astype(np.float64)
    center = float(np.median(residuals))
    mad = float(np.median(np.abs(residuals - center)))
    robust_sigma = 1.4826 * mad
    if robust_sigma <= np.finfo(float).eps:
        robust_sigma = float(np.std(residuals - center))

    if not np.isfinite(robust_sigma) or robust_sigma <= np.finfo(float).eps:
        return {
            "difference": difference,
            "valid_mask": valid,
            "background_offset": center,
            "robust_sigma": 0.0,
            "candidate_count": 0,
            "candidates": [],
            "status": "no_resolvable_residual_scatter",
            "synthetic": False,
        }

    significance = np.full(reference.shape, np.nan, dtype=np.float32)
    significance[valid] = ((difference[valid] - center) / robust_sigma).astype(np.float32)
    candidate_mask = valid & (np.abs(significance) >= sigma_threshold)
    locations = np.argwhere(candidate_mask)
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
            "difference": float(difference[y, x]),
        }
        for y, x in ranked
    ]

    return {
        "difference": difference,
        "significance": significance,
        "valid_mask": valid,
        "background_offset": center,
        "robust_sigma": robust_sigma,
        "candidate_count": int(len(locations)),
        "candidates": candidates,
        "status": "completed",
        "synthetic": False,
    }
