"""DR1 All-Sky Cube discovery and FITS inspection.

This service uses IRSA SIA2 for tile discovery and reads the actual FITS
IMAGE/NHITS/FLAGS/SPECTRAL_CHANNELS extensions. HiPS PNGs are intentionally
not used for scientific measurements.
"""
from __future__ import annotations

from io import BytesIO
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO
from urllib.parse import urlparse

import numpy as np
import requests
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u
from app.services.irsa_client import new_irsa_client
from PIL import Image

IRSA_HOST = "irsa.ipac.caltech.edu"
CUBE_COLLECTION = "spherex_dr1_cube"
MAX_FITS_BYTES = 300 * 1024 * 1024
MAX_CUBE_PLANE_BYTES = 128 * 1024 * 1024
SPOOL_MEMORY_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT = (10, 90)


class CubeDataError(RuntimeError):
    """Raised when an archive product is not a valid supported cube."""


def trusted_cube_url(value: str) -> str:
    """Accept only HTTPS URLs on the official IRSA host and standard port."""
    try:
        parsed = urlparse(value)
        trusted = (
            parsed.scheme == "https"
            and parsed.hostname == IRSA_HOST
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
        )
    except (TypeError, ValueError):
        trusted = False
    if not trusted:
        raise CubeDataError("Archive returned an untrusted cube URL")
    return value


def discover_cube_products(ra_deg: float, dec_deg: float, radius_arcsec: float = 30) -> list[dict[str, Any]]:
    """Find DR1 All-Sky Cube tiles overlapping an ICRS position."""
    position = SkyCoord(ra=ra_deg, dec=dec_deg, unit="deg", frame="icrs")
    table = new_irsa_client().query_sia(
        pos=(position, radius_arcsec * u.arcsec),
        collection=CUBE_COLLECTION,
    )
    products: list[dict[str, Any]] = []
    rejected_urls = 0
    for row in table:
        access_format = _value(row, "access_format")
        product_type = _value(row, "dataproduct_type")
        if access_format and "fits" not in str(access_format).lower():
            continue
        if product_type and str(product_type).lower() != "cube":
            continue
        try:
            access_url = trusted_cube_url(str(row["access_url"]))
        except (KeyError, TypeError, ValueError, CubeDataError):
            rejected_urls += 1
            continue
        products.append({
            "observation_id": _value(row, "obs_id"),
            "collection": _value(row, "obs_collection"),
            "data_product_type": product_type,
            "access_format": access_format,
            "access_url": access_url,
            "source_archive": "NASA/IPAC IRSA",
            "synthetic": False,
        })
    if not products and rejected_urls:
        raise CubeDataError("IRSA returned cube records with untrusted access URLs")
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


def download_cube(url: str) -> BinaryIO:
    """Stream one bounded FITS product to a spooled temporary file."""
    safe_url = trusted_cube_url(url)
    payload = SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode="w+b")
    total = 0
    try:
        with requests.get(
            safe_url,
            stream=True,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
            headers={"User-Agent": "SPHEREx-TimeLens/0.2"},
        ) as response:
            if 300 <= response.status_code < 400:
                raise CubeDataError("Unexpected redirect from the archive")
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except (TypeError, ValueError) as exc:
                    raise CubeDataError("Archive returned an invalid Content-Length") from exc
                if declared_size < 0 or declared_size > MAX_FITS_BYTES:
                    raise CubeDataError("Cube exceeds the configured download limit")
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_FITS_BYTES:
                    raise CubeDataError("Cube exceeds the configured download limit")
                payload.write(chunk)
        payload.seek(0)
        if payload.read(6) != b"SIMPLE":
            raise CubeDataError("Archive response is not an uncompressed FITS file")
        payload.seek(0)
        return payload
    except Exception:
        payload.close()
        raise


def _channel_axis(
    image: np.ndarray | tuple[int, ...],
    channel_count: int,
    header: fits.Header | None = None,
) -> int:
    image_shape = image.shape if hasattr(image, "shape") else tuple(image)
    if header is not None:
        try:
            wcs = WCS(header)
            physical_types = wcs.world_axis_physical_types or []
            spectral_world_axes = [
                index for index, physical_type in enumerate(physical_types)
                if physical_type and (
                    physical_type.startswith("em.")
                    or physical_type.startswith("spect.")
                )
            ]
            if len(spectral_world_axes) == 1:
                pixel_axes = np.flatnonzero(
                    wcs.axis_correlation_matrix[spectral_world_axes[0]]
                )
                if len(pixel_axes) == 1:
                    numpy_axis = image.ndim - 1 - int(pixel_axes[0])
                    if 0 <= numpy_axis < len(image_shape) and image_shape[numpy_axis] == channel_count:
                        return numpy_axis
        except Exception:
            pass

    axes = [axis for axis, size in enumerate(image_shape) if size == channel_count]
    if len(axes) != 1:
        raise CubeDataError(f"Cannot identify spectral axis from FITS WCS or IMAGE shape {image_shape}")
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


