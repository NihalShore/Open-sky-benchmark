"""Parallax geometry, benchmark targets, and synthetic ePSF injection utilities.

Synthetic source injections are explicitly marked (`synthetic=True`) and are used
strictly for sensitivity/completeness benchmarking against real or modeled backgrounds.
They must never be surfaced as real NASA/IPAC IRSA detections.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from astropy.wcs import WCS

from app.services.spherex_mef import (
    AB_ZERO_POINT_UJY,
    ARCSEC_PER_RADIAN,
    DEFAULT_NATIVE_PIXEL_SCALE_ARCSEC,
    _resample_epsf_stamp,
    extract_forced_photometry,
)

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "benchmark_targets.json"


def load_benchmark_config() -> dict[str, Any]:
    """Load the static SPHEREx instrument & validation-target reference configuration."""
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def estimate_six_month_parallax(
    distance_au: float,
    *,
    baseline_au: float = 2.0,
    pixel_scale_arcsec: float = DEFAULT_NATIVE_PIXEL_SCALE_ARCSEC,
) -> dict[str, float]:
    """Compute annual parallax displacement across a 6-month Earth-orbit baseline.

    For heliocentric distance d >> 1 AU and baseline Δr ≈ 2 AU, the full
    parallactic angle across opposite sides of Earth's orbit is
    2 * arctan(baseline_au / (2 * distance_au)).
    """
    if not np.isfinite(distance_au) or distance_au <= 0:
        raise ValueError("distance_au must be finite and positive")
    if not np.isfinite(baseline_au) or baseline_au <= 0:
        raise ValueError("baseline_au must be finite and positive")
    if not np.isfinite(pixel_scale_arcsec) or pixel_scale_arcsec <= 0:
        raise ValueError("pixel_scale_arcsec must be finite and positive")

    angle_rad = 2.0 * np.arctan(float(baseline_au) / (2.0 * float(distance_au)))
    parallax_arcsec = float(angle_rad * ARCSEC_PER_RADIAN)
    return {
        "distance_au": float(distance_au),
        "baseline_au": float(baseline_au),
        "parallax_arcsec": parallax_arcsec,
        "parallax_arcmin": parallax_arcsec / 60.0,
        "parallax_pixels": parallax_arcsec / float(pixel_scale_arcsec),
        "pixel_scale_arcsec": float(pixel_scale_arcsec),
    }


def inject_synthetic_epsf_source(
    clean_image_mjy_sr: np.ndarray,
    epsf_2d: np.ndarray,
    x_pix: float,
    y_pix: float,
    target_ab_mag: float,
    *,
    pixel_scale_arcsec: float = DEFAULT_NATIVE_PIXEL_SCALE_ARCSEC,
    oversampling: int = 5,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Inject a synthetic point source at (x_pix, y_pix) using an oversampled ePSF.

    Returns `(injected_image, provenance)` with `provenance["synthetic"] == True`.
    """
    image = np.asarray(clean_image_mjy_sr, dtype=np.float64).copy()
    if image.ndim != 2:
        raise ValueError("clean_image_mjy_sr must be two-dimensional")
    if not np.isfinite(target_ab_mag):
        raise ValueError("target_ab_mag must be finite")
    if not np.isfinite(pixel_scale_arcsec) or pixel_scale_arcsec <= 0:
        raise ValueError("pixel_scale_arcsec must be finite and positive")

    omega_pix_sr = (float(pixel_scale_arcsec) / ARCSEC_PER_RADIAN) ** 2
    mjy_sr_to_ujy_per_pix = 1e12 * omega_pix_sr
    flux_ujy = float(AB_ZERO_POINT_UJY * (10.0 ** (-0.4 * float(target_ab_mag))))
    total_mjy_sr_pix = flux_ujy / mjy_sr_to_ujy_per_pix

    ix, iy = int(np.round(x_pix)), int(np.round(y_pix))
    dx, dy = float(x_pix) - ix, float(y_pix) - iy
    stamp = _resample_epsf_stamp(epsf_2d, oversampling, dx, dy)
    half = stamp.shape[0] // 2

    ny, nx = image.shape
    y0, y1 = max(0, iy - half), min(ny, iy + half + 1)
    x0, x1 = max(0, ix - half), min(nx, ix + half + 1)
    if y1 <= y0 or x1 <= x0:
        raise ValueError("Target pixel lies completely outside image bounds")

    py0, px0 = y0 - (iy - half), x0 - (ix - half)
    sub_stamp = stamp[py0 : py0 + (y1 - y0), px0 : px0 + (x1 - x0)]
    image[y0:y1, x0:x1] += total_mjy_sr_pix * sub_stamp

    return image, {
        "synthetic": True,
        "injected_ab_mag": float(target_ab_mag),
        "injected_flux_ujy": flux_ujy,
        "x_pix": float(x_pix),
        "y_pix": float(y_pix),
        "oversampling": int(oversampling),
    }


