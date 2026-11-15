import numpy as np
import pytest
from astropy.wcs import WCS

from app.services.reprojection import ReprojectionError, reproject_to_reference_grid


def make_wcs(crpix=(5.0, 5.0), crval=(120.0, 30.0)):
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crpix = crpix
    wcs.wcs.crval = crval
    wcs.wcs.cdelt = [-0.01, 0.01]
    return wcs


def test_identical_wcs_preserves_image_values():
    image = np.arange(100, dtype=float).reshape(10, 10)
    result = reproject_to_reference_grid(image, make_wcs(), make_wcs(), image.shape)

    np.testing.assert_allclose(result, image, atol=1e-5)


def test_reprojection_maps_shifted_reference_grid():
    image = np.tile(np.arange(10, dtype=float), (10, 1))
    source_wcs = make_wcs()
    reference_wcs = make_wcs(crpix=(6.0, 5.0))

    result = reproject_to_reference_grid(
        image, source_wcs, reference_wcs, (10, 10)
    )

    assert result[4, 4] == pytest.approx(3.0, abs=1e-3)


def test_reprojection_keeps_nan_when_no_input_support():
    image = np.full((5, 5), np.nan)
    result = reproject_to_reference_grid(image, make_wcs(crpix=(3, 3)), make_wcs(crpix=(3, 3)), image.shape)

    assert np.isnan(result).all()


def test_reprojection_rejects_non_image_input():
    with pytest.raises(ReprojectionError, match="two-dimensional"):
        reproject_to_reference_grid(np.zeros(3), make_wcs(), make_wcs(), (3, 3))


def test_reprojection_rejects_non_celestial_wcs():
    plain_wcs = WCS(naxis=2)
    with pytest.raises(ReprojectionError, match="celestial"):
        reproject_to_reference_grid(np.zeros((3, 3)), plain_wcs, plain_wcs, (3, 3))
