"""DR1 All-Sky Cube discovery and FITS inspection.

This service uses IRSA SIA2 for tile discovery and reads the actual FITS
IMAGE/NHITS/FLAGS/SPECTRAL_CHANNELS extensions. HiPS PNGs are intentionally
not used for scientific measurements.
"""
from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator
import tempfile
import zlib

import astropy.units as u
import numpy as np
import requests
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image

from app.services.irsa import _trusted_access_url, query_sia, validate_sky_query

IRSA_HOST = "irsa.ipac.caltech.edu"
CUBE_COLLECTION = "spherex_dr1_cube"
MAX_FITS_BYTES = 300 * 1024 * 1024
REQUEST_TIMEOUT: tuple[float, float] = (10.0, 90.0)
GZIP_MAGIC = b"\x1f\x8b"
SPECTRAL_CTYPE_PREFIXES = ("WAVE", "FREQ", "ENER", "AWAV", "VRAD", "VOPT", "SPEC", "CHAN")


class CubeDataError(ValueError):
    """Raised when a requested channel or cube selection is invalid."""


class CubeUpstreamError(CubeDataError):
    """Raised when an upstream archive product is untrusted, unreachable, or malformed."""


def trusted_cube_url(value: str) -> str:
    """Accept only HTTPS URLs on the official IRSA host and standard port."""
    if not isinstance(value, str):
        raise CubeUpstreamError("Archive returned an untrusted cube URL")
    safe = _trusted_access_url(value)
    if safe is None:
        raise CubeUpstreamError("Archive returned an untrusted cube URL")
    return safe


def _value(row: Any, key: str) -> Any:
    try:
        value = row[key]
        if np.ma.is_masked(value):
            return None
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").rstrip("\x00 ")
        if isinstance(value, float) and not np.isfinite(value):
            return None
        return value if isinstance(value, (str, int, float, bool)) else str(value)
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _is_fits_cube_row(data_product_type: Any, access_format: Any) -> bool:
    if isinstance(data_product_type, str) and data_product_type.strip().lower() not in {"", "cube"}:
        return False
    if isinstance(access_format, str) and access_format.strip():
        fmt = access_format.strip().lower()
        if "fits" not in fmt:
            return False
    return True


def discover_cube_products(ra_deg: float, dec_deg: float, radius_arcsec: float = 30) -> list[dict[str, Any]]:
    """Find DR1 All-Sky Cube tiles overlapping an ICRS position."""
    position = validate_sky_query(ra_deg, dec_deg, radius_arcsec)
    table = query_sia(
        ra_deg,
        dec_deg,
        radius_arcsec,
        [CUBE_COLLECTION],
        maxrec=100,
    )

    products: list[tuple[float, dict[str, Any]]] = []
    candidate_rows = 0
    untrusted_rows = 0

    for row in table:
        data_product_type = _value(row, "dataproduct_type")
        access_format = _value(row, "access_format")
        if not _is_fits_cube_row(data_product_type, access_format):
            continue
        candidate_rows += 1
        raw_url = _value(row, "access_url")
        try:
            access_url = trusted_cube_url(str(raw_url))
        except (TypeError, ValueError, CubeDataError):
            untrusted_rows += 1
            continue

        row_ra = _value(row, "s_ra")
        row_dec = _value(row, "s_dec")
        sep_deg = float("inf")
        if isinstance(row_ra, (int, float)) and isinstance(row_dec, (int, float)):
            try:
                tile_pos = SkyCoord(ra=float(row_ra), dec=float(row_dec), unit="deg", frame="icrs")
                sep_deg = float(position.separation(tile_pos).deg)
            except Exception:
                sep_deg = float("inf")

        products.append((
            sep_deg,
            {
                "observation_id": _value(row, "obs_id"),
                "collection": _value(row, "obs_collection"),
                "ra_deg": row_ra,
                "dec_deg": row_dec,
                "data_product_type": data_product_type,
                "access_format": access_format,
                "access_url": access_url,
                "source_archive": "NASA/IPAC IRSA",
                "synthetic": False,
            },
        ))

    if candidate_rows > 0 and untrusted_rows == candidate_rows:
        raise CubeUpstreamError("Archive returned only untrusted cube URLs")

    products.sort(key=lambda item: item[0])
    return [item[1] for item in products]


