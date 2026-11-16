import numpy as np
import pytest
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.wcs import WCS

from app.services.reprojection import (
    ReprojectionError,
    reproject_to_reference_grid,
    reproject_with_coverage,
)


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


def test_reprojection_handles_different_celestial_frames():
    ref_wcs = make_wcs(crpix=(8.0, 8.0), crval=(180.0, 30.0))
    gal_center = SkyCoord(ra=180.0 * u.deg, dec=30.0 * u.deg, frame="icrs").galactic
    gal_wcs = WCS(naxis=2)
    gal_wcs.wcs.ctype = ["GLON-TAN", "GLAT-TAN"]
    gal_wcs.wcs.crpix = [8.0, 8.0]
    gal_wcs.wcs.crval = [gal_center.l.deg, gal_center.b.deg]
    gal_wcs.wcs.cdelt = [-0.01, 0.01]

    yy, xx = np.mgrid[:16, :16]
    sky_gal = gal_wcs.pixel_to_world(xx, yy).icrs
    gal_image = sky_gal.ra.deg + 2.0 * sky_gal.dec.deg

    reprojected, coverage, diagnostics = reproject_with_coverage(
        gal_image, gal_wcs, ref_wcs, (16, 16)
    )

    assert diagnostics["source_frame"] == "galactic"
    assert diagnostics["reference_frame"] == "icrs"
    assert coverage[7, 7] > 0.99
    expected_center = 180.0 + 2.0 * 30.0
    assert reprojected[7, 7] == pytest.approx(expected_center, abs=1e-3)


def test_reprojection_handles_swapped_lat_lon_axes():
    ref_wcs = make_wcs(crpix=(8.0, 8.0), crval=(120.0, 30.0))
    swapped_wcs = WCS(naxis=2)
    swapped_wcs.wcs.ctype = ["DEC--TAN", "RA---TAN"]
    swapped_wcs.wcs.crpix = [8.0, 8.0]
    swapped_wcs.wcs.crval = [30.0, 120.0]
    swapped_wcs.wcs.cdelt = [0.01, -0.01]

    yy, xx = np.mgrid[:16, :16]
    sky = swapped_wcs.pixel_to_world(xx, yy)
    swapped_image = sky.ra.deg - sky.dec.deg

    reprojected, coverage, _ = reproject_with_coverage(
        swapped_image, swapped_wcs, ref_wcs, (16, 16)
    )

    assert coverage[7, 7] > 0.99
    assert reprojected[7, 7] == pytest.approx(90.0, abs=1e-3)


def test_reprojection_masks_opposite_hemisphere():
    north_wcs = make_wcs(crpix=(5.0, 5.0), crval=(0.0, 60.0))
    south_wcs = make_wcs(crpix=(5.0, 5.0), crval=(180.0, -60.0))
    image = np.ones((10, 10), dtype=float)

    reprojected, coverage, _ = reproject_with_coverage(
        image, north_wcs, south_wcs, (10, 10)
    )

    assert np.isnan(reprojected).all()
    assert np.all(coverage == 0.0)


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
