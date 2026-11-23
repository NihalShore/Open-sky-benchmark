import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from scripts.validate_spherex_cube import build_celestial_wcs


def test_celestial_wcs_keeps_linked_fits_hdus_available():
    source_wcs = WCS(naxis=2)
    source_wcs.wcs.crpix = [4.5, 4.5]
    source_wcs.wcs.cdelt = [-0.01, 0.01]
    source_wcs.wcs.crval = [180.0, 45.0]
    source_wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    image_hdu = fits.ImageHDU(
        data=np.zeros((8, 8), dtype=np.float32),
        header=source_wcs.to_header(),
        name="IMAGE",
    )
    hdus = fits.HDUList([fits.PrimaryHDU(), image_hdu])

    celestial = build_celestial_wcs(image_hdu, hdus)
    sky = celestial.pixel_to_world(3.5, 3.5)
    back_x, back_y = celestial.world_to_pixel(sky)

    assert celestial.has_celestial
    assert np.hypot(back_x - 3.5, back_y - 3.5) <= 1e-3
