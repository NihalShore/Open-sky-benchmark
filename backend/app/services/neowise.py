"""NEOWISE single-exposure source discovery through IRSA."""
from __future__ import annotations

from typing import Any

import astropy.units as u
import numpy as np

from app.services.irsa import irsa_client, validate_sky_query

NEOWISE_CATALOG = "neowiser_p1bs_psd"
NEOWISE_COLUMNS = (
    "cntr,source_id,ra,dec,sigra,sigdec,sigradec,mjd,scan_id,frame_num,"
    "w1mpro,w1sigmpro,w1snr,w1rchi2,w2mpro,w2sigmpro,w2snr,w2rchi2,rchi2,"
    "ph_qual,det_bit,qual_frame,cc_flags,saa_sep,nb,na,qi_fact,moon_masked,"
    "sso_flg,w1frtr,w2frtr,allwise_cntr,r_allwise,n_allwise,tmass_key,r_2mass,n_2mass"
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
        # cntr/source_id identify one extraction on one frameset, not a persistent source.
        "source_cntr": _value(row, "cntr"),
        "source_id": _value(row, "source_id"),
        "ra_deg": _value(row, "ra"),
        "dec_deg": _value(row, "dec"),
        "ra_uncertainty_arcsec": _value(row, "sigra"),
        "dec_uncertainty_arcsec": _value(row, "sigdec"),
        "ra_dec_covariance_arcsec2": _value(row, "sigradec"),
        "mjd": _value(row, "mjd"),
        "scan_id": _value(row, "scan_id"),
        "frame_num": _value(row, "frame_num"),
        "w1_mag": _value(row, "w1mpro"),
        "w1_mag_error": _value(row, "w1sigmpro"),
        "w1_snr": _value(row, "w1snr"),
        "w1_rchi2": _value(row, "w1rchi2"),
        "w2_mag": _value(row, "w2mpro"),
        "w2_mag_error": _value(row, "w2sigmpro"),
        "w2_snr": _value(row, "w2snr"),
        "w2_rchi2": _value(row, "w2rchi2"),
        "profile_fit_rchi2": _value(row, "rchi2"),
        "photometric_quality": _value(row, "ph_qual"),
        "detection_bits": _value(row, "det_bit"),
        "frame_quality": _value(row, "qual_frame"),
        "contamination_flags": _value(row, "cc_flags"),
        "saa_separation_deg": _value(row, "saa_sep"),
        "blend_count": _value(row, "nb"),
        "active_deblend": _value(row, "na"),
        "quality_info_factor": _value(row, "qi_fact"),
        "moon_masked": _value(row, "moon_masked"),
        "solar_system_association_flag": _value(row, "sso_flg"),
        "w1_transient_flags": _value(row, "w1frtr"),
        "w2_transient_flags": _value(row, "w2frtr"),
        "allwise_source_id": _value(row, "allwise_cntr"),
        "allwise_separation_arcsec": _value(row, "r_allwise"),
        "allwise_match_count": _value(row, "n_allwise"),
        "tmass_source_id": _value(row, "tmass_key"),
        "tmass_separation_arcsec": _value(row, "r_2mass"),
        "tmass_match_count": _value(row, "n_2mass"),
        "source_archive": "NASA/IPAC IRSA",
        "catalog": NEOWISE_CATALOG,
        "synthetic": False,
    }


def _sort_key(row: dict[str, Any]) -> tuple[float, str, int, str]:
    frame = row.get("frame_num")
    if isinstance(frame, int) and not isinstance(frame, bool):
        frame_num, frame_str = frame, ""
    else:
        frame_num, frame_str = -1, str(frame or "")
    return (
        float(row["mjd"]),
        str(row.get("scan_id") or ""),
        frame_num,
        frame_str,
    )


def search_neowise_with_status(
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    limit: int = 500,
) -> tuple[list[dict[str, Any]], bool]:
    """Return bounded, MJD-ordered NEOWISE-R measurements and truncation state."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 500:
        raise ValueError("limit must be a positive integer between 1 and 500")

    position = validate_sky_query(ra_deg, dec_deg, radius_arcsec)
    ra = float(position.ra.deg)
    dec = float(position.dec.deg)
    radius_deg = float((float(radius_arcsec) * u.arcsec).to_value(u.deg))

    fetch_cap = limit + 1
    adql = (
        f"SELECT TOP {fetch_cap} {NEOWISE_COLUMNS} "
        f"FROM {NEOWISE_CATALOG} "
        f"WHERE CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra:.10f},{dec:.10f},{radius_deg:.10f}))=1 "
        "AND mjd IS NOT NULL "
        "ORDER BY mjd ASC, scan_id ASC, frame_num ASC"
    )

    with irsa_client() as client:
        response = client.query_tap(query=adql, async_job=False, maxrec=fetch_cap)
        table = response.to_table() if hasattr(response, "to_table") else response

    detections = [normalize_detection(row) for row in table]
    detections = [row for row in detections if row["mjd"] is not None]
    detections.sort(key=_sort_key)
    truncated = len(detections) > limit
    return detections[:limit], truncated


def search_neowise(
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return NEOWISE-R single-exposure detections near an ICRS position."""
    detections, _ = search_neowise_with_status(ra_deg, dec_deg, radius_arcsec, limit)
    return detections
