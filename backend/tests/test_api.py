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
        return fake_detections

    monkeypatch.setattr(main, "search_neowise", fake_search)
    response = client.get(
        "/api/v1/neowise/search?ra_deg=127.6&dec_deg=-39.1&radius_arcsec=15&limit=25"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog"] == "neowiser_p1bs_psd"
    assert payload["time_field"] == "mjd"
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


def test_cors_allows_time_lens_preview_origin():
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "https://open-sky-timelens-git-feature-achme-63b5.vercel.app", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"].startswith("https://open-sky-timelens-")


def test_cube_preview_reuses_the_discovered_irsa_url(monkeypatch):
    metadata = {
        "channel_number": 1,
        "wavelength_um": 0.8,
        "coverage_fraction": 0.75,
        "units": "MJy/sr",
    }
    product_url = "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/example.fits"

    def fail_discovery(*args):
        raise AssertionError("preview should reuse the URL returned by cube search")

    def fake_download(url):
        assert url == product_url
        return b"SIMPLE-fits-fixture"

    monkeypatch.setattr(main, "discover_cube_products", fail_discovery)
    monkeypatch.setattr(main, "download_cube", fake_download)
    monkeypatch.setattr(main, "inspect_cube", lambda payload, channel: (metadata, object()))
    monkeypatch.setattr(main, "render_preview_png", lambda plane: b"\x89PNG\r\n\x1a\nfixture")

    response = client.get(
        "/api/v1/cube/preview",
        params={
            "ra_deg": 127.6,
            "dec_deg": -39.1,
            "channel_index": 0,
            "access_url": product_url,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_cube_preview_rejects_untrusted_access_url():
    response = client.get(
        "/api/v1/cube/preview",
        params={
            "ra_deg": 127.6,
            "dec_deg": -39.1,
            "access_url": "https://example.com/fake.fits",
        },
    )

    assert response.status_code == 422


def test_cube_preview_metadata_mode_returns_inspected_metadata(monkeypatch):
    metadata = {
        "channel_number": 1,
        "wavelength_um": 0.8,
        "coverage_fraction": 0.75,
        "source_archive": "NASA/IPAC IRSA",
        "synthetic": False,
    }
    product_url = "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/example.fits"
    monkeypatch.setattr(main, "discover_cube_products", lambda *args: [
        {"access_url": product_url}
    ])
    monkeypatch.setattr(main, "download_cube", lambda url: b"SIMPLE-fits-fixture")
    monkeypatch.setattr(main, "inspect_cube", lambda payload, channel: (metadata, object()))
    monkeypatch.setattr(
        main, "render_preview_png",
        lambda plane: (_ for _ in ()).throw(AssertionError("metadata mode should not render PNG")),
    )

    response = client.get(
        "/api/v1/cube/preview",
        params={
            "ra_deg": 127.6,
            "dec_deg": -39.1,
            "metadata_only": "true",
        },
    )

    assert response.status_code == 200
    assert response.json()["source_archive"] == "NASA/IPAC IRSA"
    assert response.json()["synthetic"] is False


def test_hips_metadata_returns_official_102_channel_wavelengths(monkeypatch):
    class FakeResponse:
        text = "hips_cube_depth = 102\ndata_cube_crval3_arr = " + " ".join(
            str(0.75 + index * 0.04) for index in range(102)
        )

        def raise_for_status(self):
            return None

    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: FakeResponse())
    response = client.get("/api/v1/hips/metadata")

    assert response.status_code == 200
    payload = response.json()
    assert payload["frame_count"] == 102
    assert len(payload["wavelength_um"]) == 102
    assert payload["source_archive"] == "NASA/IPAC IRSA"
    assert payload["display_only"] is True
    assert payload["synthetic"] is False


def test_hips_frame_proxies_official_png(monkeypatch):
    class FakeResponse:
        headers = {"Content-Type": "image/png"}
        content = b"\\x89PNG\\r\\n\\x1a\\nfixture"

        def raise_for_status(self):
            return None

    requested = {}
    def fake_get(url, **kwargs):
        requested["url"] = url
        return FakeResponse()

    monkeypatch.setattr(main.requests, "get", fake_get)
    response = client.get("/api/v1/hips/frame/9822/0")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-spherex-source"] == "NASA/IPAC IRSA"
    assert requested["url"].endswith("/Norder5/Dir0/Npix9822.png")


def test_hips_frame_rejects_invalid_tile_and_channel():
    assert client.get("/api/v1/hips/frame/12288/0").status_code == 422
    assert client.get("/api/v1/hips/frame/9822/102").status_code == 422
