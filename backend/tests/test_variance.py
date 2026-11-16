import numpy as np
import pytest
from astropy.wcs import WCS

from app.services.image_pipeline import compare_wcs_images
from app.services.reprojection import ReprojectionError, reproject_variance_to_reference_grid


def make_wcs(crpix=(5.0, 5.0), crval=(120.0, 30.0)):
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crpix = crpix
    wcs.wcs.crval = crval
    wcs.wcs.cdelt = [-0.01, 0.01]
    return wcs


def test_identity_wcs_preserves_variance_map():
    variance = np.full((16, 16), 3.5, dtype=float)
    result = reproject_variance_to_reference_grid(
        variance, make_wcs(), make_wcs(), variance.shape
    )
    np.testing.assert_allclose(result, variance, atol=1e-6)


def test_half_pixel_interpolation_squares_weights():
    variance = np.ones((20, 20), dtype=float)
    result = reproject_variance_to_reference_grid(
        variance,
        make_wcs(),
        make_wcs(crpix=(5.5, 5.0)),
        variance.shape,
    )
    assert result[10, 10] == pytest.approx(0.5, abs=1e-4)


def test_variance_reprojection_rejects_negative_values():
    variance = np.ones((8, 8), dtype=float)
    variance[3, 3] = -1
    with pytest.raises(ReprojectionError, match="non-negative"):
        reproject_variance_to_reference_grid(
            variance, make_wcs(), make_wcs(), variance.shape
        )


def test_comparison_uses_supplied_variance_maps():
    reference = np.zeros((40, 40), dtype=float)
    target = np.zeros((40, 40), dtype=float)
    target[18, 23] = 10.0
    variance = np.ones((40, 40), dtype=float)

    result = compare_wcs_images(
        reference,
        make_wcs(),
        target,
        make_wcs(),
        sigma_threshold=5.0,
        reference_variance=variance,
        target_variance=variance,
    )

    assert result["uncertainty_propagation"] is True
    assert result["noise_sigma_map"][18, 23] == pytest.approx(np.sqrt(2), abs=1e-6)
    assert any(item["x"] == 23 and item["y"] == 18 for item in result["candidates"])
    assert result["psf_matching"] is False
    assert result["photometric_scaling"] is False


def test_comparison_requires_both_variance_maps():
    image = np.zeros((8, 8), dtype=float)
    with pytest.raises(ValueError, match="both"):
        compare_wcs_images(
            image, make_wcs(), image, make_wcs(), reference_variance=image
        )
