from contextlib import contextmanager

import pytest
import requests

from app.services import irsa


@pytest.mark.parametrize(
    "value",
    [
        "http://irsa.ipac.caltech.edu/data/test.fits",
        "https://example.com/data/test.fits",
        "https://user@irsa.ipac.caltech.edu/data/test.fits",
        "https://irsa.ipac.caltech.edu:8443/data/test.fits",
        "https://irsa.ipac.caltech.edu:not-a-port/data/test.fits",
    ],
)
def test_untrusted_access_urls_are_rejected(value):
    assert irsa._trusted_access_url(value) is None


def test_official_irsa_https_url_is_accepted():
    value = "https://irsa.ipac.caltech.edu/data/test.fits"
    assert irsa._trusted_access_url(value) == value


def test_explicit_default_https_port_is_accepted():
    value = "https://irsa.ipac.caltech.edu:443/data/test.fits"
    assert irsa._trusted_access_url(value) == value


@pytest.mark.parametrize(
    ("ra", "dec", "radius"),
    [
        (360.0, 0.0, 30.0),
        (-0.1, 0.0, 30.0),
        (10.0, 90.1, 30.0),
        (10.0, -90.1, 30.0),
        (10.0, 0.0, 0.0),
        (10.0, 0.0, 1800.1),
        (float("nan"), 0.0, 30.0),
    ],
)
def test_validate_sky_query_rejects_out_of_bounds_inputs(ra, dec, radius):
    with pytest.raises(ValueError):
        irsa.validate_sky_query(ra, dec, radius)


def test_search_spherex_cleans_nul_bytes_deduplicates_and_passes_maxrec(monkeypatch):
    calls = []

    class FakeClient:
        def query_sia(self, **kwargs):
            calls.append(kwargs)
            return [
                {
                    "obs_id": b"OBS-1\x00\x00",
                    "obs_collection": "spherex_dr1",
                    "s_ra": 127.6,
                    "s_dec": -39.1,
                    "access_url": "https://irsa.ipac.caltech.edu/a.fits",
                },
            ]

    @contextmanager
    def fake_irsa_client():
        yield FakeClient()

    monkeypatch.setattr(irsa, "irsa_client", fake_irsa_client)
    results = irsa.search_spherex(127.6, -39.1, 36.0, ["spherex_dr1", "spherex_dr1"])

    assert len(calls) == 1
    assert calls[0]["collection"] == ["spherex_dr1"]
    assert calls[0]["maxrec"] == irsa.MAX_SIA_RECORDS
    assert len(results) == 1
    assert results[0]["observation_id"] == "OBS-1"


def test_bounded_session_blocks_off_host_redirects(monkeypatch):
    session = irsa._BoundedIrsaSession(timeout=(1.0, 2.0))
    resp = requests.Response()
    resp.status_code = 302
    resp.url = "https://irsa.ipac.caltech.edu/start"
    resp.headers["location"] = "https://evil.example/payload"
    resp._content_consumed = True

    monkeypatch.setattr(requests.Session, "request", lambda self, method, url, **kwargs: resp)

    with pytest.raises(ValueError, match="untrusted host outside IRSA"):
        session.request("GET", "https://irsa.ipac.caltech.edu/start")
