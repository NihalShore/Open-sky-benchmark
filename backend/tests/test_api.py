from contextlib import contextmanager
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
import pytest

from app import main
from app.main import app
from app.services.spherex_cube import CubeDataError, CubeUpstreamError

client = TestClient(app)


def test_health_does_not_call_remote_archive():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["archive_check"] == "not_run"


def test_benchmark_targets_endpoint_returns_validation_metadata_without_remote_calls():
    response = client.get("/api/v1/benchmarks/targets?distance_au=500")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ephemeris_check"] == "not_run"
    assert payload["instrument"]["channels_total"] == 102
    assert payload["parallax_estimate"]["parallax_arcsec"] == pytest.approx(825.06, abs=0.1)
    target_ids = {t["id"] for t in payload["validation_targets"]}
    assert "3I/ATLAS" in target_ids
    assert "136472" in target_ids


def test_search_validates_coordinates():
    response = client.post(
        "/api/v1/search",
        json={"ra_deg": 361, "dec_deg": 10},
    )

    assert response.status_code == 422


def test_search_rejects_unknown_collection():
    response = client.post(
        "/api/v1/search",
        json={"ra_deg": 127.6, "dec_deg": -39.1, "collections": ["unknown_collection"]},
    )

    assert response.status_code == 422


def test_search_maps_upstream_error_to_502(monkeypatch):
    def failing_search(*args, **kwargs):
        raise RuntimeError("IRSA unreachable")

    monkeypatch.setattr(main, "search_spherex", failing_search)
    response = client.post(
        "/api/v1/search",
        json={"ra_deg": 127.6, "dec_deg": -39.1},
    )

    assert response.status_code == 502


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
        return [
            {
                "observation_id": "Npix4659_cube",
                "collection": "spherex_dr1_cube",
                "access_url": "https://irsa.ipac.caltech.edu/example.fits",
                "source_archive": "NASA/IPAC IRSA",
                "synthetic": False,
            }
        ]

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
        "flags_nonzero_pixel_count": 4,
    }
    monkeypatch.setattr(
        main,
        "discover_cube_products",
        lambda *args: [
            {
                "observation_id": "Npix4659\r\nX-Injected: bad",
                "collection": "spherex_dr1_cube",
                "access_url": "https://irsa.ipac.caltech.edu/example.fits",
            }
        ],
    )
    monkeypatch.setattr(main, "download_cube", lambda url: b"SIMPLE-fits-fixture")
    monkeypatch.setattr(main, "inspect_cube", lambda payload, channel: (metadata, object()))
    monkeypatch.setattr(main, "render_preview_png", lambda plane: b"\x89PNG\r\n\x1a\nfixture")

    response = client.get("/api/v1/cube/preview?ra_deg=127.6&dec_deg=-39.1&channel_index=0")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-spherex-source"] == "NASA/IPAC IRSA"
    assert response.headers["x-spherex-channel"] == "1"
    assert response.headers["x-spherex-wavelength-um"] == "0.8"
    assert response.headers["x-spherex-flags-nonzero-pixels"] == "4"
    assert response.headers["x-spherex-observation-id"] == "Npix4659X-Injected: bad"
    assert response.headers["x-spherex-synthetic"] == "false"


def test_cube_preview_uses_download_cube_file_when_unpatched(monkeypatch, tmp_path):
    dummy_path = tmp_path / "cube.fits"
    dummy_path.write_bytes(b"fixture")
    cleaned_up = []

    @contextmanager
    def fake_download_file(url):
        try:
            yield dummy_path
        finally:
            dummy_path.unlink(missing_ok=True)
            cleaned_up.append(not dummy_path.exists())

    monkeypatch.setattr(
        main,
        "discover_cube_products",
        lambda *args: [
            {
                "observation_id": "Npix4659_cube",
                "collection": "spherex_dr1_cube",
                "access_url": "https://irsa.ipac.caltech.edu/example.fits",
            }
        ],
    )
    monkeypatch.setattr(main, "download_cube_file", fake_download_file)
    monkeypatch.setattr(
        main,
        "inspect_cube",
        lambda path, channel: (
            {
                "channel_number": channel + 1,
                "wavelength_um": 1.2,
                "coverage_fraction": 0.5,
                "units": "MJy/sr",
                "flags_nonzero_pixel_count": 0,
            },
            object(),
        ),
    )
    monkeypatch.setattr(main, "render_preview_png", lambda plane: b"\x89PNG\r\n\x1a\nfixture")

    main._preview_cache.clear()
    response = client.get("/api/v1/cube/preview?ra_deg=127.6&dec_deg=-39.1&channel_index=2")

    assert response.status_code == 200
    assert cleaned_up == [True]
    assert response.headers["x-spherex-channel"] == "3"
    main._preview_cache.clear()


def test_cube_preview_rejects_channel_over_101():
    response = client.get("/api/v1/cube/preview?ra_deg=127.6&dec_deg=-39.1&channel_index=102")
    assert response.status_code == 422


def test_cube_preview_maps_upstream_error_to_502(monkeypatch):
    monkeypatch.setattr(
        main,
        "discover_cube_products",
        lambda *args: [{"access_url": "https://irsa.ipac.caltech.edu/example.fits"}],
    )

    @contextmanager
    def failing_download(url):
        raise CubeUpstreamError("IRSA download timed out")
        yield Path("/unused")

    monkeypatch.setattr(main, "download_cube_file", failing_download)

    response = client.get("/api/v1/cube/preview?ra_deg=127.6&dec_deg=-39.1&channel_index=0")

    assert response.status_code == 502


def test_cube_preview_maps_validation_error_to_422(monkeypatch):
    monkeypatch.setattr(
        main,
        "discover_cube_products",
        lambda *args: [{"access_url": "https://irsa.ipac.caltech.edu/example.fits"}],
    )
    monkeypatch.setattr(main, "download_cube", lambda url: b"SIMPLE-fits-fixture")

    def bad_cube(payload, channel):
        raise CubeDataError("Channel 51 is marked blank")

    monkeypatch.setattr(main, "inspect_cube", bad_cube)

    response = client.get("/api/v1/cube/preview?ra_deg=127.6&dec_deg=-39.1&channel_index=50")

    assert response.status_code == 422


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
        return fake_detections, True

    monkeypatch.setattr(main, "search_neowise_with_status", fake_search)
    response = client.get(
        "/api/v1/neowise/search?ra_deg=127.6&dec_deg=-39.1&radius_arcsec=15&limit=25"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog"] == "neowiser_p1bs_psd"
    assert payload["time_field"] == "mjd"
    assert payload["bands"] == ["W1", "W2"]
    assert payload["truncated"] is True
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
    assert "x-spherex-observation-id" in exposed


def test_cors_allows_project_preview_origin_and_rejects_unrelated_vercel_origin():
    allowed = client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://open-sky-timelens-git-feature-achme-63b5.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"].startswith("https://open-sky-timelens-")

    unrelated = client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://open-sky-timelens-evil.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in unrelated.headers


def test_cors_env_override_disables_preview_regex(monkeypatch):
    monkeypatch.setenv("TIMELENS_CORS_ORIGINS", "https://custom.example.org")
    cors_kwargs = main._cors_config()
    assert cors_kwargs["allow_origins"] == ["https://custom.example.org"]
    assert cors_kwargs["allow_origin_regex"] is None
    assert CORSMiddleware is not None