def inspect_cube(payload: bytes | BinaryIO, channel_index: int) -> tuple[dict[str, Any], np.ndarray]:
    """Read one channel from a DR1 cube without materializing the full cube."""
    if channel_index < 0:
        raise CubeDataError("channel_index must be non-negative")

    if isinstance(payload, (bytes, bytearray)):
        source: BinaryIO = BytesIO(payload)
        memmap = False
    else:
        source = payload
        source.seek(0)
        memmap = True

    with fits.open(source, memmap=memmap, lazy_load_hdus=True) as hdus:
        by_name = {hdu.name.upper(): hdu for hdu in hdus}
        required = {"IMAGE", "NHITS", "FLAGS", "SPECTRAL_CHANNELS"}
        missing = required - set(by_name)
        if missing:
            raise CubeDataError(f"Cube is missing required extensions: {', '.join(sorted(missing))}")

        image_hdu = by_name["IMAGE"]
        nhits_hdu = by_name["NHITS"]
        flags_hdu = by_name["FLAGS"]
        channels_hdu = by_name["SPECTRAL_CHANNELS"]
        if any(isinstance(hdu, fits.CompImageHDU) for hdu in (image_hdu, nhits_hdu, flags_hdu)):
            raise CubeDataError("Tile-compressed FITS image extensions are not supported")

        image_shape = image_hdu.shape
        nhits_shape = nhits_hdu.shape
        flags_shape = flags_hdu.shape
        if not image_shape or image_shape != nhits_shape or image_shape != flags_shape:
            raise CubeDataError("IMAGE, NHITS, and FLAGS shapes do not match")

        wavelengths = _channel_wavelengths(channels_hdu)
        channel_count = len(wavelengths)
        if channel_count != 102:
            raise CubeDataError(f"Expected 102 spectral-channel records, found {channel_count}")
        if channel_index >= channel_count:
            raise CubeDataError(f"channel_index must be between 0 and {channel_count - 1}")

        axis = _channel_axis(image_shape, channel_count, image_hdu.header)
        plane_shape = tuple(size for index, size in enumerate(image_shape) if index != axis)
        pixels = int(np.prod(plane_shape, dtype=np.int64))
        bitpix_bytes = {8: 1, 16: 2, 32: 4, 64: 8, -32: 4, -64: 8}
        plane_bytes = pixels * sum(
            bitpix_bytes.get(int(hdu.header.get("BITPIX", -32)), 8)
            for hdu in (image_hdu, nhits_hdu, flags_hdu)
        )
        if plane_bytes > MAX_CUBE_PLANE_BYTES:
            raise CubeDataError("Selected cube plane exceeds the configured memory limit")

        index = [slice(None)] * len(image_shape)
        index[axis] = channel_index
        index = tuple(index)
        plane = np.asarray(image_hdu.section[index], dtype=np.float32).copy()
        hits = np.asarray(nhits_hdu.section[index])
        flags = np.asarray(flags_hdu.section[index])
        if plane.shape != plane_shape or hits.shape != plane_shape or flags.shape != plane_shape:
            raise CubeDataError("Selected IMAGE, NHITS, and FLAGS planes do not match")

        blank_value = next(
            (hdu.header.get("BLANKCH") for hdu in hdus if hdu.header.get("BLANKCH") is not None),
            "",
        )
        blank_channels = str(blank_value).replace(" ", "")
        blank_values = {
            part for part in blank_channels.replace("[", "").replace("]", "").split(",") if part
        }
        if str(channel_index + 1) in blank_values:
            raise CubeDataError("The requested channel is marked blank by the FITS header")

        coverage = (hits > 0) & np.isfinite(plane)
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
            "units": str(image_hdu.header.get("BUNIT", "unknown")),
            "flags_extension_present": True,
            "flags_nonzero_pixel_count": int(np.count_nonzero((flags != 0) & (hits > 0))),
            "blank_channels_header": blank_channels or None,
            "source_archive": "NASA/IPAC IRSA",
            "data_product": "SPHEREx DR1 All-Sky Cube",
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
    """Render a display-only grayscale preview using robust percentile scaling."""
    valid = plane[np.isfinite(plane)]
    if valid.size == 0:
        raise CubeDataError("Selected channel contains no covered finite pixels")
    low, high = np.nanpercentile(valid, [1, 99])
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        high = low + 1.0
    valid_mask = np.isfinite(plane)
    scaled = np.clip((np.nan_to_num(plane, nan=low) - low) / (high - low), 0, 1)
    pixels = np.asarray(scaled * 255, dtype=np.uint8)
    rgba = np.zeros((*pixels.shape, 4), dtype=np.uint8)
    rgba[..., :3] = pixels[..., None]
    rgba[..., 3] = np.where(valid_mask, 255, 0).astype(np.uint8)
    output = BytesIO()
    Image.fromarray(np.flipud(rgba), mode="RGBA").save(output, format="PNG")
    return output.getvalue()
