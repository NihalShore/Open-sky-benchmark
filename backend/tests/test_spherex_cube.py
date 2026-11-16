from contextlib import contextmanager
import gzip
from io import BytesIO

import numpy as np
from PIL import Image
import pytest
from astropy.io import fits

from app.services import spherex_cube
from app.services.spherex_cube import (
    CubeDataError,
    CubeUpstreamError,
    discover_cube_products,
    download_cube_file,
    inspect_cube,
    render_preview_png,
    trusted_cube_url,
)


def make_cube_fixture(*, swapped_axes: bool = False) -> bytes:
    if swapped_axes:
        # Shape (Y=8, X=8, C=102) so spectral axis is axis 2 (FITS axis 1 -> CTYPE1='WAVE')
        image = np.zeros((8, 8, 102), dtype=np.float32)
        image[:, :, 0] = np.arange(64, dtype=np.float32).reshape(8, 8)
        nhits = np.ones((8, 8, 102), dtype=np.uint16)
        nhits[0, 0, :] = 0
        flags = np.zeros((8, 8, 102), dtype=np.uint16)
        flags[0, 0, 0] = 7  # uncovered pixel must NOT count toward covered flagged count
        flags[1, 1, 0] = 3  # covered flagged pixel
    else:
        image = np.arange(102 * 8 * 8, dtype=np.float32).reshape(102, 8, 8)
        nhits = np.ones_like(image, dtype=np.uint16)
        nhits[:, 0, 0] = 0
        flags = np.zeros_like(image, dtype=np.uint16)
        flags[0, 0, 0] = 7  # uncovered pixel
        flags[0, 1, 1] = 3  # covered flagged pixel

    channels = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="DETECTOR", format="I", array=np.ones(102, dtype=np.int16)),
            fits.Column(name="SUBCHAN", format="I", array=np.arange(1, 103, dtype=np.int16)),
            fits.Column(name="WAVELENGTH", format="E", unit="um", array=np.linspace(0.8, 4.9, 102)),
            fits.Column(name="WL_MIN", format="E", unit="um", array=np.linspace(0.79, 4.89, 102)),
            fits.Column(name="WL_MAX", format="E", unit="um", array=np.linspace(0.81, 4.91, 102)),
            fits.Column(name="BANDWIDTH", format="E", unit="um", array=np.full(102, 0.02)),
            fits.Column(name="R", format="E", array=np.full(102, 40.0)),
            fits.Column(name="R_STD", format="E", array=np.full(102, 1.0)),
        ],
        name="SPECTRAL_CHANNELS",
    )
    primary = fits.PrimaryHDU()
    primary.header["BLANKCH"] = "51,52"
    primary.header["ZODISUB"] = True
    primary.header["DOI"] = "10.26131/IRSA679"

    image_hdu = fits.ImageHDU(data=image, name="IMAGE")
    image_hdu.header["BUNIT"] = "MJy/sr"
    if swapped_axes:
        # NumPy shape (Y=8, X=8, C=102) -> FITS axes (NAXIS1=102, NAXIS2=8, NAXIS3=8)
        image_hdu.header["CTYPE1"] = "WAVE"
        image_hdu.header["CUNIT1"] = "um"
        image_hdu.header["CTYPE2"] = "RA---TAN"
        image_hdu.header["CTYPE3"] = "DEC--TAN"
        image_hdu.header["CRVAL1"] = 0.8
        image_hdu.header["CRVAL2"] = 127.6
        image_hdu.header["CRVAL3"] = -39.1
        image_hdu.header["CDELT1"] = 0.04
        image_hdu.header["CDELT2"] = -0.001
        image_hdu.header["CDELT3"] = 0.001
        image_hdu.header["CRPIX1"] = 1.0
        image_hdu.header["CRPIX2"] = 4.0
        image_hdu.header["CRPIX3"] = 4.0

    hdus = fits.HDUList(
        [
            primary,
            image_hdu,
            fits.ImageHDU(data=nhits, name="NHITS"),
            fits.ImageHDU(data=flags, name="FLAGS"),
            channels,
        ]
    )
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
    assert metadata["flags_nonzero_pixel_count"] == 1
    assert metadata["flags_total_nonzero_pixel_count"] == 2
    assert metadata["zodiacal_light_subtracted"] is True
    assert metadata["dataset_doi"] == "10.26131/IRSA679"
    assert np.isnan(plane[0, 0])
    assert np.isfinite(plane[0, 1])


def test_inspect_cube_handles_wcs_spectral_axis_on_non_zero_axis():
    metadata, plane = inspect_cube(make_cube_fixture(swapped_axes=True), channel_index=0)

    assert plane.shape == (8, 8)
    assert metadata["coverage_fraction"] == pytest.approx(63 / 64)
    assert metadata["flags_nonzero_pixel_count"] == 1
    assert np.isnan(plane[0, 0])
    assert plane[0, 1] == pytest.approx(1.0)


def test_inspect_cube_rejects_blank_channel_from_header():
    with pytest.raises(CubeDataError, match="marked blank"):
        inspect_cube(make_cube_fixture(), channel_index=50)


