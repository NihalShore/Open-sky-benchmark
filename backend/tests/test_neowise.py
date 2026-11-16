import pytest

from app.services import neowise


def test_normalize_detection_keeps_time_photometry_and_quality():
    row = {
        "cntr": 456, "ra": 127.6, "dec": -39.1, "mjd": 59000.25, "scan_id": b"01234",
        "frame_num": 17, "w1mpro": 12.3, "w1sigmpro": 0.04, "w1snr": 25.0,
        "w2mpro": 11.8, "w2sigmpro": 0.05, "w2snr": 20.0,
        "w1rchi2": 1.1, "w2rchi2": 1.2, "nb": 2, "na": 1,
        "qi_fact": 1.0, "moon_masked": 0,
        "ph_qual": b"AAXX", "qual_frame": 10, "cc_flags": b"0000", "saa_sep": 12.0,
    }

    result = neowise.normalize_detection(row)

    assert result["mjd"] == 59000.25
    assert result["source_id"] == 456
    assert result["w1_psf_chi2"] == 1.1
    assert result["blend_count"] == 2
    assert result["moon_masked"] == 0
    assert result["w1_mag"] == 12.3
    assert result["w2_mag"] == 11.8
    assert result["scan_id"] == "01234"
    assert result["photometric_quality"] == "AAXX"
    assert result["contamination_flags"] == "0000"
    assert result["synthetic"] is False


def test_search_uses_bounded_tap_query_and_numeric_order(monkeypatch):
    rows = [
        {"ra": 1.0, "dec": 2.0, "mjd": 59001.0, "scan_id": "2", "frame_num": "10"},
        {"ra": 1.0, "dec": 2.0, "mjd": 59001.0, "scan_id": "2", "frame_num": "2"},
        {"ra": 1.0, "dec": 2.0, "mjd": 59002.0, "scan_id": "2", "frame_num": "1"},
    ]
    calls = {}

    def fake_query_tap(query, maxrec=None):
        calls["query"] = query
        calls["maxrec"] = maxrec
        return rows

    monkeypatch.setattr(
        neowise, "new_irsa_client",
        lambda: type("FakeClient", (), {"query_tap": staticmethod(fake_query_tap)})(),
    )
    result = neowise.search_neowise(1.0, 2.0, 15, limit=2)

    assert "SELECT TOP 3" in calls["query"]
    assert "ORDER BY mjd ASC, scan_id ASC, frame_num ASC" in calls["query"]
    assert calls["maxrec"] == 3
    assert [item["frame_num"] for item in result["detections"]] == ["2", "10"]
    assert result["truncated"] is True


def test_search_rejects_invalid_limit():
    with pytest.raises(ValueError, match="between 1 and 500"):
        neowise.search_neowise(1.0, 2.0, 15, limit=0)


def test_search_rejects_invalid_coordinates():
    with pytest.raises(ValueError, match="ra_deg"):
        neowise.search_neowise(360.0, 2.0, 15)
