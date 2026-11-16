from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_pipeline_capabilities_report_variance_and_limitations():
    response = client.get("/api/v1/pipeline/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["wcs_reprojection"] is True
    assert payload["coverage_aware_difference"] is True
    assert payload["variance_propagation"] is True
    assert payload["psf_matching"] is False
    assert payload["photometric_scaling"] is False
