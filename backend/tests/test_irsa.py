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
