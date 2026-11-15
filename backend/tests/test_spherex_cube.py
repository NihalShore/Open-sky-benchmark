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
        fits.Column(name="WAVELENGTH", format="E", unit="um", array=np.linspace(0.8, 4.9, 102))
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
