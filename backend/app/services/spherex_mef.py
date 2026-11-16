"""SPHEREx Spectral Image MEF cutout ingestion, calibration, and forced photometry.

Unlike the time-averaged All-Sky Cubes (`spherex_dr1_cube`), single-exposure
Spectral Image Multi-Extension FITS (MEF) products preserve individual MJD-OBS
timestamps, zodiacal background models (`ZODI`), pixel quality flags (`FLAGS`),
per-pixel variance (`VARIANCE`), and oversampled ePSFs needed for moving-object
and time-domain photometry.
"""
from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import tempfile
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import zlib

import numpy as np
import requests
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales

from app.services.irsa import _trusted_access_url, validate_sky_query

MAX_MEF_BYTES = 100 * 1024 * 1024
REQUEST_TIMEOUT: tuple[float, float] = (10.0, 60.0)
GZIP_MAGIC = b"\x1f\x8b"
ARCSEC_PER_RADIAN = 206264.80624709636
AB_ZERO_POINT_UJY = 3.631e9  # 3631 Jy in microjanskys
DEFAULT_NATIVE_PIXEL_SCALE_ARCSEC = 6.15


class MefDataError(ValueError):
    """Raised when MEF parameters or FITS structure cannot be used safely."""


class MefUpstreamError(MefDataError):
    """Raised when an upstream MEF archive URL or payload is invalid or unreachable."""


def trusted_mef_url(value: str) -> str:
    """Validate that an MEF URL is HTTPS on the official IRSA host."""
    if not isinstance(value, str):
        raise MefUpstreamError("Archive returned an untrusted MEF URL")
    safe = _trusted_access_url(value)
    if safe is None:
        raise MefUpstreamError("Archive returned an untrusted MEF URL")
    return safe


def build_cutout_url(
    access_url: str,
    ra_deg: float,
    dec_deg: float,
    size_arcsec: float = 92.25,
) -> str:
    """Safely append IRSA cutout parameters to a validated MEF access URL."""
    safe_url = trusted_mef_url(access_url)
    position = validate_sky_query(ra_deg, dec_deg, size_arcsec)

    split = urlsplit(safe_url)
    query_items = [
        (k, v)
        for k, v in parse_qsl(split.query, keep_blank_values=True)
        if k.lower() not in {"center", "size"}
    ]
    query_items.append(("center", f"{float(position.ra.deg):.7f},{float(position.dec.deg):.7f}deg"))
    query_items.append(("size", f"{float(size_arcsec):.4f}arcsec"))
    return urlunsplit(
        (split.scheme, split.netloc, split.path, urlencode(query_items), split.fragment)
    )


def _stream_mef_response(response: requests.Response, sink: Any) -> int:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_MEF_BYTES:
                raise MefUpstreamError("MEF cutout exceeds the configured download limit")
        except ValueError:
            pass

    raw_total = 0
    out_total = 0
    raw_prefix = bytearray()
    decomp_prefix = bytearray()
    header_checked = False
    is_gzip: bool | None = None
    decomp = None

    for chunk in response.iter_content(chunk_size=256 * 1024):
        if not chunk:
            continue
        raw_total += len(chunk)
        if raw_total > MAX_MEF_BYTES:
            raise MefUpstreamError("MEF cutout exceeds the configured download limit")

        if is_gzip is None:
            needed = max(0, 6 - len(raw_prefix))
            raw_prefix.extend(chunk[:needed])
            if len(raw_prefix) >= 2 and raw_prefix[:2] == GZIP_MAGIC:
                is_gzip = True
                decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
                payload_chunk = bytes(raw_prefix) + chunk[needed:]
                raw_prefix.clear()
                data = decomp.decompress(payload_chunk, MAX_MEF_BYTES - out_total + 1)
            elif len(raw_prefix) >= 6:
                is_gzip = False
                if not bytes(raw_prefix).startswith(b"SIMPLE"):
                    raise MefUpstreamError("Archive response is not a FITS MEF file")
                header_checked = True
                data = bytes(raw_prefix) + chunk[needed:]
                raw_prefix.clear()
            else:
                continue
        elif is_gzip:
            assert decomp is not None
            data = decomp.decompress(chunk, MAX_MEF_BYTES - out_total + 1)
        else:
            data = chunk

        if data:
            out_total += len(data)
            if out_total > MAX_MEF_BYTES:
                raise MefUpstreamError("Decompressed MEF cutout exceeds the configured size limit")
            if not header_checked:
                decomp_prefix.extend(data)
                if len(decomp_prefix) < 6:
                    continue
                if not bytes(decomp_prefix).startswith(b"SIMPLE"):
                    raise MefUpstreamError("Archive gzip payload is not a FITS MEF file")
                header_checked = True
                sink.write(bytes(decomp_prefix))
                decomp_prefix.clear()
            else:
                sink.write(data)

    if is_gzip is None:
        if not bytes(raw_prefix).startswith(b"SIMPLE"):
            raise MefUpstreamError("Archive response is not a FITS MEF file")
        sink.write(bytes(raw_prefix))
        out_total += len(raw_prefix)
    elif is_gzip and decomp is not None:
        tail = decomp.flush(MAX_MEF_BYTES - out_total + 1)
        out_total += len(tail)
        if out_total > MAX_MEF_BYTES:
            raise MefUpstreamError("Decompressed MEF cutout exceeds the configured size limit")
        if not header_checked:
            decomp_prefix.extend(tail)
            if not bytes(decomp_prefix).startswith(b"SIMPLE"):
                raise MefUpstreamError("Archive gzip payload is not a FITS MEF file")
            sink.write(bytes(decomp_prefix))
        elif tail:
            sink.write(tail)

    return out_total


