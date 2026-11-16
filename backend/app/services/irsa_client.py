"""Per-request IRSA VO clients with bounded HTTP timeouts."""
from __future__ import annotations

import warnings

import requests
from astropy import units as u
from astropy.coordinates import SkyCoord
from pyvo.dal import SIA2Service, TAPService
from pyvo.dal.exceptions import DALOverflowWarning

IRSA_SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
IRSA_TAP_URL = "https://irsa.ipac.caltech.edu/TAP"
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30


class TimedSession(requests.Session):
    """Requests session that applies finite timeouts to archive traffic."""

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", (CONNECT_TIMEOUT, READ_TIMEOUT))
        return super().request(method, url, **kwargs)


class IrsaClient:
    """Small per-request wrapper around IRSA SIA2 and TAP services."""

    def __init__(self):
        self._session = TimedSession()
        self._sia = SIA2Service(
            IRSA_SIA_URL,
            session=self._session,
            check_baseurl=False,
        )
        self._tap = TAPService(IRSA_TAP_URL, session=self._session)

    def query_sia(self, *, pos, collection):
        """Run an ObsCore SIA2 position search and return its table."""
        position, radius = pos
        if not isinstance(position, SkyCoord):
            raise TypeError("SIA2 position must contain a SkyCoord")
        circle = (
            float(position.icrs.ra.deg),
            float(position.icrs.dec.deg),
            float(radius.to_value(u.deg)),
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DALOverflowWarning)
            results = self._sia.search(pos=circle, collection=collection, maxrec=500)
            table = results.to_table()
        if any(issubclass(item.category, DALOverflowWarning) for item in caught):
            table.meta["QUERY_STATUS"] = "OVERFLOW"
        return table

    def query_tap(self, query: str, *, maxrec: int | None = None):
        """Run a bounded ADQL query and preserve TAP overflow status."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DALOverflowWarning)
            results = self._tap.run_sync(query, maxrec=maxrec)
            table = results.to_table()
        if any(issubclass(item.category, DALOverflowWarning) for item in caught):
            table.meta["QUERY_STATUS"] = "OVERFLOW"
        return table

    def close(self) -> None:
        self._session.close()


def new_irsa_client() -> IrsaClient:
    """Create an isolated client and HTTP session for one archive operation."""
    return IrsaClient()