def evaluate_injection_recovery(
    background_image_mjy_sr: np.ndarray,
    variance_mjy_sr2: np.ndarray,
    wcs: WCS,
    epsf_2d: np.ndarray,
    ab_magnitudes: list[float],
    *,
    x_pix: float | None = None,
    y_pix: float | None = None,
    oversampling: int = 5,
    pixel_scale_arcsec: float = DEFAULT_NATIVE_PIXEL_SCALE_ARCSEC,
    snr_threshold: float = 5.0,
) -> dict[str, Any]:
    """Measure ePSF-weighted flux recovery and SNR across trial AB magnitudes."""
    bg = np.asarray(background_image_mjy_sr, dtype=np.float64)
    var = np.asarray(variance_mjy_sr2, dtype=np.float64)
    if bg.ndim != 2 or bg.shape != var.shape:
        raise ValueError("background_image_mjy_sr and variance_mjy_sr2 must share a 2-D shape")
    if not ab_magnitudes:
        raise ValueError("At least one AB magnitude is required")

    ny, nx = bg.shape
    tx = (nx - 1) / 2.0 if x_pix is None else float(x_pix)
    ty = (ny - 1) / 2.0 if y_pix is None else float(y_pix)

    trials: list[dict[str, Any]] = []
    for mag in ab_magnitudes:
        injected, inj_meta = inject_synthetic_epsf_source(
            bg,
            epsf_2d,
            tx,
            ty,
            mag,
            pixel_scale_arcsec=pixel_scale_arcsec,
            oversampling=oversampling,
        )
        frame = {
            "clean_image_mjy_sr": injected,
            "variance_mjy_sr2": var,
            "x_cutout": tx,
            "y_cutout": ty,
            "pixel_scale_arcsec": (float(pixel_scale_arcsec), float(pixel_scale_arcsec)),
            "wcs": wcs,
            "target_in_frame": True,
            "dichroic_impacted": False,
            "zodi_subtracted": True,
            "epsf": epsf_2d,
            "epsf_oversampling": int(oversampling),
            "source_archive": "Synthetic injection into background",
        }
        phot = extract_forced_photometry(
            frame,
            radius_pix=1.5,
            use_epsf=True,
            subtract_local_background=False,
        )
        recovered_mag = phot["ab_mag"]
        trials.append(
            {
                "injected_ab_mag": float(mag),
                "injected_flux_ujy": inj_meta["injected_flux_ujy"],
                "recovered_flux_ujy": phot["flux_ujy"],
                "flux_err_ujy": phot["flux_err_ujy"],
                "recovered_ab_mag": recovered_mag,
                "mag_error": (recovered_mag - float(mag)) if recovered_mag is not None else None,
                "snr": phot["snr"],
                "detected": bool(phot["snr"] >= snr_threshold),
                "synthetic": True,
            }
        )

    return {
        "synthetic_injection": True,
        "snr_threshold": float(snr_threshold),
        "trial_count": len(trials),
        "detected_count": sum(1 for item in trials if item["detected"]),
        "trials": trials,
    }