@contextmanager
def download_mef_cutout_file(
    access_url: str,
    ra_deg: float,
    dec_deg: float,
    size_arcsec: float = 92.25,
) -> Iterator[Path]:
    """Stream one bounded IRSA MEF cutout to a temporary file without redirects."""
    cutout_url = build_cutout_url(access_url, ra_deg, dec_deg, size_arcsec)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".fits", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            with requests.get(
                cutout_url,
                stream=True,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
                headers={"User-Agent": "SPHEREx-TimeLens/0.3"},
            ) as response:
                if 300 <= response.status_code < 400:
                    raise MefUpstreamError("Unexpected redirect from the archive")
                response.raise_for_status()
                _stream_mef_response(response, tmp)
        yield tmp_path
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def cutout_to_detector_pixel(
    header: fits.Header,
    x_cutout: float,
    y_cutout: float,
) -> tuple[float, float, str]:
    """Map 0-based cutout pixel coordinates to 0-based full-detector coordinates.

    Uses FITS alternate WCS key 'A' when present (falling back cleanly to the
    IRSA CRPIX1A/CRPIX2A offset convention when CRVAL1A/CRVAL2A are omitted).
    """
    has_crpix_a = header.get("CRPIX1A") is not None and header.get("CRPIX2A") is not None
    if has_crpix_a:
        if header.get("CRVAL1A") is not None and header.get("CRVAL2A") is not None:
            wcs_a = WCS(header, key="A")
            x_1based, y_1based = wcs_a.pixel_to_world_values(x_cutout, y_cutout)
            return float(x_1based) - 1.0, float(y_1based) - 1.0, "fits_alternate_wcs_a"
        crpix1a = float(header["CRPIX1A"])
        crpix2a = float(header["CRPIX2A"])
        return 1.0 + float(x_cutout) - crpix1a, 1.0 + float(y_cutout) - crpix2a, "irsa_crpix_a_offset"
    return float(x_cutout), float(y_cutout), "cutout_identity"


def _header_float(headers: list[fits.Header], keys: tuple[str, ...]) -> float | None:
    for hdr in headers:
        for key in keys:
            val = hdr.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and np.isfinite(val):
                return float(val)
    return None


def _header_value(headers: list[fits.Header], keys: tuple[str, ...]) -> Any:
    for hdr in headers:
        for key in keys:
            if key in hdr and hdr[key] is not None:
                return hdr[key]
    return None


def _pixel_scale_from_wcs(wcs: WCS) -> tuple[float, float]:
    scales = proj_plane_pixel_scales(wcs.celestial) * 3600.0
    if len(scales) >= 2 and np.all(np.isfinite(scales[:2])) and np.all(scales[:2] > 0):
        return float(scales[0]), float(scales[1])
    return DEFAULT_NATIVE_PIXEL_SCALE_ARCSEC, DEFAULT_NATIVE_PIXEL_SCALE_ARCSEC


