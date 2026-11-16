from io import BytesIO

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from app.services import spherex_mef
from app.services.parallax_benchmark import inject_synthetic_epsf_source
from app.services.spherex_mef import (
    MefUpstreamError,
    build_cutout_url,
    calibrate_mef,
    cutout_to_detector_pixel,
    download_mef_cutout_file,
    extract_forced_photometry,
)


def _make_gaussian_epsf(size: int = 33, oversampling: int = 5, sigma_native_pix: float = 0.7) -> np.ndarray:
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[:size, :size]
    sigma_sub = sigma_native_pix * oversampling
    psf = np.exp(-0.5 * (((xx - c) ** 2 + (yy - c) ** 2) / (sigma_sub ** 2)))
    return psf / np.sum(psf)


def _make_mef_fixture(
    *,
    ra_deg: float = 127.6,
    dec_deg: float = -39.1,
    zodi_level: float = 0.45,
    source_ab_mag: float | None = 16.0,
    crpix1a: float | None = -99.0,
    crpix2a: float | None = -199.0,
    with_crval_a: bool = False,
    noise_sigma_mjy_sr: float = 0.002,
) -> bytes:
    ny, nx = 21, 21
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crpix = [11.0, 11.0]
    wcs.wcs.crval = [ra_deg, dec_deg]
    wcs.wcs.cdelt = [-6.15 / 3600.0, 6.15 / 3600.0]

    epsf = _make_gaussian_epsf(33, oversampling=5, sigma_native_pix=0.65)
    zodi = np.full((ny, nx), zodi_level, dtype=np.float32)
    science = np.zeros((ny, nx), dtype=np.float64)
    if source_ab_mag is not None:
        science, _ = inject_synthetic_epsf_source(
            science, epsf, 10.25, 10.75, source_ab_mag, pixel_scale_arcsec=6.15, oversampling=5
        )
    image = (science + zodi).astype(np.float32)
    flags = np.zeros((ny, nx), dtype=np.int32)
    flags[0, 0] = 4  # flagged pixel
    variance = np.full((ny, nx), noise_sigma_mjy_sr ** 2, dtype=np.float32)

    img_hdu = fits.ImageHDU(data=image, header=wcs.to_header(), name="IMAGE")
    img_hdu.header["BUNIT"] = "MJy/sr"
    img_hdu.header["MJD-OBS"] = 60895.4128
    img_hdu.header["DETECTOR"] = 2
    if crpix1a is not None and crpix2a is not None:
        img_hdu.header["CRPIX1A"] = crpix1a
        img_hdu.header["CRPIX2A"] = crpix2a
        if with_crval_a:
            img_hdu.header["CTYPE1A"] = "PIXEL"
            img_hdu.header["CTYPE2A"] = "PIXEL"
            img_hdu.header["CRVAL1A"] = 1.0
            img_hdu.header["CRVAL2A"] = 1.0
            img_hdu.header["CDELT1A"] = 1.0
            img_hdu.header["CDELT2A"] = 1.0

    epsf_hdu = fits.ImageHDU(data=epsf.astype(np.float32), name="EPSF")
    epsf_hdu.header["OVERSAMP"] = 5

    hdus = fits.HDUList(
        [
            fits.PrimaryHDU(),
            img_hdu,
            fits.ImageHDU(data=flags, name="FLAGS"),
            fits.ImageHDU(data=variance, name="VARIANCE"),
            fits.ImageHDU(data=zodi, name="ZODI"),
            epsf_hdu,
        ]
    )
    buf = BytesIO()
    hdus.writeto(buf)
    return buf.getvalue()


def test_build_cutout_url_validates_host_and_replaces_existing_cutout_params():
    url = build_cutout_url(
        "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/img.fits?center=1,2deg&token=abc",
        127.6,
        -39.1,
        92.25,
    )
    assert url.startswith("https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/img.fits?")
    assert "token=abc" in url
    assert url.count("center=") == 1

    with pytest.raises(MefUpstreamError):
        build_cutout_url("https://evil.example/img.fits", 127.6, -39.1, 92.25)


