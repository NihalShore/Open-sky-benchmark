import requests

from app.services.irsa_client import (
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
    IrsaClient,
    TimedSession,
)


def test_timed_session_applies_finite_connect_and_read_timeouts(monkeypatch):
    session = TimedSession()
    captured = {}

    def fake_request(self, method, url, **kwargs):
        captured.update(kwargs)
        return "response"

    monkeypatch.setattr(requests.Session, "request", fake_request)
    assert session.request("GET", "https://irsa.ipac.caltech.edu/query") == "response"
    assert captured["timeout"] == (CONNECT_TIMEOUT, READ_TIMEOUT)


def test_timed_session_preserves_explicit_timeout(monkeypatch):
    session = TimedSession()
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(kwargs)
        return "response"

    monkeypatch.setattr(requests.Session, "request", fake_request)
    session.request("GET", "https://irsa.ipac.caltech.edu/query", timeout=5)
    assert captured["timeout"] == 5


def test_new_irsa_client_uses_fresh_sessions():
    from app.services.irsa_client import new_irsa_client

    first = new_irsa_client()
    second = new_irsa_client()

    try:
        assert first is not second
        assert first._session is not second._session
        assert isinstance(first._session, TimedSession)
    finally:
        first.close()
        second.close()


def test_sia2_query_converts_skycoord_radius_to_adql_circle(monkeypatch):
    from astropy.coordinates import SkyCoord
    from astropy import units as u

    client = IrsaClient()
    captured = {}

    class Results:
        def to_table(self):
            return ["table"]

    class FakeSia:
        def search(self, **kwargs):
            captured.update(kwargs)
            return Results()

    client._sia = FakeSia()
    try:
        result = client.query_sia(
            pos=(SkyCoord(ra=120 * u.deg, dec=30 * u.deg), 30 * u.arcsec),
            collection=["spherex_dr1"],
        )
        assert result == ["table"]
        assert captured["pos"] == (120.0, 30.0, 30 / 3600)
        assert captured["collection"] == ["spherex_dr1"]
    finally:
        client.close()



def test_timed_session_rejects_cross_host_redirects():
    from requests import Response

    session = TimedSession()
    response = Response()
    response.status_code = 302
    response.url = "https://irsa.ipac.caltech.edu/query"
    response.headers["Location"] = "https://attacker.example/collect"

    assert session.get_redirect_target(response) is None


def test_timed_session_allows_same_host_https_redirects():
    from requests import Response

    session = TimedSession()
    response = Response()
    response.status_code = 302
    response.url = "https://irsa.ipac.caltech.edu/query"
    response.headers["Location"] = "/TAP/sync"

    assert session.get_redirect_target(response) == "/TAP/sync"
