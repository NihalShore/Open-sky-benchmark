import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.wcs import WCS

from app.services.image_pipeline import compare_wcs_images


def make_wcs(cdelt=(-0.001, 0.001)):
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crpix = [20.0, 20.0]
    wcs.wcs.crval = [120.0, 30.0]
    wcs.wcs.cdelt = cdelt
    return wcs


def test_pipeline_reprojects_masks_and_finds_change():
    rng = np.random.default_rng(31)
    reference = rng.normal(0.0, 1.0, (40, 40))
    target = rng.normal(0.0, 1.0, (40, 40))
    target[18, 23] += 20.0
    target[0, 0] = np.nan

    result = compare_wcs_images(
        reference, make_wcs(), target, make_wcs(), sigma_threshold=5.0
    )

    assert result["registration"] == "target_reprojected_to_reference_wcs_bilinear"
    assert result["coverage_mask"][10, 10]
    assert not result["coverage_mask"][0, 0]
    assert not result["common_valid_mask"][0, 0]
    assert np.isnan(result["difference"][0, 0])
    assert any(item["x"] == 23 and item["y"] == 18 for item in result["candidates"])
    assert result["uncertainty_propagation"] is False
    assert result["pixel_scale_ratio"] == 1.0
    assert result["warnings"] == []


def test_pipeline_warns_on_pixel_scale_mismatch():
    rng = np.random.default_rng(42)
    ref = rng.normal(0.0, 1.0, (40, 40))
    tgt = rng.normal(0.0, 1.0, (20, 20))
    tgt_wcs = make_wcs(cdelt=(-0.0025, 0.0025))
    tgt_wcs.wcs.crpix = [10.0, 10.0]

    result = compare_wcs_images(ref, make_wcs(), tgt, tgt_wcs, sigma_threshold=5.0)

    assert result["pixel_scale_ratio"] > 2.0
    assert any("pixel scale" in w.lower() for w in result["warnings"])


def test_pipeline_supports_galactic_to_icrs_registration():
    rng = np.random.default_rng(7)
    ref_wcs = make_wcs()
    gal = SkyCoord(ra=120.0 * u.deg, dec=30.0 * u.deg, frame="icrs").galactic
    gal_wcs = WCS(naxis=2)
    gal_wcs.wcs.ctype = ["GLON-TAN", "GLAT-TAN"]
    gal_wcs.wcs.crpix = [20.0, 20.0]
    gal_wcs.wcs.crval = [gal.l.deg, gal.b.deg]
    gal_wcs.wcs.cdelt = [-0.001, 0.001]

    reference = rng.normal(0.0, 0.1, (40, 40))
    target = rng.normal(0.0, 0.1, (40, 40))

    result = compare_wcs_images(reference, ref_wcs, target, gal_wcs, sigma_threshold=5.0)

    assert result["common_valid_mask"].sum() > 200
