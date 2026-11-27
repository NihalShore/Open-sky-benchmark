"""DR1 All-Sky Cube discovery and FITS inspection.

This service uses IRSA SIA2 for tile discovery and reads the actual FITS
IMAGE/NHITS/FLAGS/SPECTRAL_CHANNELS extensions. HiPS PNGs are intentionally
not used for scientific measurements.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any
from urllib.parse import urlparse

import numpy as np
import requests
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image

from app.services.irsa import normalize_observation, query_sia

IRSA_HOST = "irsa.ipac.caltech.edu"
CUBE_COLLECTION = "spherex_dr1_cube"
# A DR1 tile carries IMAGE, NHITS, and FLAGS for 102 channels.
# The full official FITS product can exceed the previous 300 MiB cap.
MAX_FITS_BYTES = 512 * 1024 * 1024
REQUEST_TIMEOUT = (10, 90)


class CubeDataError(RuntimeError):
    """Raised when an archive product is not a valid supported cube."""


def trusted_cube_url(value: str) -> str:
    """Accept only clean HTTPS URLs on the official IRSA host and standard port."""
    if not isinstance(value, str) or any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise CubeDataError("Archive returned an invalid cube URL")
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != IRSA_HOST
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CubeDataError("Archive returned an untrusted cube URL")
    return value


MAX_CUBE_SEARCH_RECORDS = 100


def discover_cube_products(ra_deg: float, dec_deg: float, radius_arcsec: float = 30) -> list[dict[str, Any]]:
    """Find a bounded set of DR1 All-Sky Cube tiles overlapping an ICRS position."""
    table = query_sia(
        ra_deg,
        dec_deg,
        radius_arcsec,
        [CUBE_COLLECTION],
        maxrec=MAX_CUBE_SEARCH_RECORDS,
    )
    products: list[dict[str, Any]] = []
    for row in table:
        observation = normalize_observation(row)
        try:
            access_url = trusted_cube_url(observation["access_url"])
        except (KeyError, TypeError, ValueError, CubeDataError):
            continue
        products.append({
            "observation_id": observation["observation_id"],
            "collection": observation["collection"],
            "data_product_type": observation["data_product_type"],
            "access_format": observation["access_format"],
            "access_url": access_url,
            "source_archive": "NASA/IPAC IRSA",
            "synthetic": False,
        })
    return products


def _value(row: Any, key: str) -> Any:
    try:
        value = row[key]
        if np.ma.is_masked(value):
            return None
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value if isinstance(value, (str, int, float, bool)) else str(value)
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def download_cube(url: str) -> bytes:
    """Download one bounded FITS product without following redirects."""
    safe_url = trusted_cube_url(url)
    output = BytesIO()
    total = 0
    with requests.get(
        safe_url,
        stream=True,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False,
        headers={"User-Agent": "SPHEREx-TimeLens/0.3"},
    ) as response:
        response.raise_for_status()
        if 300 <= response.status_code < 400:
            raise CubeDataError("Unexpected redirect from the archive")
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                announced_size = int(content_length)
            except ValueError as exc:
                raise CubeDataError("Archive returned an invalid Content-Length") from exc
            if announced_size > MAX_FITS_BYTES:
                raise CubeDataError("Cube exceeds the configured download limit")
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_FITS_BYTES:
                raise CubeDataError("Cube exceeds the configured download limit")
            output.write(chunk)
    payload = output.getvalue()
    if not payload.startswith(b"SIMPLE"):
        raise CubeDataError("Archive response is not a FITS file")
    return payload


def _channel_axis(image: np.ndarray, channel_count: int) -> int:
    axes = [axis for axis, size in enumerate(image.shape) if size == channel_count]
    if len(axes) != 1:
        raise CubeDataError(f"Cannot identify spectral axis in IMAGE shape {image.shape}")
    return axes[0]


def _channel_wavelengths(hdu: fits.BinTableHDU) -> list[float | None]:
    names = list(hdu.columns.names or [])
    if "WAVELENGTH" not in names:
        return [None] * len(hdu.data)
    values = np.asarray(hdu.data["WAVELENGTH"]).reshape(-1)
    output: list[float | None] = []
    for value in values:
        try:
            number = float(value)
            output.append(number if np.isfinite(number) else None)
        except (TypeError, ValueError):
            output.append(None)
    return output


def _channel_value(row: Any, key: str) -> float | int | None:
    """Read a documented scalar from one SPECTRAL_CHANNELS row."""
    try:
        value = row[key]
        if np.ma.is_masked(value):
            return None
        number = float(value)
        if not np.isfinite(number):
            return None
        return int(number) if key in {"DETECTOR", "SUBCHAN"} else number
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def inspect_cube(
    payload: bytes,
    channel_index: int,
    *,
    ra_deg: float | None = None,
    dec_deg: float | None = None,
) -> tuple[dict[str, Any], np.ndarray]:
    """Validate a DR1 cube and return metadata plus a coverage-masked image plane."""
    if (ra_deg is None) != (dec_deg is None):
        raise CubeDataError("ra_deg and dec_deg must be supplied together")
    if channel_index < 0:
        raise CubeDataError("channel_index must be non-negative")

    with fits.open(BytesIO(payload), memmap=False) as hdus:
        by_name = {hdu.name.upper(): hdu for hdu in hdus}
        required = {"IMAGE", "NHITS", "FLAGS", "SPECTRAL_CHANNELS"}
        missing = required - set(by_name)
        if missing:
            raise CubeDataError(f"Cube is missing required extensions: {', '.join(sorted(missing))}")

        image = np.asarray(by_name["IMAGE"].data)
        nhits = np.asarray(by_name["NHITS"].data)
        flags = np.asarray(by_name["FLAGS"].data)
        channels_hdu = by_name["SPECTRAL_CHANNELS"]
        wavelengths = _channel_wavelengths(channels_hdu)
        channel_count = len(wavelengths)
        if channel_count != 102:
            raise CubeDataError(f"Expected 102 spectral-channel records, found {channel_count}")
        if channel_index >= channel_count:
            raise CubeDataError(f"channel_index must be between 0 and {channel_count - 1}")

        axis = _channel_axis(image, channel_count)
        image_cube = np.moveaxis(image, axis, 0)
        hits_cube = np.moveaxis(nhits, axis, 0)
        flags_cube = np.moveaxis(flags, axis, 0)
        if image_cube.shape != hits_cube.shape or image_cube.shape != flags_cube.shape:
            raise CubeDataError("IMAGE, NHITS, and FLAGS shapes do not match")

        blank_value = next(
            (hdu.header.get("BLANKCH") for hdu in hdus if hdu.header.get("BLANKCH") is not None),
            "",
        )
        blank_channels = str(blank_value).replace(" ", "")
        blank_values = {part for part in blank_channels.replace("[", "").replace("]", "").split(",") if part}
        if str(channel_index + 1) in blank_values:
            raise CubeDataError("The requested channel is marked blank by the FITS header")

        plane = image_cube[channel_index].astype(np.float32, copy=True)
        coverage = (hits_cube[channel_index] > 0) & np.isfinite(plane)
        plane[~coverage] = np.nan
        valid = plane[np.isfinite(plane)]
        metadata = {
            "channel_index": channel_index,
            "channel_number": channel_index + 1,
            "wavelength_um": wavelengths[channel_index],
            "wavelength_min_um": _channel_value(channels_hdu.data[channel_index], "WL_MIN"),
            "wavelength_max_um": _channel_value(channels_hdu.data[channel_index], "WL_MAX"),
            "bandwidth_um": _channel_value(channels_hdu.data[channel_index], "BANDWIDTH"),
            "resolving_power": _channel_value(channels_hdu.data[channel_index], "R"),
            "detector": _channel_value(channels_hdu.data[channel_index], "DETECTOR"),
            "subchannel": _channel_value(channels_hdu.data[channel_index], "SUBCHAN"),
            "image_shape": list(plane.shape),
            "valid_pixel_count": int(valid.size),
            "coverage_fraction": float(valid.size / plane.size),
            "units": str(by_name["IMAGE"].header.get("BUNIT", "MJy/sr")),
            "flags_extension_present": True,
            "flags_nonzero_pixel_count": int(np.count_nonzero(flags_cube[channel_index])),
            "zodiacal_light_subtracted": True,
            "blank_channels_header": blank_channels or None,
            "source_archive": "NASA/IPAC IRSA",
            "data_product": "SPHEREx DR1 All-Sky Cube",
            "dataset_doi": "10.26131/IRSA679",
            "synthetic": False,
        }
        metadata["query_pixel"] = None
        metadata["query_pixel_status"] = "not_requested"
        if ra_deg is not None and dec_deg is not None:
            try:
                celestial_wcs = WCS(by_name["IMAGE"].header, fobj=hdus).celestial
                query_position = SkyCoord(ra=ra_deg, dec=dec_deg, unit="deg", frame="icrs")
                pixel_x, pixel_y = celestial_wcs.world_to_pixel(query_position)
                if np.isfinite(pixel_x) and np.isfinite(pixel_y):
                    if 0 <= pixel_x < plane.shape[1] and 0 <= pixel_y < plane.shape[0]:
                        metadata["query_pixel"] = {
                            "x": float(pixel_x),
                            "y": float(pixel_y),
                        }
                        metadata["query_pixel_status"] = "available"
                    else:
                        metadata["query_pixel_status"] = "outside_image"
                else:
                    metadata["query_pixel_status"] = "unavailable"
            except Exception:
                metadata["query_pixel_status"] = "unavailable"

        if valid.size:
            metadata["value_percentiles"] = {
                "p01": float(np.nanpercentile(valid, 1)),
                "p50": float(np.nanpercentile(valid, 50)),
                "p99": float(np.nanpercentile(valid, 99)),
            }
        return metadata, plane


def render_preview_png(plane: np.ndarray) -> bytes:
    """Render a display-only grayscale PNG with uncovered pixels transparent."""
    valid_mask = np.isfinite(plane)
    valid = plane[valid_mask]
    if valid.size == 0:
        raise CubeDataError("Selected channel contains no covered finite pixels")
    low, high = np.nanpercentile(valid, [1, 99])
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        high = low + 1.0
    display_values = np.where(valid_mask, plane, low)
    scaled = np.clip((display_values - low) / (high - low), 0, 1)
    pixels = np.asarray(scaled * 255, dtype=np.uint8)
    alpha = valid_mask.astype(np.uint8) * 255
    rgba = np.dstack((pixels, pixels, pixels, alpha))
    output = BytesIO()
    # Keep the FITS array row order. The WCS pixel mapping uses the same
    # zero-based (x, y) coordinates as the rows and columns in this PNG.
    Image.fromarray(rgba).save(output, format="PNG")
    return output.getvalue()
