import pytest

from app.services.irsa import _trusted_access_url


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
    assert _trusted_access_url(value) is None


def test_official_irsa_https_url_is_accepted():
    value = "https://irsa.ipac.caltech.edu/data/test.fits"
    assert _trusted_access_url(value) == value


def test_explicit_default_https_port_is_accepted():
    value = "https://irsa.ipac.caltech.edu:443/data/test.fits"
    assert _trusted_access_url(value) == value



def test_search_spherex_validates_and_deduplicates_collections(monkeypatch):
    from app.services import irsa

    calls = {}

    class FakeClient:
        def query_sia(self, **kwargs):
            calls.update(kwargs)
            return []

    monkeypatch.setattr(irsa, "new_irsa_client", lambda: FakeClient())
    result = irsa.search_spherex(
        120.0, 30.0, 15.0, ["spherex_dr1", "spherex_dr1"]
    )

    assert result == []
    assert calls["collection"] == ["spherex_dr1"]


def test_search_spherex_rejects_invalid_coordinates():
    from app.services.irsa import search_spherex

    with pytest.raises(ValueError, match="ra_deg"):
        search_spherex(360.0, 0.0, 15.0, ["spherex_dr1"])