def test_inspect_cube_rejects_wrong_channel_index():
    with pytest.raises(CubeDataError, match="between 0 and 101"):
        inspect_cube(make_cube_fixture(), channel_index=102)


def test_preview_is_rgba_png_with_transparent_uncovered_pixels_and_north_up_flip():
    _, plane = inspect_cube(make_cube_fixture(), channel_index=0)
    png_bytes = render_preview_png(plane)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    img = Image.open(BytesIO(png_bytes))
    assert img.mode == "RGBA"
    rgba = np.asarray(img)
    # Row 0 of plane had uncovered pixel at col 0; vertical flip places row 0 at bottom (row -1)
    assert rgba[-1, 0, 3] == 0
    assert rgba[-1, 1, 3] == 255
    # Plane top row (-1) had larger values than bottom row (0), flipped to top row (0) in PNG
    assert rgba[0, 1, 0] > rgba[-1, 1, 0]


def test_download_cube_file_streams_gzip_fits_and_cleans_up(monkeypatch):
    raw_fits = make_cube_fixture()
    gz_fits = gzip.compress(raw_fits)

    class FakeResp:
        status_code = 200
        headers = {"Content-Length": str(len(gz_fits))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024):
            for idx in range(0, len(gz_fits), 512):
                yield gz_fits[idx : idx + 512]

    monkeypatch.setattr(spherex_cube.requests, "get", lambda *args, **kwargs: FakeResp())

    with download_cube_file("https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/cube.fits.gz") as path:
        assert path.exists()
        metadata, plane = inspect_cube(path, channel_index=0)
        assert metadata["channel_number"] == 1
        assert np.isfinite(plane[0, 1])
    assert not path.exists()


def test_download_cube_file_rejects_gzip_exceeding_max_bytes(monkeypatch):
    gz_bomb = gzip.compress(b"SIMPLE" + b" " * 4096)
    monkeypatch.setattr(spherex_cube, "MAX_FITS_BYTES", 1024)

    class FakeResp:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024):
            yield gz_bomb

    monkeypatch.setattr(spherex_cube.requests, "get", lambda *args, **kwargs: FakeResp())

    with pytest.raises(CubeUpstreamError, match="exceeds"):
        with download_cube_file("https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/bomb.fits.gz"):
            pass


def test_discover_cube_products_sorts_nearest_first(monkeypatch):
    class FakeClient:
        def query_sia(self, **kwargs):
            return [
                {
                    "obs_id": "FAR",
                    "obs_collection": "spherex_dr1_cube",
                    "s_ra": 128.0,
                    "s_dec": -39.1,
                    "access_url": "https://irsa.ipac.caltech.edu/far.fits",
                },
                {
                    "obs_id": "NEAR",
                    "obs_collection": "spherex_dr1_cube",
                    "s_ra": 127.6,
                    "s_dec": -39.1,
                    "access_url": "https://irsa.ipac.caltech.edu/near.fits",
                },
            ]

    @contextmanager
    def fake_irsa_client():
        yield FakeClient()

    monkeypatch.setattr(spherex_cube, "irsa_client", fake_irsa_client)
    products = discover_cube_products(127.6, -39.1, 30.0)

    assert [p["observation_id"] for p in products] == ["NEAR", "FAR"]


def test_discover_cube_products_rejects_only_untrusted_urls(monkeypatch):
    class FakeClient:
        def query_sia(self, **kwargs):
            return [
                {
                    "obs_id": "BAD",
                    "obs_collection": "spherex_dr1_cube",
                    "s_ra": 127.6,
                    "s_dec": -39.1,
                    "access_url": "https://evil.example/bad.fits",
                }
            ]

    @contextmanager
    def fake_irsa_client():
        yield FakeClient()

    monkeypatch.setattr(spherex_cube, "irsa_client", fake_irsa_client)
    with pytest.raises(CubeUpstreamError, match="untrusted"):
        discover_cube_products(127.6, -39.1, 30.0)


@pytest.mark.parametrize(
    "url",
    [
        "http://irsa.ipac.caltech.edu/data/test.fits",
        "https://example.com/test.fits",
        "https://user@irsa.ipac.caltech.edu/test.fits",
        "https://irsa.ipac.caltech.edu:8443/test.fits",
    ],
)
def test_untrusted_cube_urls_are_rejected(url):
    with pytest.raises(CubeDataError):
        trusted_cube_url(url)


def test_official_irsa_https_url_is_accepted():
    assert trusted_cube_url(
        "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/test.fits"
    ).startswith("https://irsa.ipac.caltech.edu/")


def test_inspect_script_supports_direct_execution_and_swapped_spectral_axis():
    from scripts.inspect_spherex_cube import inspect_product

    report = inspect_product(
        make_cube_fixture(swapped_axes=True),
        {"observation_id": "Npix_swapped", "collection": "spherex_dr1_cube"},
    )
    image_entry = next(h for h in report["hdus"] if h["name"] == "IMAGE")
    assert image_entry["celestial_wcs"]["available"] is True
    assert image_entry["celestial_wcs"]["pixel_to_sky"]["center"]["ra_deg"] == pytest.approx(127.6, abs=0.05)
