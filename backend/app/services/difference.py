"""Coverage-aware difference imaging for already aligned image planes."""
from __future__ import annotations

from typing import Any

import numpy as np


class DifferenceImageError(ValueError):
    """Raised when two image planes cannot be compared safely."""


def _compact_float_array(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Use float32 when finite values fit safely; preserve float64 otherwise."""
    finite_vals = values[valid]
    if finite_vals.size and np.max(np.abs(finite_vals)) > float(np.finfo(np.float32).max) * 0.5:
        out = np.full(values.shape, np.nan, dtype=np.float64)
        out[valid] = finite_vals
        return out
    out = np.full(values.shape, np.nan, dtype=np.float32)
    out[valid] = finite_vals.astype(np.float32)
    return out


def compare_aligned_images(
    reference: np.ndarray,
    target: np.ndarray,
    *,
    sigma_threshold: float = 5.0,
    max_candidates: int = 1000,
) -> dict[str, Any]:
    """Subtract compatible same-grid images and rank robust residuals.

    A zero MAD is treated as unresolved noise rather than replaced with a
    standard deviation that a small number of outliers can dominate.
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
    if np.count_nonzero(valid) < 3:
        raise DifferenceImageError("At least three overlapping finite pixels are required")

    diff_64 = np.full(reference.shape, np.nan, dtype=np.float64)
    residuals = target[valid] - reference[valid]
    if not np.all(np.isfinite(residuals)):
        raise DifferenceImageError("Difference produced non-finite residuals")
    diff_64[valid] = residuals
    difference = _compact_float_array(diff_64, valid)

    center = float(np.median(residuals))
    mad = float(np.median(np.abs(residuals - center)))
    robust_sigma = 1.4826 * mad
    significance = np.full(reference.shape, np.nan, dtype=np.float32)

    if not np.isfinite(robust_sigma) or robust_sigma <= np.finfo(float).tiny:
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

    sig_residuals = (residuals - center) / robust_sigma
    sig_64 = np.full(reference.shape, np.nan, dtype=np.float64)
    sig_64[valid] = sig_residuals
    significance = _compact_float_array(sig_64, valid)

    valid_y, valid_x = np.nonzero(valid)
    exceed = np.abs(sig_residuals) >= sigma_threshold
    hit_count = int(np.count_nonzero(exceed))

    candidates: list[dict[str, float | int]] = []
    if hit_count > 0:
        hit_idx = np.flatnonzero(exceed)
        scores = np.abs(sig_residuals[hit_idx])
        if hit_count > max_candidates:
            top_local = np.argpartition(scores, -max_candidates)[-max_candidates:]
            top_local = top_local[np.argsort(scores[top_local])[::-1]]
        else:
            top_local = np.argsort(scores)[::-1]
        chosen = hit_idx[top_local]
        candidates = [
            {
                "y": int(valid_y[idx]),
                "x": int(valid_x[idx]),
                "significance": float(sig_residuals[idx]),
                "difference": float(residuals[idx]),
            }
            for idx in chosen
        ]

    return {
        "difference": difference,
        "significance": significance,
        "valid_mask": valid,
        "background_offset": center,
        "robust_sigma": robust_sigma,
        "candidate_count": hit_count,
        "candidates": candidates,
        "status": "completed",
        "synthetic": False,
    }
