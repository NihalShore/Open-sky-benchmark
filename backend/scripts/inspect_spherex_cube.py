"""Inspect a real SPHEREx DR1 All-Sky Cube FITS product.

Run from the backend directory:
    python scripts/inspect_spherex_cube.py --ra 127.69444 --dec -39.17760
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from astropy.io import fits
from astropy.wcs import WCS

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.spherex_cube import discover_cube_products, download_cube_file


WCS_PREFIXES = (
    "CTYPE", "CUNIT", "CRPIX", "CRVAL", "CDELT", "CD", "PC", "PV",
    "WCSAXES", "WCSNAME", "RADESYS", "EQUINOX", "LONPOLE", "LATPOLE",
)


def _header_summary(header: fits.Header) -> dict[str, Any]:
    return {
        key: value
        for key, value in header.items()
        if (key.startswith(WCS_PREFIXES) or key in {"BUNIT", "ORDER", "PIXTYPE", "INDXSCHM"})
        and isinstance(value, (str, int, float, bool))
    }


def _celestial_sample(header: fits.Header) -> dict[str, Any]:
    try:
        wcs = WCS(header).celestial
        if not wcs.has_celestial:
            return {"available": False, "reason": "No usable celestial WCS found"}

        pixel_shape = wcs.pixel_shape
        if pixel_shape and len(pixel_shape) == 2:
            width, height = pixel_shape
        else:
            width = header.get("NAXIS1")
            height = header.get("NAXIS2")
        if not width or not height:
            return {"available": False, "reason": "No usable celestial dimensions found"}

        pixels = {
            "center": ((width - 1) / 2, (height - 1) / 2),
            "lower_left": (0, 0),
            "upper_right": (width - 1, height - 1),
        }
        coordinates = {}
        for name, (x, y) in pixels.items():
            sky = wcs.pixel_to_world(x, y)
            coordinates[name] = {
                "ra_deg": float(sky.icrs.ra.deg),
                "dec_deg": float(sky.icrs.dec.deg),
            }
        return {"available": True, "pixel_to_sky": coordinates}
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def inspect_product(fits_source: bytes | Path, product: dict[str, Any]) -> dict[str, Any]:
    if isinstance(fits_source, Path):
        download_bytes = fits_source.stat().st_size
        source: Any = fits_source
    else:
        from io import BytesIO

        download_bytes = len(fits_source)
        source = BytesIO(fits_source)

    report: dict[str, Any] = {
        "product": product,
        "download_bytes": download_bytes,
        "hdus": [],
    }
    with fits.open(source, memmap=False) as hdus:
        for index, hdu in enumerate(hdus):
            shape = list(hdu.shape) if getattr(hdu, "shape", None) else None
            item: dict[str, Any] = {
                "index": index,
                "name": hdu.name,
                "hdu_type": type(hdu).__name__,
                "shape": shape,
                "header": _header_summary(hdu.header),
            }
            if hdu.name.upper() == "IMAGE" and shape is not None:
                item["celestial_wcs"] = _celestial_sample(hdu.header)
            if hdu.name.upper() == "SPECTRAL_CHANNELS" and hdu.data is not None:
                item["rows"] = len(hdu.data)
                item["columns"] = list(hdu.columns.names or [])
            report["hdus"].append(item)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ra", type=float, required=True, help="ICRS right ascension in degrees")
    parser.add_argument("--dec", type=float, required=True, help="ICRS declination in degrees")
    parser.add_argument(
        "--radius-arcsec", type=float, default=1800,
        help="SIA search radius in arcseconds (default: 1800)",
    )
    args = parser.parse_args()

    products = discover_cube_products(args.ra, args.dec, args.radius_arcsec)
    if not products:
        parser.error("IRSA returned no DR1 All-Sky Cube products for this position")

    product = products[0]
    with download_cube_file(product["access_url"]) as cube_path:
        print(json.dumps(inspect_product(cube_path, product), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
