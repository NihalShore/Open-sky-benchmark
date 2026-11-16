from io import BytesIO

import pytest
import requests
from astropy.table import Table

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


def test_query_sia_direct_uses_documented_endpoint_and_votable(monkeypatch):
    votable = Table({"obs_id": ["OBS-1"]})
    payload = BytesIO()
    votable.write(payload, format="votable")
    response = requests.Response()
    response.status_code = 200
    response.url = "https://irsa.ipac.caltech.edu/SIA"
    response._content = payload.getvalue()
    response._content_consumed = True
    calls = []

    def fake_get(session, url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(irsa._BoundedIrsaSession, "get", fake_get)
    result = irsa.query_sia_direct(
        127.6,
        -39.1,
        36.0,
        ["spherex_dr1", "spherex_qr3", "spherex_dr1"],
        maxrec=25,
    )

    assert list(result["obs_id"]) == ["OBS-1"]
    assert len(calls) == 1
    assert calls[0][0] == "https://irsa.ipac.caltech.edu/SIA"
    params = calls[0][1]["params"]
    assert ("POS", "CIRCLE 127.6000000000 -39.1000000000 0.0100000000") in params
    assert ("MAXREC", "25") in params
    assert ("RESPONSEFORMAT", "VOTABLE") in params
    assert [value for key, value in params if key == "COLLECTION"] == [
        "spherex_dr1",
        "spherex_qr3",
    ]


def test_search_spherex_cleans_nul_bytes_deduplicates_and_passes_maxrec(monkeypatch):
    calls = []

    def fake_query_sia(ra, dec, radius, collections, *, maxrec):
        calls.append((ra, dec, radius, collections, maxrec))
        return [
            {
                "obs_id": b"OBS-1\x00\x00",
                "obs_collection": "spherex_dr1",
                "s_ra": 127.6,
                "s_dec": -39.1,
                "access_url": "https://irsa.ipac.caltech.edu/a.fits",
            },
        ]

    monkeypatch.setattr(irsa, "query_sia", fake_query_sia)
    results = irsa.search_spherex(127.6, -39.1, 36.0, ["spherex_dr1", "spherex_dr1"])

    assert calls == [(127.6, -39.1, 36.0, ["spherex_dr1"], irsa.MAX_SIA_RECORDS)]
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
