"""IRSA SPHEREx SIA2 discovery adapter and thread-safe IRSA client factory.

This module discovers image products and normalizes archive metadata.
It deliberately does not download FITS files yet.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse

import astropy.units as u
import numpy as np
import requests
from astropy.coordinates import SkyCoord
from astroquery.ipac.irsa.core import IrsaClass

ALLOWED_COLLECTIONS = (
    "spherex_dr1",
    "spherex_dr1_deep",
    "spherex_dr1_cube",
    "spherex_qr3",
    "spherex_qr3_deep",
)
ALLOWED_COLLECTION_SET = frozenset(ALLOWED_COLLECTIONS)
IRSA_HOST = "irsa.ipac.caltech.edu"
IRSA_TIMEOUT: tuple[float, float] = (10.0, 30.0)
MAX_SIA_RECORDS = 1000


class _BoundedIrsaSession(requests.Session):
    """Per-request Session that enforces timeouts and restricts redirects to IRSA."""

    def __init__(self, timeout: tuple[float, float] = IRSA_TIMEOUT) -> None:
        super().__init__()
        self._default_timeout = timeout

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self._default_timeout
        follow_redirects = kwargs.pop("allow_redirects", True)
        kwargs["allow_redirects"] = False

        response = super().request(method, url, **kwargs)
        if not follow_redirects:
            return response

        hops = 0
        current_method = method
        current_kwargs = dict(kwargs)
        while 300 <= response.status_code < 400 and "location" in response.headers:
            if hops >= 5:
                response.close()
                raise requests.TooManyRedirects("Exceeded maximum IRSA redirect hops")
            next_url = urljoin(response.url, response.headers["location"])
            if _trusted_access_url(next_url) is None:
                response.close()
                raise ValueError("Blocked redirect to untrusted host outside IRSA")
            status = response.status_code
            response.close()
            hops += 1
            if status in (301, 302, 303) and current_method.upper() not in ("GET", "HEAD"):
                current_method = "GET"
                current_kwargs.pop("data", None)
                current_kwargs.pop("json", None)
            response = super().request(current_method, next_url, **current_kwargs)
        return response


@contextmanager
def irsa_client(timeout: tuple[float, float] = IRSA_TIMEOUT) -> Iterator[IrsaClass]:
    """Yield an isolated, thread-safe IRSA client with bounded HTTP timeouts."""
    client = IrsaClass()
    client._session.close()
    session = _BoundedIrsaSession(timeout=timeout)
    session.headers.update(client._session.headers)
    client._session = session
    try:
        yield client
    finally:
        session.close()


def validate_sky_query(
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    *,
    max_radius_arcsec: float = 1800.0,
) -> SkyCoord:
    """Validate ICRS sky coordinates and search radius."""
    if isinstance(ra_deg, bool) or not np.isfinite(ra_deg) or not (0.0 <= float(ra_deg) < 360.0):
        raise ValueError("ra_deg must be finite and in [0, 360)")
    if isinstance(dec_deg, bool) or not np.isfinite(dec_deg) or not (-90.0 <= float(dec_deg) <= 90.0):
        raise ValueError("dec_deg must be finite and in [-90, 90]")
    if (
        isinstance(radius_arcsec, bool)
        or not np.isfinite(radius_arcsec)
        or not (0.0 < float(radius_arcsec) <= max_radius_arcsec)
    ):
        raise ValueError(f"radius_arcsec must be finite and in (0, {max_radius_arcsec}]")
    return SkyCoord(ra=float(ra_deg), dec=float(dec_deg), unit="deg", frame="icrs")


def _plain_value(value: Any) -> Any:
    """Convert Astropy/NumPy scalar values into JSON-safe Python values."""
    if value is None or np.ma.is_masked(value):
        return None

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\x00 ")

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
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
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
    *,
    maxrec: int = MAX_SIA_RECORDS,
) -> list[dict[str, Any]]:
    """Query real SPHEREx spectral-image products that overlap a sky position.

    Uses the documented Astroquery IRSA SIA2 interface with bounded timeouts
    and record limits. Search results are metadata records; a returned
    access_url is not itself a FITS cutout.
    """
    if not collections:
        raise ValueError("At least one SPHEREx collection is required")
    deduped = list(dict.fromkeys(collections))
    invalid = sorted(set(deduped) - ALLOWED_COLLECTION_SET)
    if invalid:
        raise ValueError(f"Unsupported SPHEREx collection(s): {', '.join(invalid)}")
    if isinstance(maxrec, bool) or not isinstance(maxrec, int) or maxrec < 1:
        raise ValueError("maxrec must be a positive integer")

    position = validate_sky_query(ra_deg, dec_deg, radius_arcsec)
    radius = float(radius_arcsec) * u.arcsec

    with irsa_client() as client:
        table = client.query_sia(
            pos=(position, radius),
            collection=deduped,
            maxrec=maxrec,
        )
    return [normalize_observation(row) for row in table]
