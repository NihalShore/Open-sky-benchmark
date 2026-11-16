"""Per-request IRSA client with bounded HTTP timeouts."""
from __future__ import annotations

import requests
from astroquery.ipac.irsa import IrsaClass

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30


class TimedSession(requests.Session):
    """Requests session that applies finite timeouts to archive traffic."""

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", (CONNECT_TIMEOUT, READ_TIMEOUT))
        return super().request(method, url, **kwargs)


def new_irsa_client() -> IrsaClass:
    """Create an isolated client and HTTP session for one archive operation."""
    client = IrsaClass()
    client._session = TimedSession()
    return client