def _stream_response_to_sink(response: requests.Response, sink: Any) -> int:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_FITS_BYTES:
                raise CubeUpstreamError("Cube exceeds the configured download limit")
        except ValueError:
            pass

    raw_total = 0
    out_total = 0
    raw_prefix = bytearray()
    decomp_prefix = bytearray()
    header_checked = False
    is_gzip: bool | None = None
    decomp = None

    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if not chunk:
            continue
        raw_total += len(chunk)
        if raw_total > MAX_FITS_BYTES:
            raise CubeUpstreamError("Cube exceeds the configured download limit")

        if is_gzip is None:
            needed = max(0, 6 - len(raw_prefix))
            raw_prefix.extend(chunk[:needed])
            if len(raw_prefix) >= 2 and raw_prefix[:2] == GZIP_MAGIC:
                is_gzip = True
                decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
                payload_chunk = bytes(raw_prefix) + chunk[needed:]
                raw_prefix.clear()
                data = decomp.decompress(payload_chunk, MAX_FITS_BYTES - out_total + 1)
            elif len(raw_prefix) >= 6:
                is_gzip = False
                if not bytes(raw_prefix).startswith(b"SIMPLE"):
                    raise CubeUpstreamError("Archive response is not a FITS file")
                header_checked = True
                data = bytes(raw_prefix) + chunk[needed:]
                raw_prefix.clear()
            else:
                continue
        elif is_gzip:
            assert decomp is not None
            data = decomp.decompress(chunk, MAX_FITS_BYTES - out_total + 1)
        else:
            data = chunk

        if data:
            out_total += len(data)
            if out_total > MAX_FITS_BYTES:
                raise CubeUpstreamError("Decompressed cube exceeds the configured size limit")
            if not header_checked:
                decomp_prefix.extend(data)
                if len(decomp_prefix) < 6:
                    continue
                if not bytes(decomp_prefix).startswith(b"SIMPLE"):
                    raise CubeUpstreamError("Archive gzip payload is not a FITS file")
                header_checked = True
                sink.write(bytes(decomp_prefix))
                decomp_prefix.clear()
            else:
                sink.write(data)

    if is_gzip is None:
        if not bytes(raw_prefix).startswith(b"SIMPLE"):
            raise CubeUpstreamError("Archive response is not a FITS file")
        sink.write(bytes(raw_prefix))
        out_total += len(raw_prefix)
    elif is_gzip and decomp is not None:
        tail = decomp.flush(MAX_FITS_BYTES - out_total + 1)
        out_total += len(tail)
        if out_total > MAX_FITS_BYTES:
            raise CubeUpstreamError("Decompressed cube exceeds the configured size limit")
        if not header_checked:
            decomp_prefix.extend(tail)
            if not bytes(decomp_prefix).startswith(b"SIMPLE"):
                raise CubeUpstreamError("Archive gzip payload is not a FITS file")
            sink.write(bytes(decomp_prefix))
        elif tail:
            sink.write(tail)

    return out_total


@contextmanager
def download_cube_file(url: str) -> Iterator[Path]:
    """Stream one bounded FITS product into a temporary file without redirects."""
    safe_url = trusted_cube_url(url)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".fits", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            with requests.get(
                safe_url,
                stream=True,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
                headers={"User-Agent": "SPHEREx-TimeLens/0.3"},
            ) as response:
                if 300 <= response.status_code < 400:
                    raise CubeUpstreamError("Unexpected redirect from the archive")
                response.raise_for_status()
                _stream_response_to_sink(response, tmp)
        yield tmp_path
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def download_cube(url: str) -> bytes:
    """Download one bounded FITS product into memory without following redirects."""
    safe_url = trusted_cube_url(url)
    buffer = BytesIO()
    with requests.get(
        safe_url,
        stream=True,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False,
        headers={"User-Agent": "SPHEREx-TimeLens/0.3"},
    ) as response:
        if 300 <= response.status_code < 400:
            raise CubeUpstreamError("Unexpected redirect from the archive")
        response.raise_for_status()
        _stream_response_to_sink(response, buffer)
    return buffer.getvalue()


def _spectral_axis_index(hdu: fits.hdu.base.ExtensionHDU, channel_count: int) -> int:
    shape = hdu.shape
    if not shape or len(shape) < 3:
        raise CubeUpstreamError(f"Expected 3-D cube in {hdu.name}, found shape {shape}")

    ndim = len(shape)
    header = hdu.header
    try:
        wcs = WCS(header)
        if wcs.wcs.spec >= 0:
            np_axis = ndim - 1 - int(wcs.wcs.spec)
            if 0 <= np_axis < ndim and shape[np_axis] == channel_count:
                return np_axis
    except Exception:
        pass

    header_axes: list[int] = []
    for fits_axis in range(1, ndim + 1):
        ctype = str(header.get(f"CTYPE{fits_axis}", "")).strip().upper()
        if ctype.startswith(SPECTRAL_CTYPE_PREFIXES):
            np_axis = ndim - fits_axis
            if shape[np_axis] == channel_count:
                header_axes.append(np_axis)
    if len(header_axes) == 1:
        return header_axes[0]

    axes = [axis for axis, size in enumerate(shape) if size == channel_count]
    if len(axes) != 1:
        raise CubeUpstreamError(f"Cannot identify spectral axis in {hdu.name} shape {shape}")
    return axes[0]


