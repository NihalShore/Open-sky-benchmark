"""NEOWISE single-exposure source discovery through IRSA TAP."""
from __future__ import annotations

from typing import Any

import numpy as np
from app.services.irsa_client import new_irsa_client

NEOWISE_CATALOG = "neowiser_p1bs_psd"
NEOWISE_COLUMNS = (
    "cntr,ra,dec,mjd,scan_id,frame_num,w1mpro,w1sigmpro,w1snr,"
    "w2mpro,w2sigmpro,w2snr,w1rchi2,w2rchi2,nb,na,qi_fact,"
    "moon_masked,ph_qual,qual_frame,cc_flags,saa_sep"
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
        "source_id": _value(row, "cntr"),
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
        "w1_psf_chi2": _value(row, "w1rchi2"),
        "w2_psf_chi2": _value(row, "w2rchi2"),
        "blend_count": _value(row, "nb"),
        "active_deblend_count": _value(row, "na"),
        "quality_factor": _value(row, "qi_fact"),
        "moon_masked": _value(row, "moon_masked"),
        "photometric_quality": _value(row, "ph_qual"),
        "frame_quality": _value(row, "qual_frame"),
        "contamination_flags": _value(row, "cc_flags"),
        "saa_separation_deg": _value(row, "saa_sep"),
        "source_archive": "NASA/IPAC IRSA",
        "catalog": NEOWISE_CATALOG,
        "synthetic": False,
    }


def _numeric_sort_value(value: Any) -> tuple[int, float | str]:
    try:
        number = float(value)
        if np.isfinite(number):
            return (0, number)
    except (TypeError, ValueError):
        pass
    return (1, str(value))


def search_neowise(
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    limit: int = 500,
) -> dict[str, Any]:
    """Return a bounded, MJD-ordered NEOWISE-R result and truncation status."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be an integer between 1 and 500")
    if not np.isfinite(ra_deg) or not 0 <= ra_deg < 360:
        raise ValueError("ra_deg must be in [0, 360)")
    if not np.isfinite(dec_deg) or not -90 <= dec_deg <= 90:
        raise ValueError("dec_deg must be in [-90, 90]")
    if not np.isfinite(radius_arcsec) or not 0 < radius_arcsec <= 1800:
        raise ValueError("radius_arcsec must be in (0, 1800]")

    radius_deg = radius_arcsec / 3600.0
    query = (
        f"SELECT TOP {limit + 1} {NEOWISE_COLUMNS} "
        f"FROM {NEOWISE_CATALOG} "
        "WHERE CONTAINS(POINT('ICRS', ra, dec), "
        f"CIRCLE('ICRS', {ra_deg:.12f}, {dec_deg:.12f}, {radius_deg:.12f})) = 1 "
        "ORDER BY mjd ASC, scan_id ASC, frame_num ASC"
    )
    client = new_irsa_client()
    try:
        table = client.query_tap(query, maxrec=limit + 1)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    detections = [normalize_detection(row) for row in table]
    detections = [row for row in detections if row["mjd"] is not None]
    detections.sort(
        key=lambda row: (
            _numeric_sort_value(row["mjd"]),
            _numeric_sort_value(row["scan_id"]),
            _numeric_sort_value(row["frame_num"]),
        )
    )
    overflow = "OVERFLOW" in str(getattr(table, "meta", {})).upper()
    truncated = overflow or len(detections) > limit
    return {
        "detections": detections[:limit],
        "truncated": truncated,
    }