def calibrate_mef(
    payload: bytes | str | Path,
    ra_deg: float,
    dec_deg: float,
    *,
    reject_flag_mask: int | None = None,
    cwave_2d: np.ndarray | None = None,
    cband_2d: np.ndarray | None = None,
    dichroic_mask_2d: np.ndarray | None = None,
    require_zodi: bool = True,
) -> dict[str, Any]:
    """Calibrate a SPHEREx Spectral Image MEF or cutout around (ra_deg, dec_deg).

    Steps:
    1. Subtract HDU `ZODI` from `IMAGE` (in MJy/sr).
    2. Mask pixels flagged by `FLAGS` (any nonzero flag by default, or specific
       bits when `reject_flag_mask` is set) and non-finite / non-positive `VARIANCE`.
    3. Map sky `(ra_deg, dec_deg)` to cutout pixel `(x_cutout, y_cutout)` via celestial WCS.
    4. Recover full-detector pixel `(x_orig, y_orig)` via alternate WCS `A` (`CRPIX1A`/`CRPIX2A`)
       for lookup in calibrated `CWAVE` / `CBAND` arrays when supplied.
    """
    position = validate_sky_query(ra_deg, dec_deg, 1.0)
    source: Any = payload if isinstance(payload, (str, Path)) else BytesIO(payload)
    try:
        hdus_ctx = fits.open(source, memmap=False)
    except Exception as exc:
        raise MefUpstreamError(f"Could not open MEF payload: {exc}") from exc

    with hdus_ctx as hdus:
        by_name = {hdu.name.upper(): hdu for hdu in hdus if hdu.name}
        required = {"IMAGE", "FLAGS", "VARIANCE"}
        if require_zodi:
            required.add("ZODI")
        missing = required - set(by_name)
        if missing:
            raise MefUpstreamError(f"MEF is missing required extensions: {', '.join(sorted(missing))}")

        image_hdu = by_name["IMAGE"]
        flags_hdu = by_name["FLAGS"]
        variance_hdu = by_name["VARIANCE"]
        zodi_hdu = by_name.get("ZODI")

        if image_hdu.data is None or image_hdu.data.ndim != 2:
            raise MefUpstreamError("MEF IMAGE extension must be a 2-D array")
        image = np.asarray(image_hdu.data, dtype=np.float64)
        flags = np.asarray(flags_hdu.data)
        variance = np.asarray(variance_hdu.data, dtype=np.float64)
        if flags.shape != image.shape or variance.shape != image.shape:
            raise MefUpstreamError("IMAGE, FLAGS, and VARIANCE shapes do not match")

        if zodi_hdu is not None:
            if zodi_hdu.data is None or zodi_hdu.data.shape != image.shape:
                raise MefUpstreamError("ZODI shape does not match IMAGE")
            zodi = np.asarray(zodi_hdu.data, dtype=np.float64)
            clean_image = image - zodi
            zodi_subtracted = True
        else:
            clean_image = image.copy()
            zodi_subtracted = False

        if reject_flag_mask is None:
            flagged = flags != 0
        else:
            flagged = (flags.astype(np.int64) & int(reject_flag_mask)) != 0

        usable = np.isfinite(clean_image) & (~flagged) & np.isfinite(variance) & (variance > 0)
        clean_image = np.where(usable, clean_image, np.nan)
        clean_variance = np.where(usable, variance, np.nan)

        wcs = WCS(image_hdu.header).celestial
        if not wcs.has_celestial:
            raise MefUpstreamError("MEF IMAGE extension lacks a valid celestial WCS")

        x_cutout_arr, y_cutout_arr = wcs.world_to_pixel(position)
        x_cutout = float(x_cutout_arr)
        y_cutout = float(y_cutout_arr)
        if not (np.isfinite(x_cutout) and np.isfinite(y_cutout)):
            raise MefDataError("Target position did not map onto the MEF WCS")

        ny, nx = image.shape
        target_in_frame = -0.5 <= x_cutout <= nx - 0.5 and -0.5 <= y_cutout <= ny - 0.5
        x_orig, y_orig, det_mapping = cutout_to_detector_pixel(image_hdu.header, x_cutout, y_cutout)

        wavelength_um: float | None = None
        bandwidth_um: float | None = None
        wavelength_source = "unavailable"
        dichroic_impacted = False

        if cwave_2d is not None:
            cwave_arr = np.asarray(cwave_2d, dtype=np.float64)
            iy = int(np.round(y_orig))
            ix = int(np.round(x_orig))
            if 0 <= iy < cwave_arr.shape[0] and 0 <= ix < cwave_arr.shape[1]:
                val = float(cwave_arr[iy, ix])
                if np.isfinite(val):
                    wavelength_um = val
                    wavelength_source = "spectral_wcs_cwave_cband"
                if cband_2d is not None:
                    cband_arr = np.asarray(cband_2d, dtype=np.float64)
                    if 0 <= iy < cband_arr.shape[0] and 0 <= ix < cband_arr.shape[1]:
                        bw = float(cband_arr[iy, ix])
                        if np.isfinite(bw):
                            bandwidth_um = bw
                if dichroic_mask_2d is not None:
                    dmask = np.asarray(dichroic_mask_2d)
                    if 0 <= iy < dmask.shape[0] and 0 <= ix < dmask.shape[1]:
                        dichroic_impacted = bool(dmask[iy, ix])

        epsf_data: np.ndarray | None = None
        epsf_oversampling: int | None = None
        for psf_name in ("EPSF", "PSF"):
            if psf_name in by_name and by_name[psf_name].data is not None:
                epsf_hdu = by_name[psf_name]
                raw_epsf = np.asarray(epsf_hdu.data, dtype=np.float64)
                if raw_epsf.ndim == 2 and np.all(np.isfinite(raw_epsf)):
                    epsf_data = raw_epsf
                    oversamp = epsf_hdu.header.get("OVERSAMP")
                    if isinstance(oversamp, (int, float)) and oversamp >= 1:
                        epsf_oversampling = int(round(float(oversamp)))
                    elif raw_epsf.shape[0] == 33:
                        epsf_oversampling = 5
                    elif raw_epsf.shape[0] == 101:
                        epsf_oversampling = 10
                    else:
                        epsf_oversampling = 1
                break

        headers = [image_hdu.header, hdus[0].header]
        scale_x_arcsec, scale_y_arcsec = _pixel_scale_from_wcs(wcs)

        return {
            "mjd_obs": _header_float(headers, ("MJD-OBS", "MJD_OBS")),
            "date_obs": _header_value(headers, ("DATE-OBS",)),
            "detector": _header_value(headers, ("DETECTOR",)),
            "units": str(image_hdu.header.get("BUNIT", "MJy/sr")).strip() or "MJy/sr",
            "zodi_subtracted": zodi_subtracted,
            "clean_image_mjy_sr": clean_image,
            "variance_mjy_sr2": clean_variance,
            "usable_mask": usable,
            "flagged_pixel_count": int(np.count_nonzero(flagged)),
            "usable_pixel_count": int(np.count_nonzero(usable)),
            "wcs": wcs,
            "pixel_scale_arcsec": (scale_x_arcsec, scale_y_arcsec),
            "x_cutout": x_cutout,
            "y_cutout": y_cutout,
            "x_orig": x_orig,
            "y_orig": y_orig,
            "detector_coord_mapping": det_mapping,
            "target_in_frame": target_in_frame,
            "wavelength_um": wavelength_um,
            "bandwidth_um": bandwidth_um,
            "wavelength_source": wavelength_source,
            "dichroic_impacted": dichroic_impacted,
            "epsf": epsf_data,
            "epsf_oversampling": epsf_oversampling,
            "source_archive": "NASA/IPAC IRSA",
            "synthetic": False,
        }


