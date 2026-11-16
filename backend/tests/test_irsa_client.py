import requests

from app.services.irsa_client import READ_TIMEOUT, CONNECT_TIMEOUT, TimedSession, new_irsa_client


def test_timed_session_applies_finite_connect_and_read_timeouts(monkeypatch):
    session = TimedSession()
    captured = {}

    def fake_request(method, url, **kwargs):
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


def test_new_irsa_client_uses_a_fresh_session():
    first = new_irsa_client()
    second = new_irsa_client()

    assert first is not second
    assert first._session is not second._session
    assert isinstance(first._session, TimedSession)
