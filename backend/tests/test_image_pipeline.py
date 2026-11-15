import numpy as np
from astropy.wcs import WCS

from app.services.image_pipeline import compare_wcs_images


def make_wcs():
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crpix = [20.0, 20.0]
    wcs.wcs.crval = [120.0, 30.0]
    wcs.wcs.cdelt = [-0.001, 0.001]
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