def _resample_epsf_stamp(
    epsf_2d: np.ndarray,
    oversampling: int,
    dx: float,
    dy: float,
) -> np.ndarray:
    """Shift and block-bin an oversampled 2-D ePSF onto native detector pixels."""
    epsf = np.asarray(epsf_2d, dtype=np.float64)
    ny, nx = epsf.shape
    if oversampling <= 1:
        total = float(np.sum(epsf))
        return epsf / total if total > 0 else epsf

    cy = (ny - 1) / 2.0
    cx = (nx - 1) / 2.0
    native_half = max(1, int(np.floor(min(ny, nx) / (2.0 * oversampling))))
    offsets = np.arange(-native_half, native_half + 1, dtype=np.int64)
    sub_offsets = (np.arange(oversampling, dtype=np.float64) + 0.5) / oversampling - 0.5

    stamp = np.zeros((offsets.size, offsets.size), dtype=np.float64)
    for iy, oy in enumerate(offsets):
        for ix, ox in enumerate(offsets):
            # Evaluate oversampled PSF centered at target (dx, dy) over native pixel [ox-0.5, ox+0.5]
            sy = cy + (oy - dy + sub_offsets[:, None]) * oversampling
            sx = cx + (ox - dx + sub_offsets[None, :]) * oversampling
            y0 = np.floor(sy).astype(np.int64)
            x0 = np.floor(sx).astype(np.int64)
            wy = sy - y0
            wx = sx - x0
            inside = (y0 >= 0) & (y0 < ny - 1) & (x0 >= 0) & (x0 < nx - 1)
            if not np.any(inside):
                continue
            y0c = np.clip(y0, 0, ny - 2)
            x0c = np.clip(x0, 0, nx - 2)
            vals = (
                (1.0 - wy) * (1.0 - wx) * epsf[y0c, x0c]
                + (1.0 - wy) * wx * epsf[y0c, x0c + 1]
                + wy * (1.0 - wx) * epsf[y0c + 1, x0c]
                + wy * wx * epsf[y0c + 1, x0c + 1]
            )
            stamp[iy, ix] = float(np.sum(np.where(inside, vals, 0.0)))

    total = float(np.sum(stamp))
    if total > 0:
        stamp /= total
    return stamp


