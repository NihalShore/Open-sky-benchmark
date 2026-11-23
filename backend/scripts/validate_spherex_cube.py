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
        return repֻǱ˞