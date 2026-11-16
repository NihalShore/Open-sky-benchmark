import numpy as np
import pytest
from astropy.wcs import WCS

from app.services.parallax_benchmark import (
    estimate_six_month_parallax,
    evaluate_injection_recovery,
    inject_synthetic_epsf_source,
    load_benchmark_config,
)


def _make_gaussian_epsf(size: int = 33, oversampling: int = 5) -> np.ndarray:
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[:size, :size]
    sigma_sub = 0.65 * oversampling
    psf = np.exp(-0.5 * (((xx - c) ** 2 + (yy - c) ** 2) / (sigma_sub ** 2)))
    return psf / np.sum(psf)


def test_estimate_six_month_parallax_matches_physical_geometry():
    est = estimate_six_month_parallax(400.0)
    assert est["parallax_arcsec"] == pytest.approx(1031.32, abs=0.2)
    assert est["parallax_pixels"] == pytest.approx(1031.32 / 6.15, abs=0.1)


def test_load_benchmark_config_contains_documented_validation_targets():
    cfg = load_benchmark_config()
    ids = {target["id"] for target in cfg["validation_targets"]}
    assert {"3I/ATLAS", "136472", "136199", "136108", "134340"}.issubset(ids)
    assert cfg["instrument"]["channels_total"] == 102
    assert cfg["instrument"]["dr1_cube_blank_channels"] == [51, 52]


def test_inject_synthetic_epsf_source_marks_synthetic_and_conserves_flux():
    bg = np.zeros((21, 21), dtype=np.float64)
    epsf = _make_gaussian_epsf()

    injected, meta = inject_synthetic_epsf_source(bg, epsf, 10.3, 10.7, 17.0)
    assert meta["synthetic"] is True
    assert meta["injected_ab_mag"] == 17.0
    # 1 pixel at 6.15" -> 888.98 uJy per (MJy/sr * pixel)
    expected_sum = meta["injected_flux_ujy"] / (1e12 * (6.15 / 206264.80624709636) ** 2)
    assert np.sum(injected) == pytest.approx(expected_sum, rel=1e-3)


def test_evaluate_injection_recovery_separates_bright_and_faint_limits():
    rng = np.random.default_rng(123)
    # Realistic single-pass 5-sigma depth ~ 18.8 AB mag -> 1-sigma flux ~ 22 uJy -> ~0.025 MJy/sr per pixel
    noise_sigma = 0.015
    bg = rng.normal(0.0, noise_sigma, (25, 25))
    var = np.full((25, 25), noise_sigma ** 2, dtype=np.float64)
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crpix = [13.0, 13.0]
    wcs.wcs.crval = [120.0, 30.0]
    wcs.wcs.cdelt = [-6.15 / 3600.0, 6.15 / 3600.0]

    scorecard = evaluate_injection_recovery(
        bg, var, wcs, _make_gaussian_epsf(), [16.0, 17.5, 22.5], snr_threshold=5.0
    )

    assert scorecard["synthetic_injection"] is True
    by_mag = {item["injected_ab_mag"]: item for item in scorecard["trials"]}
    assert by_mag[16.0]["detected"] is True
    assert by_mag[16.0]["mag_error"] == pytest.approx(0.0, abs=0.1)
    assert by_mag[22.5]["detected"] is False