def test_cutout_to_detector_pixel_supports_wcs_a_and_crpix_offset():
    hdr_offset = fits.Header()
    hdr_offset["CRPIX1A"] = -99.0
    hdr_offset["CRPIX2A"] = -199.0
    x0, y0, mode0 = cutout_to_detector_pixel(hdr_offset, 0.0, 0.0)
    assert mode0 == "irsa_crpix_a_offset"
    assert (x0, y0) == (pytest.approx(100.0), pytest.approx(200.0))

    hdr_wcs_a = fits.Header()
    hdr_wcs_a["CTYPE1A"] = "PIXEL"
    hdr_wcs_a["CTYPE2A"] = "PIXEL"
    hdr_wcs_a["CRPIX1A"] = -99.0
    hdr_wcs_a["CRPIX2A"] = -199.0
    hdr_wcs_a["CRVAL1A"] = 1.0
    hdr_wcs_a["CRVAL2A"] = 1.0
    hdr_wcs_a["CDELT1A"] = 1.0
    hdr_wcs_a["CDELT2A"] = 1.0
    x1, y1, mode1 = cutout_to_detector_pixel(hdr_wcs_a, 0.0, 0.0)
    assert mode1 == "fits_alternate_wcs_a"
    assert (x1, y1) == (pytest.approx(100.0), pytest.approx(200.0))


def test_calibrate_mef_subtracts_zodi_masks_flags_and_recovers_cwave():
    payload = _make_mef_fixture(ra_deg=127.6, dec_deg=-39.1, crpix1a=-99.0, crpix2a=-199.0, with_crval_a=True)

    cwave = np.full((300, 300), np.nan, dtype=np.float64)
    cband = np.full((300, 300), np.nan, dtype=np.float64)
    dichroic = np.zeros((300, 300), dtype=np.uint8)
    # Target maps near cutout (10, 10) -> detector (110, 210)
    cwave[210, 110] = 1.54
    cband[210, 110] = 0.038

    cal = calibrate_mef(
        payload,
        127.6,
        -39.1,
        cwave_2d=cwave,
        cband_2d=cband,
        dichroic_mask_2d=dichroic,
    )

    assert cal["zodi_subtracted"] is True
    assert cal["mjd_obs"] == pytest.approx(60895.4128)
    assert cal["detector"] == 2
    assert cal["detector_coord_mapping"] == "fits_alternate_wcs_a"
    assert np.isnan(cal["clean_image_mjy_sr"][0, 0])  # FLAGS == 4 masked
    assert cal["flagged_pixel_count"] == 1
    assert cal["wavelength_um"] == pytest.approx(1.54)
    assert cal["bandwidth_um"] == pytest.approx(0.038)
    assert cal["wavelength_source"] == "spectral_wcs_cwave_cband"


def test_forced_epsf_photometry_recovers_exact_ab_magnitude():
    # Place source at exact WCS center (127.6, -39.1) by shifting target RA/Dec slightly to pixel (10.25, 10.75)
    payload = _make_mef_fixture(source_ab_mag=16.0)
    # Determine exact sky coordinates of pixel (10.25, 10.75)
    with fits.open(BytesIO(payload)) as hdus:
        sky = WCS(hdus["IMAGE"].header).pixel_to_world(10.25, 10.75)
    cal = calibrate_mef(payload, float(sky.ra.deg), float(sky.dec.deg))

    epsf_phot = extract_forced_photometry(cal, use_epsf=True, subtract_local_background=True)
    assert epsf_phot["method"] == "epsf_weighted"
    assert epsf_phot["synthetic"] is False
    assert epsf_phot["zodi_subtracted"] is True
    assert epsf_phot["ab_mag"] == pytest.approx(16.0, abs=0.02)
    assert epsf_phot["snr"] > 50.0

    ap_phot = extract_forced_photometry(cal, radius_pix=3.5, use_epsf=False)
    assert ap_phot["method"] == "aperture"
    assert ap_phot["ab_mag"] == pytest.approx(16.0, abs=0.05)


def test_forced_photometry_blocks_dichroic_impacted_measurements():
    payload = _make_mef_fixture(crpix1a=-99.0, crpix2a=-199.0)
    cwave = np.full((300, 300), 2.42)
    dichroic = np.ones((300, 300), dtype=np.uint8)
    cal = calibrate_mef(payload, 127.6, -39.1, cwave_2d=cwave, dichroic_mask_2d=dichroic)

    phot = extract_forced_photometry(cal, use_epsf=True)
    assert phot["dichroic_impacted"] is True
    assert phot["flux_ujy"] is None
    assert phot["status"] == "dichroic_or_out_of_frame"


def test_download_mef_cutout_file_streams_and_cleans_up(monkeypatch):
    raw_mef = _make_mef_fixture()

    class FakeResp:
        status_code = 200
        headers = {"Content-Length": str(len(raw_mef))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024):
            yield raw_mef

    monkeypatch.setattr(spherex_mef.requests, "get", lambda *args, **kwargs: FakeResp())

    with download_mef_cutout_file(
        "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/img.fits", 127.6, -39.1
    ) as path:
        assert path.exists()
        cal = calibrate_mef(path, 127.6, -39.1)
        assert cal["zodi_subtracted"] is True
    assert not path.exists()
