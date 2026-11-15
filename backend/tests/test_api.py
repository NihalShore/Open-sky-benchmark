from fastapi.testclient import TestClient

from app.main import app
from app import main

client = TestClient(app)


def test_health_does_not_call_remote_archive():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["archive_check"] == "not_run"


def test_search_validates_coordinates():
    response = client.post(
        "/api/v1/search",
        json={"ra_deg": 361, "dec_deg": 10},
    )

    assert response.status_code == 422


def test_search_returns_normalized_real_archive_metadata(monkeypatch):
    fake_observations = [
        {
            "observation_id": "TEST-OBS-001",
            "collection": "spherex_qr3",
            "ra_deg": 127.6,
            "dec_deg": -39.1,
            "synthetic": False,
            "source_archive": "NASA/IPAC IRSA",
            "access_url": "https://irsa.ipac.caltech.edu/example.fits",
        }
    ]

    def fake_search(ra_deg, dec_deg, radius_arcsec, collections):
        assert ra_deg == 127.6
        assert dec_deg == -39.1
        assert collections == ["spherex_dr1", "spherex_qr3"]
        return fake_observations

    monkeypatch.setattr(main, "search_spherex", fake_search)

    response = client.post(
        "/api/v1/search",
        json={"ra_deg": 127.6, "dec_deg": -39.1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result_count"] == 1
    assert payload["synthetic"] is False
    assert payload["observations"][0]["observation_id"] == "TEST-OBS-001"
