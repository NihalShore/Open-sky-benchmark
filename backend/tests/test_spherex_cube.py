from io import BytesIO

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from app.services import spherex_cube
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
    image_hdu = fits.ImageHDU(data=image, name="IMAGE")
    wcs = WCS(naxis=3)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN", "WAVE"]
    wcs.wcs.cunit = ["deg", "deg", "um"]
    wcs.wcs.crpix = [4.5, 4.5, 1.0]
    wcs.wcs.crval = [127.6, -39.1, 0.8]
    wcs.wcs.cdelt = [-0.01, 0.01, 0.04]
    image_hdu.header.update(wcs.to_header())
    hdus = fits.HDUList([
        primary,
        image_hdu,
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


def test_download_cube_accepts_full_tile_over_previous_limit(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"Content-Length": str(301 * 1024 * 1024)}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"SIMPLE  = fake FITS payload"

    monkeypatch.setattr(spherex_cube.requests, "get", lambda *args, **kwargs: FakeResponse())

    payload = spherex_cube.download_cube(
        "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/test.fits"
    )

    assert payload.startswith(b"SIMPLE")



def test_discover_cube_products_uses_bounded_sia_query(monkeypatch):
    calls = {}

    def fake_query(ra_deg, dec_deg, radius_arcsec, collections, *, maxrec):
        calls.update({
            "ra_deg": ra_deg,
            "dec_deg": dec_deg,
            "radius_arcsec": radius_arcsec,
            "collections": collections,
            "maxrec": maxrec,
        })
        return [{
            "obs_id": "Npix445_cube",
            "obs_collection": "spherex_dr1_cube",
            "dataproduct_type": "cube",
            "access_format": "application/fits",
            "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/example.fits",
        }]

    monkeypatch.setattr(spherex_cube, "query_sia", fake_query)
    products = spherex_cube.discover_cube_products(60.8109955, 51.3404038, 30)

    assert calls == {
        "ra_deg": 60.8109955,
        "dec_deg": 51.3404038,
        "radius_arcsec": 30,
        "collections": ["spherex_dr1_cube"],
        "maxrec": spherex_cube.MAX_CUBE_SEARCH_RECORDS,
    }
    assert len(products) == 1
    assert products[0]["observation_id"] == "Npix445_cube"
    assert products[0]["synthetic"] is False



def test_inspect_cube_maps_query_position_through_image_celestial_wcs():
    metadata, _ = inspect_cube(
        make_cube_fixture(),
        channel_index=0,
        ra_deg=127.6,
        dec_deg=-39.1,
    )

    assert metadata["query_pixel_status"] == "available"
    assert metadata["query_pixel"]["x"] == pytest.approx(3.5)
    assert metadata["query_pixel"]["y"] == pytest.approx(3.5)


def test_render_preview_keeps_uncovered_pixels_transparent():
    from PIL import Image

    _, plane = inspect_cube(make_cube_fixture(), channel_index=0)
    png = render_preview_png(plane)

    with Image.open(BytesIO(png)) as image:
        rgba = image.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0
        assert rgba.getpixel((1, 0))[3] == 255
