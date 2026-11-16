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
    result = reproject_to_reference_grid(
        image, make_wcs(), make_wcs(crpix=(6.0, 5.0)), (10, 10)
    )
    assert result[4, 4] == pytest.approx(3.0, abs=1e-3)


def test_reprojection_keeps_nan_when_no_input_support():
    image = np.full((5, 5), np.nan)
    result = reproject_to_reference_grid(
        image, make_wcs(crpix=(3, 3)), make_wcs(crpix=(3, 3)), image.shape
    )
    assert np.isnan(result).all()


def test_reprojection_rejects_non_image_input():
    with pytest.raises(ReprojectionError, match="two-dimensional"):
        reproject_to_reference_grid(np.zeros(3), make_wcs(), make_wcs(), (3, 3))


def test_reprojection_rejects_non_celestial_wcs():
    plain_wcs = WCS(naxis=2)
    with pytest.raises(ReprojectionError, match="celestial"):
        reproject_to_reference_grid(np.zeros((3, 3)), plain_wcs, plain_wcs, (3, 3))


def test_reprojection_rejects_fractional_output_dimensions():
    with pytest.raises(ReprojectionError, match="positive integer"):
        reproject_to_reference_grid(np.zeros((3, 3)), make_wcs(), make_wcs(), (3.5, 3))



def test_reprojection_converts_between_celestial_frames():
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    icrs = make_wcs(crval=(120.0, 30.0))
    galactic = WCS(naxis=2)
    galactic.wcs.ctype = ["GLON-TAN", "GLAT-TAN"]
    galactic.wcs.crpix = [5.0, 5.0]
    center = SkyCoord(ra=120.0 * u.deg, dec=30.0 * u.deg, frame="icrs").galactic
    galactic.wcs.crval = [center.l.deg, center.b.deg]
    galactic.wcs.cdelt = [-0.01, 0.01]

    image = np.arange(100, dtype=float).reshape(10, 10)
    result = reproject_to_reference_grid(image, galactic, icrs, image.shape)

    assert result[4, 4] == pytest.approx(image[4, 4], abs=1e-4)


def test_reprojection_does_not_interpolate_across_missing_support():
    image = np.ones((10, 10), dtype=float)
    image[4, 4] = np.nan
    result = reproject_to_reference_grid(
        image, make_wcs(), make_wcs(crpix=(5.5, 5.0)), image.shape
    )

    assert np.isnan(result[4, 4])
