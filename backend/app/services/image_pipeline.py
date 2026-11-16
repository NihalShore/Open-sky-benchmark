"""End-to-end registration and comparison for two calibrated image planes."""
from __future__ import annotations

from typing import Any

import numpy as np
from astropy.wcs import WCS

from app.services.difference import compare_aligned_images
from app.services.reprojection import reproject_with_coverage


def compare_wcs_images(
    reference: np.ndarray,
    reference_wcs: WCS,
    target: np.ndarray,
    target_wcs: WCS,
    *,
    sigma_threshold: float = 5.0,
    max_candidates: int = 1000,
    minimum_coverage: float = 0.999,
) -> dict[str, Any]:
    """Reproject target onto reference grid, then compare common valid pixels.

    The inputs must already be in compatible surface-brightness units and
    photometrically calibrated. This routine does not perform PSF matching,
    photometric scaling, background matching, or uncertainty propagation.
    """
    reference = np.asarray(reference, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if reference.ndim != 2 or target.ndim != 2:
        raise ValueError("Both inputs must be two-dimensional image planes")
    if not np.isfinite(minimum_coverage) or not 0 < minimum_coverage <= 1:
        raise ValueError("minimum_coverage must be in the interval (0, 1]")

    aligned_target, coverage, diagnostics = reproject_with_coverage(
        target, target_wcs, reference_wcs, reference.shape
    )
    coverage_mask = np.isfinite(coverage) & (coverage >= minimum_coverage)
    common_valid_mask = np.isfinite(reference) & coverage_mask & np.isfinite(aligned_target)

    masked_target = aligned_target.astype(np.float64, copy=True)
    masked_target[~coverage_mask] = np.nan
    result = compare_aligned_images(
        reference,
        masked_target,
        sigma_threshold=sigma_threshold,
        max_candidates=max_candidates,
    )

    warnings_list: list[str] = []
    ratio = diagnostics.get("pixel_scale_ratio")
    if ratio is not None and (ratio < 0.8 or ratio > 1.25):
        warnings_list.append(
            f"Target/reference pixel scale ratio is {ratio:.3f}; bilinear resampling does not conserve flux across mismatched pixel scales."
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
            "flux_conservation": "surface_brightness_bilinear_not_flux_conserving",
            "uncertainty_propagation": False,
            "psf_matching": False,
            **diagnostics,
            "warnings": warnings_list,
        }
    )
    return result