def _extract_channel_slice(hdu: Any, spectral_axis: int, channel_index: int) -> np.ndarray:
    """Read only one 2-D channel plane from a 3-D FITS HDU."""
    shape = hdu.shape
    indexer = tuple(
        channel_index if axis == spectral_axis else slice(None)
        for axis in range(len(shape))
    )
    if isinstance(hdu, fits.CompImageHDU):
        total_bytes = int(np.prod(shape)) * 4
        if total_bytes > MAX_FITS_BYTES:
            raise CubeUpstreamError("Compressed FITS cube exceeds uncompressed memory budget")
        return np.asarray(hdu.data[indexer])
    return np.asarray(hdu.section[indexer])


def _channel_columns_map(hdu: fits.BinTableHDU) -> dict[str, str]:
    names = list(hdu.columns.names or [])
    return {name.upper(): name for name in names}


def _channel_wavelengths(hdu: fits.BinTableHDU, col_map: dict[str, str]) -> list[float | None]:
    wl_col = col_map.get("WAVELENGTH")
    if not wl_col:
        return [None] * len(hdu.data)
    values = np.asarray(hdu.data[wl_col]).reshape(-1)
    output: list[float | None] = []
    for value in values:
        try:
            number = float(value)
            output.append(number if np.isfinite(number) else None)
        except (TypeError, ValueError):
            output.append(None)
    return output


def _channel_value(row: Any, col_map: dict[str, str], key: str) -> float | int | None:
    """Read a documented scalar from one SPECTRAL_CHANNELS row."""
    col_name = col_map.get(key.upper())
    if not col_name:
        return None
    try:
        value = row[col_name]
        if np.ma.is_masked(value):
            return None
        number = float(value)
        if not np.isfinite(number):
            return None
        return int(number) if key.upper() in {"DETECTOR", "SUBCHAN"} else number
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _parse_blank_channels(hdus: fits.HDUList) -> tuple[str | None, set[int]]:
    blank_value = next(
        (hdu.header.get("BLANKCH") for hdu in hdus if hdu.header.get("BLANKCH") is not None),
        None,
    )
    if blank_value is None:
        return None, set()
    blank_channels = str(blank_value).replace(" ", "")
    tokens = [
        part
        for part in blank_channels.replace("[", "").replace("]", "").split(",")
        if part
    ]
    parsed: set[int] = set()
    for token in tokens:
        try:
            parsed.add(int(token))
        except ValueError:
            continue
    return blank_channels or None, parsed


def _header_bool(hdus: fits.HDUList, key: str) -> bool | None:
    for hdu in hdus:
        val = hdu.header.get(key)
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)) and val in (0, 1):
            return bool(val)
        if isinstance(val, str):
            norm = val.strip().upper()
            if norm in {"T", "TRUE", "YES", "1"}:
                return True
            if norm in {"F", "FALSE", "NO", "0"}:
                return False
    return None


