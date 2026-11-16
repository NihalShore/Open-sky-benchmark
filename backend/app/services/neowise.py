"""NEOWISE single-exposure source discovery through IRSA."""
from __future__ import annotations

from typing import Any

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astroquery.ipac.irsa import Irsa

NEOWISE_CATALOG = "neowiser_p1bs_psd"
NEOWISE_COLUMNS = (
    "ra,dec,mjd,scan_id,frame_num,w1mpro,w1sigmpro,w1snr,"
    "w2mpro,w2sigmpro,w2snr,ph_qual,qual_frame,cc_flags,saa_sep"
)


def _value(row: Any, name: str) -> Any:
    try:
        value = row[name]
        if value is None or np.ma.is_masked(value):
            return None
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").rstrip("\x00 ")
        if isinstance(value, (float, np.floating)) and not np.isfinite(value):
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def normalize_detection(row: Any) -> dict[str, Any]:
    """Keep the archive's measurement and quality fields without filtering."""
    return {
        "ra_deg": _value(row, "ra"),
        "dec_deg": _value(row, "dec"),
        "mjd": _value(row, "mjd"),
        "scan_id": _value(row, "scan_id"),
        "frame_num": _value(row, "frame_num"),
        "w1_mag": _value(row, "w1mpro"),
        "w1_mag_error": _value(row, "w1sigmpro"),
        "w1_snr": _value(row, "w1snr"),
        "w2_mag": _value(row, "w2mpro"),
        "w2_mag_error": _value(row, "w2sigmpro"),
        "w2_snr": _value(row, "w2snr"),
        "photometric_quality": _value(row, "ph_qual"),
        "frame_quality": _value(row, "qual_frame"),
        "contamination_flags": _value(row, "cc_flags"),
        "saa_separation_deg": _value(row, "saa_sep"),
        "source_archive": "NASA/IPAC IRSA",
        "catalog": NEOWISE_CATALOG,
        "synthetic": False,
    }


def search_neowise(
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return NEOWISE-R single-exposure detections near an ICRS position."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if not np.isfinite(radius_arcsec) or radius_arcsec <= 0:
        raise ValueError("radius_arcsec must be positive and finite")

    position = SkyCoord(ra=ra_deg, dec=dec_deg, unit="deg", frame="icrs")
    table = Irsa.query_region(
        coordinates=position,
        catalog=NEOWISE_CATALOG,
        spatial="Cone",
        radius=radius_arcsec * u.arcsec,
        columns=NEOWISE_COLUMNS,
    )
    detections = [normalize_detection(row) for row in table]
    detections = [row for row in detections if row["mjd"] is not None]
    detections.sort(key=lambda row: (row["mjd"], str(row["scan_id"]), str(row["frame_num"])))
    return detections[:limit]