def extract_forced_photometry(
    calibrated_frame: dict[str, Any],
    *,
    radius_pix: float = 1.5,
    use_epsf: bool = False,
    aperture_correction: float = 1.0,
    subtract_local_background: bool = True,
) -> dict[str, Any]:
    """Extract forced point-source flux (uJy) and AB magnitude at (x_cutout, y_cutout).

    Supports both circular aperture summation (with explicit `aperture_correction`)
    and optimal inverse-variance ePSF-weighted photometry when `use_epsf=True` and
    an `epsf` extension is present on the calibrated frame.
    """
    if not np.isfinite(radius_pix) or radius_pix <= 0:
        raise MefDataError("radius_pix must be positive and finite")
    if not np.isfinite(aperture_correction) or aperture_correction <= 0:
        raise MefDataError("aperture_correction must be positive and finite")

    img = np.asarray(calibrated_frame["clean_image_mjy_sr"], dtype=np.float64)
    var = np.asarray(calibrated_frame["variance_mjy_sr2"], dtype=np.float64)
    xc = float(calibrated_frame["x_cutout"])
    yc = float(calibrated_frame["y_cutout"])
    scale_x, scale_y = calibrated_frame.get(
        "pixel_scale_arcsec", (DEFAULT_NATIVE_PIXEL_SCALE_ARCSEC, DEFAULT_NATIVE_PIXEL_SCALE_ARCSEC)
    )
    omega_pix_sr = (float(scale_x) / ARCSEC_PER_RADIAN) * (float(scale_y) / ARCSEC_PER_RADIAN)
    mjy_sr_to_ujy_per_pix = 1e12 * omega_pix_sr

    base_meta = {
        "mjd_obs": calibrated_frame.get("mjd_obs"),
        "wavelength_um": calibrated_frame.get("wavelength_um"),
        "bandwidth_um": calibrated_frame.get("bandwidth_um"),
        "wavelength_source": calibrated_frame.get("wavelength_source", "unavailable"),
        "dichroic_impacted": bool(calibrated_frame.get("dichroic_impacted", False)),
        "zodi_subtracted": bool(calibrated_frame.get("zodi_subtracted", False)),
        "mjy_sr_to_ujy_per_pix": mjy_sr_to_ujy_per_pix,
        "source_archive": calibrated_frame.get("source_archive", "NASA/IPAC IRSA"),
        "synthetic": False,
    }

    if calibrated_frame.get("dichroic_impacted") or not calibrated_frame.get("target_in_frame", True):
        return {
            **base_meta,
            "method": "epsf_weighted" if use_epsf else "aperture",
            "flux_ujy": None,
            "flux_err_ujy": None,
            "ab_mag": None,
            "snr": 0.0,
            "aperture_corrected": False,
            "status": "dichroic_or_out_of_frame",
        }

    ny, nx = img.shape
    y_grid, x_grid = np.ogrid[:ny, :nx]
    dist2 = (x_grid - xc) ** 2 + (y_grid - yc) ** 2

    bg_median = 0.0
    bg_var_per_pix = 0.0
    if subtract_local_background:
        ann_mask = (
            (dist2 >= (radius_pix * 1.8) ** 2)
            & (dist2 <= (radius_pix * 3.5) ** 2)
            & np.isfinite(img)
        )
        ann_vals = img[ann_mask]
        if ann_vals.size >= 5:
            bg_median = float(np.median(ann_vals))
            mad = float(np.median(np.abs(ann_vals - bg_median)))
            bg_sigma = 1.4826 * mad
            bg_var_per_pix = (np.pi / 2.0) * (bg_sigma ** 2) / float(ann_vals.size)

    epsf_2d = calibrated_frame.get("epsf")
    if use_epsf and epsf_2d is not None:
        oversamp = int(calibrated_frame.get("epsf_oversampling") or 1)
        ix, iy = int(np.round(xc)), int(np.round(yc))
        dx, dy = xc - ix, yc - iy
        stamp = _resample_epsf_stamp(epsf_2d, oversamp, dx, dy)
        half = stamp.shape[0] // 2
        y0, y1 = max(0, iy - half), min(ny, iy + half + 1)
        x0, x1 = max(0, ix - half), min(nx, ix + half + 1)
        py0, px0 = y0 - (iy - half), x0 - (ix - half)
        sub_psf = stamp[py0 : py0 + (y1 - y0), px0 : px0 + (x1 - x0)]
        sub_img = img[y0:y1, x0:x1] - bg_median
        sub_var = var[y0:y1, x0:x1] + bg_var_per_pix
        valid = np.isfinite(sub_img) & np.isfinite(sub_var) & (sub_var > 0) & (sub_psf > 0)
        if not np.any(valid):
            return {
                **base_meta,
                "method": "epsf_weighted",
                "flux_ujy": None,
                "flux_err_ujy": None,
                "ab_mag": None,
                "snr": 0.0,
                "aperture_corrected": True,
                "status": "no_usable_pixels",
            }
        w = 1.0 / sub_var[valid]
        p = sub_psf[valid]
        denom = float(np.sum(w * p * p))
        if denom <= 0:
            raise MefDataError("Degenerate ePSF inverse-variance norm")
        amp_mjy_sr_pix = float(np.sum(w * p * sub_img[valid]) / denom)
        amp_err_mjy_sr_pix = float(np.sqrt(1.0 / denom))
        flux_ujy = amp_mjy_sr_pix * mjy_sr_to_ujy_per_pix
        flux_err_ujy = amp_err_mjy_sr_pix * mjy_sr_to_ujy_per_pix
        snr = flux_ujy / flux_err_ujy if flux_err_ujy > 0 else 0.0
        ab_mag = float(-2.5 * np.log10(flux_ujy / AB_ZERO_POINT_UJY)) if flux_ujy > 0 else None
        return {
            **base_meta,
            "method": "epsf_weighted",
            "flux_ujy": float(flux_ujy),
            "flux_err_ujy": float(flux_err_ujy),
            "ab_mag": ab_mag,
            "snr": float(snr),
            "aperture_corrected": True,
            "pixel_count": int(np.count_nonzero(valid)),
            "status": "completed",
        }

    ap_mask = (dist2 <= radius_pix ** 2) & np.isfinite(img) & np.isfinite(var) & (var > 0)
    n_ap = int(np.count_nonzero(ap_mask))
    if n_ap == 0:
        return {
            **base_meta,
            "method": "aperture",
            "flux_ujy": None,
            "flux_err_ujy": None,
            "ab_mag": None,
            "snr": 0.0,
            "aperture_corrected": aperture_correction != 1.0,
            "status": "no_usable_pixels",
        }

    net_sb = float(np.sum(img[ap_mask] - bg_median))
    net_var = float(np.sum(var[ap_mask]) + (n_ap ** 2) * bg_var_per_pix)
    flux_ujy = net_sb * mjy_sr_to_ujy_per_pix * float(aperture_correction)
    flux_err_ujy = np.sqrt(net_var) * mjy_sr_to_ujy_per_pix * float(aperture_correction)
    snr = flux_ujy / flux_err_ujy if flux_err_ujy > 0 else 0.0
    ab_mag = float(-2.5 * np.log10(flux_ujy / AB_ZERO_POINT_UJY)) if flux_ujy > 0 else None
    return {
        **base_meta,
        "method": "aperture",
        "flux_ujy": float(flux_ujy),
        "flux_err_ujy": float(flux_err_ujy),
        "ab_mag": ab_mag,
        "snr": float(snr),
        "aperture_corrected": aperture_correction != 1.0,
        "aperture_correction": float(aperture_correction),
        "pixel_count": n_ap,
        "status": "completed",
    }