def _header_str(hdus: fits.HDUList, keys: tuple[str, ...]) -> str | None:
    for hdu in hdus:
        for key in keys:
            val = hdu.header.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def inspect_cube(payload: bytes | str | Path, channel_index: int) -> tuple[dict[str, Any], np.ndarray]:
    """Validate a DR1 cube and return metadata plus a coverage-masked image plane."""
    if isinstance(channel_index, bool) or not isinstance(channel_index, int) or channel_index < 0:
        raise CubeDataError("channel_index must be a non-negative integer")

    source: Any = payload if isinstance(payload, (str, Path)) else BytesIO(payload)

    try:
        # memmap=False avoids strict_memmap failures on BZERO-scaled uint16 NHITS/FLAGS
        # while hdu.section[...] still reads only the single requested channel slice from disk.
        hdus_ctx = fits.open(source, memmap=False)
    except Exception as exc:
        raise CubeUpstreamError(f"Could not open FITS payload: {exc}") from exc

    with hdus_ctx as hdus:
        by_name = {hdu.name.upper(): hdu for hdu in hdus if hdu.name}
        required = {"IMAGE", "NHITS", "FLAGS", "SPECTRAL_CHANNELS"}
        missing = required - set(by_name)
        if missing:
            raise CubeUpstreamError(f"Cube is missing required extensions: {', '.join(sorted(missing))}")

        image_hdu = by_name["IMAGE"]
        nhits_hdu = by_name["NHITS"]
        flags_hdu = by_name["FLAGS"]
        channels_hdu = by_name["SPECTRAL_CHANNELS"]

        if channels_hdu.data is None:
            raise CubeUpstreamError("SPECTRAL_CHANNELS table is empty")

        col_map = _channel_columns_map(channels_hdu)
        wavelengths = _channel_wavelengths(channels_hdu, col_map)
        channel_count = len(wavelengths)
        if channel_count != 102:
            raise CubeUpstreamError(f"Expected 102 spectral-channel records, found {channel_count}")
        if channel_index >= channel_count:
            raise CubeDataError(f"channel_index must be between 0 and {channel_count - 1}")

        axis = _spectral_axis_index(image_hdu, channel_count)
        if image_hdu.shape != nhits_hdu.shape or image_hdu.shape != flags_hdu.shape:
            raise CubeUpstreamError("IMAGE, NHITS, and FLAGS shapes do not match")

        blank_raw, blank_numbers = _parse_blank_channels(hdus)
        if (channel_index + 1) in blank_numbers:
            raise CubeDataError("The requested channel is marked blank by the FITS header")

        plane = _extract_channel_slice(image_hdu, axis, channel_index).astype(np.float32, copy=True)
        hits_slice = _extract_channel_slice(nhits_hdu, axis, channel_index)
        flags_slice = _extract_channel_slice(flags_hdu, axis, channel_index)

        coverage = (hits_slice > 0) & np.isfinite(plane)
        plane[~coverage] = np.nan
        valid = plane[coverage]
        row = channels_hdu.data[channel_index]

        metadata = {
            "channel_index": channel_index,
            "channel_number": channel_index + 1,
            "wavelength_um": wavelengths[channel_index],
            "wavelength_min_um": _channel_value(row, col_map, "WL_MIN"),
            "wavelength_max_um": _channel_value(row, col_map, "WL_MAX"),
            "bandwidth_um": _channel_value(row, col_map, "BANDWIDTH"),
            "resolving_power": _channel_value(row, col_map, "R"),
            "detector": _channel_value(row, col_map, "DETECTOR"),
            "subchannel": _channel_value(row, col_map, "SUBCHAN"),
            "image_shape": list(plane.shape),
            "valid_pixel_count": int(valid.size),
            "coverage_fraction": float(valid.size / plane.size) if plane.size else 0.0,
            "units": str(image_hdu.header.get("BUNIT", "unknown")).strip() or "unknown",
            "flags_extension_present": True,
            "flags_nonzero_pixel_count": int(np.count_nonzero(flags_slice[coverage])) if np.any(coverage) else 0,
            "flags_total_nonzero_pixel_count": int(np.count_nonzero(flags_slice)),
            "zodiacal_light_subtracted": _header_bool(hdus, "ZODISUB"),
            "blank_channels_header": blank_raw,
            "source_archive": "NASA/IPAC IRSA",
            "data_product": "SPHEREx DR1 All-Sky Cube",
            "dataset_doi": _header_str(hdus, ("DOI", "REFERENC")),
            "observation_id": _header_str(hdus, ("OBS_ID", "TILE_ID", "OBJECT")),
            "synthetic": False,
        }
        if valid.size:
            metadata["value_percentiles"] = {
                "p01": float(np.nanpercentile(valid, 1)),
                "p50": float(np.nanpercentile(valid, 50)),
                "p99": float(np.nanpercentile(valid, 99)),
            }
        return metadata, plane


def render_preview_png(plane: np.ndarray) -> bytes:
    """Render a display-only RGBA PNG with transparent missing-coverage pixels."""
    plane = np.asarray(plane, dtype=np.float64)
    if plane.ndim != 2:
        raise CubeDataError("Preview plane must be two-dimensional")
    finite_mask = np.isfinite(plane)
    valid = plane[finite_mask]
    if valid.size == 0:
        raise CubeDataError("Selected channel contains no covered finite pixels")

    low, high = np.nanpercentile(valid, [1, 99])
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        high = low + 1.0
    scaled = np.clip((np.nan_to_num(plane, nan=low) - low) / (high - low), 0.0, 1.0)

    # Flip vertically so FITS row 0 (South/bottom) appears at the bottom of the PNG.
    gray = np.flipud(np.asarray(scaled * 255.0, dtype=np.uint8))
    alpha = np.flipud(np.where(finite_mask, np.uint8(255), np.uint8(0)))
    rgba = np.stack([gray, gray, gray, alpha], axis=-1)

    output = BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
    return output.getvalue()
