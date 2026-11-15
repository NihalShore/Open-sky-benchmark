"""Inspect a real SPHEREx DR1 All-Sky Cube FITS product.

Run from the backend directory:
    python scripts/inspect_spherex_cube.py --ra 127.69444 --dec -39.17760
"""
from __future__ import annotations

import argparse
import json
from io import BytesIO
from typing import Any

from astropy.io import fits
from astropy.wcs import WCS

from app.services.spherex_cube import discover_cube_products, download_cube


WCS_PREFIXES = (
    "CTYPE", "CUNIT", "CRPIX", "CRVAL", "CDELT", "CD", "PC", "PV",
    "WCSAXES", "WCSNAME", "RADESYS", "EQUINOX", "LONPOLE", "LATPOLE",
)


def _header_summary(header: fits.Header) -> dict[str, Any]:
    return {
        key: value
        for key, value in header.items()
        if key.startswith(WCS_PREFIXES) or key in {"BUNIT", "ORDER", "PIXTYPE", "INDXSCHM"}
    }


def _celestial_sample(header: fits.Header, shape: tuple[int, ...]) -> dict[str, Any]:
    try:
        wcs = WCS(header).celestial
        if not wcs.has_celestial or len(shape) < 2:
            return {"available": False, "reason": "No celestial WCS found"}

        height, width = shape[-2:]
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


def inspect_product(payload: bytes, product: dict[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "product": product,
        "download_bytes": len(payload),
        "hdus": [],
    }
    with fits.open(BytesIO(payload), memmap=False) as hdus:
        for index, hdu in enumerate(hdus):
            data = hdu.data
            shape = list(data.shape) if data is not None else None
            item: dict[str, Any] = {
                "index": index,
                "name": hdu.name,
                "hdu_type": type(hdu).__name__,
                "shape": shape,
                "header": _header_summary(hdu.header),
            }
            if hdu.name.upper() == "IMAGE" and data is not None:
                item["celestial_wcs"] = _celestial_sample(
                    hdu.header, tuple(data.shape)
                )
            if hdu.name.upper() == "SPECTRAL_CHANNELS" and data is not None:
                item["rows"] = len(data)
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
    payload = download_cube(product["access_url"])
    print(json.dumps(inspect_product(payload, product), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
