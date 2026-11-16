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



def test_cube_search_uses_dr1_cube_collection_and_returns_provenance(monkeypatch):
    def fake_discovery(ra_deg, dec_deg, radius_arcsec):
        assert (ra_deg, dec_deg, radius_arcsec) == (127.6, -39.1, 30)
        return [{
            "observation_id": "Npix4659_cube",
            "collection": "spherex_dr1_cube",
            "access_url": "https://irsa.ipac.caltech.edu/example.fits",
            "source_archive": "NASA/IPAC IRSA",
            "synthetic": False,
        }]

    monkeypatch.setattr(main, "discover_cube_products", fake_discovery)
    response = client.get("/api/v1/cube/search?ra_deg=127.6&dec_deg=-39.1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["collection"] == "spherex_dr1_cube"
    assert payload["result_count"] == 1
    assert payload["products"][0]["synthetic"] is False


def test_cube_preview_returns_png_and_provenance_headers(monkeypatch):
    metadata = {
        "channel_number": 1,
        "wavelength_um": 0.8,
        "coverage_fraction": 0.75,
        "units": "MJy/sr",
    }
    monkeypatch.setattr(main, "discover_cube_products", lambda *args: [
        {"access_url": "https://irsa.ipac.caltech.edu/example.fits"}
    ])
    monkeypatch.setattr(main, "download_cube", lambda url: b"SIMPLE-fits-fixture")
    monkeypatch.setattr(main, "inspect_cube", lambda payload, channel: (metadata, object()))
    monkeypatch.setattr(main, "render_preview_png", lambda plane: b"\x89PNG\r\n\x1a\nfixture")

    response = client.get("/api/v1/cube/preview?ra_deg=127.6&dec_deg=-39.1&channel_index=0")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-spherex-source"] == "NASA/IPAC IRSA"
    assert response.headers["x-spherex-channel"] == "1"
    assert response.headers["x-spherex-wavelength-um"] == "0.8"
    assert response.headers["x-spherex-synthetic"] == "false"



def test_neowise_search_returns_time_ordered_archive_measurements(monkeypatch):
    fake_detections = [
        {
            "mjd": 59000.0,
            "w1_mag": 12.3,
            "w2_mag": 11.8,
            "photometric_quality": "AAXX",
            "source_archive": "NASA/IPAC IRSA",
            "synthetic": False,
        }
    ]

    def fake_search(ra_deg, dec_deg, radius_arcsec, limit):
        assert (ra_deg, dec_deg, radius_arcsec, limit) == (127.6, -39.1, 15, 25)
        return {"detections": fake_detections, "truncated": False}

    monkeypatch.setattr(main, "search_neowise", fake_search)
    response = client.get(
        "/api/v1/neowise/search?ra_deg=127.6&dec_deg=-39.1&radius_arcsec=15&limit=25"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog"] == "neowiser_p1bs_psd"
    assert payload["time_field"] == "mjd"
    assert payload["truncated"] is False
    assert payload["bands"] == ["W1", "W2"]
    assert payload["detections"][0]["mjd"] == 59000.0
    assert payload["synthetic"] is False


def test_neowise_search_validates_limit():
    response = client.get(
        "/api/v1/neowise/search?ra_deg=127.6&dec_deg=-39.1&limit=501"
    )

    assert response.status_code == 422


def test_cors_allows_production_frontend_and_exposes_fits_headers():
    response = client.get("/api/v1/health", headers={"Origin": "https://open-sky-timelens.vercel.app"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://open-sky-timelens.vercel.app"
    exposed = response.headers["access-control-expose-headers"].lower()
    assert "x-spherex-wavelength-um" in exposed
    assert "x-spherex-flags-nonzero-pixels" in exposed


def test_cors_rejects_unlisted_vercel_project_origin():
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://open-sky-timelens-untrusted.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
