"""Run reproducible structural and pixel checks on a real SPHEREx DR1 cube."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from app.services.spherex_cube import discover_cube_products, download_cube, trusted_cube_url

CHANNELS = 102
BLANK_CHANNELS = (51, 52)


def build_celestial_wcs(image_hdu, hdus):
    """Build celestial WCS while keeping linked FITS table extensions available."""
    return WCS(image_hdu.header, fobj=hdus).celestial


def validate(payload: bytes, product: dict, query: dict) -> dict:
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_archive": "NASA/IPAC IRSA",
        "product": product,
        "query": query,
        "file": {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "fits_signature": payload.startswith(b"SIMPLE"),
        },
        "checks": [],
        "hdus": [],
        "channels": [],
    }

    def check(name: str, ok: bool, detail: str) -> None:
        report["checks"].append({
            "name": name, "status": "PASS" if ok else "FAIL", "detail": detail,
        })

    if not report["file"]["fits_signature"]:
        check("fits_signature", False, "Missing SIMPLE FITS signature")
        report["overall_status"] = "FAIL"
        return report
    check("fits_signature", True, "FITS primary signature present")

    with fits.open(BytesIO(payload), memmap=False, checksum=True) as hdus:
        names = [hdu.name.upper() for hdu in hdus]
        required = {"IMAGE", "NHITS", "FLAGS", "SPECTRAL_CHANNELS", "WCS-WAVE"}
        missing = sorted(required - set(names))
        check("required_hdus", not missing, "All required extensions present" if not missing else f"Missing: {missing}")

        for index, hdu in enumerate(hdus):
            item = {
                "index": index,
                "name": hdu.name,
                "type": type(hdu).__name__,
                "shape": list(hdu.data.shape) if hdu.data is not None else None,
                "dtype": str(hdu.data.dtype) if hdu.data is not None else None,
                "header": {
                    key: value for key, value in hdu.header.items()
                    if key.startswith(("CTYPE", "CUNIT", "CRPIX", "CRVAL", "CDELT", "CD", "PC", "WCS"))
                    or key in ("BUNIT", "BLANKCH", "CHECKSUM", "DATASUM")
                },
            }
            try:
                hdu.verify("exception")
                item["structural_verify"] = "PASS"
            except Exception as exc:
                item["structural_verify"] = f"FAIL: {type(exc).__name__}: {exc}"
            if "CHECKSUM" in hdu.header:
                item["checksum"] = "PASS" if hdu.verify_checksum() == 1 else "FAIL"
            if "DATASUM" in hdu.header:
                item["datasum"] = "PASS" if hdu.verify_datasum() == 1 else "FAIL"
            report["hdus"].append(item)

        if missing:
            report["overall_status"] = "FAIL"
            return report

        image_hdu = hdus[names.index("IMAGE")]
        image = np.asarray(image_hdu.data)
        hits = np.asarray(hdus[names.index("NHITS")].data)
        flags = np.asarray(hdus[names.index("FLAGS")].data)
        spectral = hdus[names.index("SPECTRAL_CHANNELS")]
        wave = hdus[names.index("WCS-WAVE")]

        rows = len(spectral.data) if spectral.data is not None else 0
        check("spectral_channel_rows", rows == CHANNELS, f"Found {rows}; expected {CHANNELS}")
        report["spectral_channels"] = {
            "rows": rows, "columns": list(spectral.columns.names or []),
        }
        report["wcs_wave"] = {
            "rows": len(wave.data) if wave.data is not None else 0,
            "columns": list(wave.columns.names or []) if wave.data is not None else [],
        }
        check("wcs_wave_table", wave.data is not None and len(wave.data) > 0,
              f"Found {report['wcs_wave']['rows']} WCS-WAVE rows")

        axes = [i for i, size in enumerate(image.shape) if size == CHANNELS]
        check("image_spectral_axis", len(axes) == 1, f"IMAGE shape {image.shape}; 102-channel axes: {axes}")
        same_shape = image.shape == hits.shape == flags.shape
        check("extension_shapes", same_shape,
              f"IMAGE={image.shape}; NHITS={hits.shape}; FLAGS={flags.shape}")

        if len(axes) == 1 and same_shape:
            axis = axes[0]
            cube = np.moveaxis(image, axis, 0)
            hit_cube = np.moveaxis(hits, axis, 0)
            flag_cube = np.moveaxis(flags, axis, 0)
            check("spatial_dimensions", cube.shape[-2:] == (512, 512),
                  f"Spatial shape {cube.shape[-2:]}; expected (512, 512)")

            for i in range(CHANNELS):
                plane = cube[i]
                hit_plane = hit_cube[i]
                flag_plane = flag_cube[i]
                finite = np.isfinite(plane)
                covered = hit_plane > 0
                valid = finite & covered
                values = plane[valid]
                row = {
                    "channel_number": i + 1,
                    "finite_pixels": int(finite.sum()),
                    "covered_pixels": int(covered.sum()),
                    "valid_pixels": int(valid.sum()),
                    "flags_nonzero_pixels": int(np.count_nonzero(flag_plane)),
                }
                if values.size:
                    p01, p50, p99 = np.nanpercentile(values, [1, 50, 99])
                    row["percentiles"] = {"p01": float(p01), "p50": float(p50), "p99": float(p99)}
                if i + 1 in BLANK_CHANNELS:
                    row["blank_channel_check"] = (
                        "PASS" if not finite.any() and not covered.any() and not np.any(flag_plane)
                        else "FAIL"
                    )
                report["channels"].append(row)

            blank_ok = all(report["channels"][n - 1]["blank_channel_check"] == "PASS"
                           for n in BLANK_CHANNELS)
            check("blank_channels_51_52", blank_ok,
                  "Both documented blank channels have all-NaN IMAGE, zero NHITS and zero FLAGS"
                  if blank_ok else "Channel 51 or 52 differs from documented blank-channel behavior")

            try:
                wcs = build_celestial_wcs(image_hdu, hdus)
                height, width = cube.shape[-2:]
                points = ((width / 2, height / 2), (0, 0), (width - 1, height - 1))
                samples = []
                for x, y in points:
                    sky = wcs.pixel_to_world(x, y)
                    back_x, back_y = wcs.world_to_pixel(sky)
                    error = float(np.hypot(back_x - x, back_y - y))
                    samples.append({
                        "pixel": [x, y],
                        "ra_deg": float(sky.icrs.ra.deg),
                        "dec_deg": float(sky.icrs.dec.deg),
                        "roundtrip_error_pixel": error,
                    })
                wcs_ok = wcs.has_celestial and all(
                    np.isfinite(p["roundtrip_error_pixel"]) and p["roundtrip_error_pixel"] <= 1e-3
                    for p in samples
                )
                report["celestial_wcs_samples"] = samples
                check("celestial_wcs_roundtrip", wcs_ok,
                      "WCS round-trip error <= 0.001 pixel at center and corners")
            except Exception as exc:
                check("celestial_wcs_roundtrip", False, f"{type(exc).__name__}: {exc}")

        integrity_failures = [
            f"{h['name']} HDU {h['index']}" for h in report["hdus"]
            if h.get("checksum") == "FAIL" or h.get("datasum") == "FAIL"
            or str(h.get("structural_verify", "")).startswith("FAIL")
        ]
        check("fits_integrity", not integrity_failures,
              "HDU structure and available FITS checksums passed"
              if not integrity_failures else "; ".join(integrity_failures))

    failed = [c["name"] for c in report["checks"] if c["status"] == "FAIL"]
    report["failed_checks"] = failed
    report["overall_status"] = "PASS" if not failed else "FAIL"
    report["scientific_validation"] = (
        "All configured structural, WCS, integrity, and blank-channel checks passed."
        if not failed else
        "Validation failed. This FITS product must not be described as scientifically verified."
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ra", type=float, required=True)
    parser.add_argument("--dec", type=float, required=True)
    parser.add_argument("--radius-arcsec", type=float, default=30)
    parser.add_argument("--access-url", help="Exact IRSA FITS URL; skips archive discovery")
    parser.add_argument("--output", type=Path, default=Path("spherex-validation-report.json"))
    args = parser.parse_args()
    query = {"ra_deg": args.ra, "dec_deg": args.dec, "radius_arcsec": args.radius_arcsec}
    if args.access_url:
        url = trusted_cube_url(args.access_url)
        product = {"access_url": url, "observation_id": "hips5_cube-hips_20261026", "collection": "spherex_dr1_cube", "source_archive": "NASA/IPAC IRSA", "synthetic": False}
    else:
        products = discover_cube_products(args.ra, args.dec, args.radius_arcsec)
        if not products:
            parser.error("IRSA returned no DR1 All-Sky Cube product for this position")
        product = products[0]
    payload = download_cube(product["access_url"])
    report = validate(payload, product, query)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["overall_status"],
        "failed_checks": report.get("failed_checks", []),
        "bytes": report["file"]["bytes"],
        "sha256": report["file"]["sha256"],
        "report": str(args.output),
    }, indent=2))
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
