"""IRSA SPHEREx SIA2 discovery adapter.

This module discovers image products and normalizes archive metadata.
It deliberately does not download FITS files yet.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astroquery.ipac.irsa import Irsa

ALLOWED_COLLECTIONS = {
    "spherex_dr1",
    "spherex_dr1_deep",
    "spherex_dr1_cube",
    "spherex_qr3",
    "spherex_qr3_deep",
}
IRSA_HOST = "irsa.ipac.caltech.edu"


def _plain_value(value: Any) -> Any:
    """Convert Astropy/NumPy scalar values into JSON-safe Python values."""
    if value is None or np.ma.is_masked(value):
        return None

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if isinstance(value, np.generic):
        value = value.item()

    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not np.isfinite(value):
            return None
        return value

    try:
        if np.ma.is_masked(value):
            return None
    except (TypeError, ValueError):
        pass

    return str(value)


def _column(row: Any, name: str) -> Any:
    """Read a metadata column safely, returning None when it is absent."""
    try:
        return _plain_value(row[name])
    except (KeyError, TypeError, IndexError, ValueError):
        return None


def _trusted_access_url(value: Any) -> str | None:
    """Expose only HTTPS access URLs hosted by the official IRSA archive."""
    url = _plain_value(value)
    if not isinstance(url, str):
        return None

    try:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != IRSA_HOST
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
    except ValueError:
        return None
    return url


def normalize_observation(row: Any) -> dict[str, Any]:
    """Normalize an IRSA SIA2 table row for the frontend."""
    return {
        "observation_id": _column(row, "obs_id"),
        "collection": _column(row, "obs_collection"),
        "ra_deg": _column(row, "s_ra"),
        "dec_deg": _column(row, "s_dec"),
        "facility": _column(row, "facility_name"),
        "instrument": _column(row, "instrument_name"),
        "data_product_type": _column(row, "dataproduct_type"),
        "bandpass_name": _column(row, "energy_bandpassname"),
        "wavelength_min": _column(row, "em_min"),
        "wavelength_max": _column(row, "em_max"),
        "observation_start_mjd": _column(row, "t_min"),
        "observation_end_mjd": _column(row, "t_max"),
        "access_format": _column(row, "access_format"),
        "access_url": _trusted_access_url(_column(row, "access_url")),
        "synthetic": False,
        "source_archive": "NASA/IPAC IRSA",
    }


def search_spherex(
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    collections: list[str],
) -> list[dict[str, Any]]:
    """Query real SPHEREx spectral-image products that overlap a sky position.

    Uses the documented Astroquery IRSA SIA2 interface. Search results are
    metadata records; a returned access_url is not itself a FITS cutout.
    """
    invalid = sorted(set(collections) - ALLOWED_COLLECTIONS)
    if invalid:
        raise ValueError(f"Unsupported SPHEREx collection(s): {', '.join(invalid)}")

    position = SkyCoord(ra=ra_deg, dec=dec_deg, unit="deg", frame="icrs")
    radius = radius_arcsec * u.arcsec

    table = Irsa.query_sia(
        pos=(position, radius),
        collection=collections,
    )
    return [normalize_observation(row) for row in table]
