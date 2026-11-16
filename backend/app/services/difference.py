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
    """Subtract compatible same-grid images and rank robust residuals.

    Statistics remain in float64 so small physical flux units and large
    finite values are not lost to an arbitrary absolute epsilon or float32
    conversion.
    """
    reference = np.asarray(reference, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)

    if reference.ndim != 2 or target.ndim != 2:
        raise DifferenceImageError("Both inputs must be two-dimensional image planes")
    if reference.shape != target.shape:
        raise DifferenceImageError("Image planes must have identical shapes")
    if not np.isfinite(sigma_threshold) or sigma_threshold <= 0:
        raise DifferenceImageError("sigma_threshold must be positive and finite")
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or max_candidates < 1:
        raise DifferenceImageError("max_candidates must be a positive integer")

    valid = np.isfinite(reference) & np.isfinite(target)
    difference = np.full(reference.shape, np.nan, dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        difference[valid] = target[valid] - reference[valid]
    valid &= np.isfinite(difference)
    difference[~valid] = np.nan
    if np.count_nonzero(valid) < 3:
        raise DifferenceImageError("At least three overlapping finite pixels are required")

    residuals = difference[valid]
    center = float(np.median(residuals))
    mad = float(np.median(np.abs(residuals - center)))
    robust_sigma = 1.4826 * mad
    significance = np.full(reference.shape, np.nan, dtype=np.float64)

    if not np.isfinite(robust_sigma) or robust_sigma <= 0.0:
        return {
            "difference": difference,
            "significance": significance,
            "valid_mask": valid,
            "background_offset": center,
            "robust_sigma": 0.0,
            "candidate_count": 0,
            "candidates": [],
            "status": "no_resolvable_residual_scatter",
            "synthetic": False,
        }

    significance[valid] = (difference[valid] - center) / robust_sigma
    candidate_mask = valid & (np.abs(significance) >= sigma_threshold)
    locations = np.argwhere(candidate_mask)
    scores = np.abs(significance[candidate_mask])
    if len(locations) > max_candidates:
        selected = np.argpartition(scores, -max_candidates)[-max_candidates:]
        locations = locations[selected]
    ranked = sorted(
        locations,
        key=lambda point: abs(float(significance[tuple(point)])),
        reverse=True,
    )

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
        "candidate_count": int(np.count_nonzero(candidate_mask)),
        "candidates": candidates,
        "status": "completed",
        "synthetic": False,
    }
