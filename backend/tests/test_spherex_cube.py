from io import BytesIO

import numpy as np
import pytest
from astropy.io import fits

from app.services.spherex_cube import (
    CubeDataError,
    inspect_cube,
    render_preview_png,
    trusted_cube_url,
)


def make_cube_fixture() -> bytes:
    image = np.arange(102 * 8 * 8, dtype=np.float32).reshape(102, 8, 8)
    nhits = np.ones_like(image, dtype=np.uint16)
    nhits[:, 0, 0] = 0
    flags = np.zeros_like(image, dtype=np.uint16)
    channels = fits.BinTableHDU.from_columns([
        fits.Column(name="DETECTOR", format="I", array=np.ones(102, dtype=np.int16)),
        fits.Column(name="SUBCHAN", format="I", array=np.arange(1, 103, dtype=np.int16)),
        fits.Column(name="WAVELENGTH", format="E", unit="um", array=np.linspace(0.8, 4.9, 102)),
        fits.Column(name="WL_MIN", format="E", unit="um", array=np.linspace(0.79, 4.89, 102)),
        fits.Column(name="WL_MAX", format="E", unit="um", array=np.linspace(0.81, 4.91, 102)),
        fits.Column(name="BANDWIDTH", format="E", unit="um", array=np.full(102, 0.02)),
        fits.Column(name="R", format="E", array=np.full(102, 40.0)),
        fits.Column(name="R_STD", format="E", array=np.full(102, 1.0)),
    ], name="SPECTRAL_CHANNELS")
    primary = fits.PrimaryHDU()
    primary.header["BLANKCH"] = "51,52"
    hdus = fits.HDUList([
        primary,
        fits.ImageHDU(data=image, name="IMAGE"),
        fits.ImageHDU(data=nhits, name="NHITS"),
        fits.ImageHDU(data=flags, name="FLAGS"),
        channels,
    ])
    buffer = BytesIO()
    hdus.writeto(buffer)
    return buffer.getvalue()


def test_inspect_cube_returns_real_channel_metadata_and_masks_no_coverage():
    metadata, plane = inspect_cube(make_cube_fixture(), channel_index=0)

    assert metadata["synthetic"] is False
    assert metadata["channel_number"] == 1
    assert metadata["wavelength_um"] == pytest.approx(0.8)
    assert metadata["wavelength_min_um"] == pytest.approx(0.79)
    assert metadata["wavelength_max_um"] == pytest.approx(0.81)
    assert metadata["bandwidth_um"] == pytest.approx(0.02)
    assert metadata["resolving_power"] == pytest.approx(40.0)
    assert metadata["detector"] == 1
    assert metadata["subchannel"] == 1
    assert metadata["coverage_fraction"] == pytest.approx(63 / 64)
    assert np.isnan(plane[0, 0])
    assert np.isfinite(plane[0, 1])


def test_inspect_cube_rejects_blank_channel_from_header():
    with pytest.raises(CubeDataError, match="marked blank"):
        inspect_cube(make_cube_fixture(), channel_index=50)


def test_inspect_cube_rejects_wrong_channel_index():
    with pytest.raises(CubeDataError, match="between 0 and 101"):
        inspect_cube(make_cube_fixture(), channel_index=102)


def test_preview_is_png():
    _, plane = inspect_cube(make_cube_fixture(), channel_index=0)
    assert render_preview_png(plane).startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("url", [
    "http://irsa.ipac.caltech.edu/data/test.fits",
    "https://example.com/test.fits",
    "https://user@irsa.ipac.caltech.edu/test.fits",
    "https://irsa.ipac.caltech.edu:8443/test.fits",
])
def test_untrusted_cube_urls_are_rejected(url):
    with pytest.raises(CubeDataError):
        trusted_cube_url(url)


def test_official_irsa_https_url_is_accepted():
    assert trusted_cube_url(
        "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/test.fits"
    ).startswith("https://irsa.ipac.caltech.edu/")



def test_preview_keeps_missing_pixels_transparent_and_flips_fits_rows():
    from PIL import Image

    plane = np.array([[1.0, 2.0], [3.0, np.nan]], dtype=np.float32)
    preview = Image.open(BytesIO(render_preview_png(plane))).convert("RGBA")

    assert preview.size == (2, 2)
    assert preview.getpixel((1, 0))[3] == 0
    assert preview.getpixel((0, 0))[3] == 255


def test_channel_axis_uses_spectral_wcs_axis_when_shape_is_ambiguous():
    from astropy.wcs import WCS
    from app.services.spherex_cube import _channel_axis

    wcs = WCS(naxis=3)
    wcs.wcs.ctype = ["WAVE", "DEC--TAN", "RA---TAN"]
    wcs.wcs.cunit = ["um", "deg", "deg"]
    wcs.wcs.crpix = [1.0, 1.0, 1.0]
    wcs.wcs.crval = [1.0, 0.0, 0.0]
    wcs.wcs.cdelt = [0.01, 0.01, -0.01]
    header = wcs.to_header()
    image = np.zeros((10, 102, 102))

    assert _channel_axis(image, 102, header) == 2
