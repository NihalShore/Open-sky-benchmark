from contextlib import contextmanager

import pytest

from app.services import neowise


def test_normalize_detection_keeps_time_photometry_and_quality():
    row = {
        "cntr": 987654321,
        "ra": 127.6,
        "dec": -39.1,
        "mjd": 59000.25,
        "scan_id": b"01234\x00",
        "frame_num": 17,
        "w1mpro": 12.3,
        "w1sigmpro": 0.04,
        "w1snr": 25.0,
        "w2mpro": 11.8,
        "w2sigmpro": 0.05,
        "w2snr": 20.0,
        "ph_qual": b"AAXX",
        "qual_frame": 10,
        "cc_flags": b"0000",
        "saa_sep": 12.0,
        "source_id": b"44212a057-000100",
        "sigra": 0.12,
        "sigdec": 0.13,
        "sigradec": -0.01,
        "rchi2": 1.1,
        "det_bit": 3,
        "sso_flg": 0,
        "w1frtr": b"0000",
        "w2frtr": b"0000",
        "allwise_cntr": 12345,
        "r_allwise": 0.7,
        "n_allwise": 1,
        "tmass_key": 54321,
        "r_2mass": 1.1,
        "n_2mass": 1,
    }

    result = neowise.normalize_detection(row)

    assert result["source_cntr"] == 987654321
    assert result["mjd"] == 59000.25
    assert result["w1_mag"] == 12.3
    assert result["w2_mag"] == 11.8
    assert result["scan_id"] == "01234"
    assert result["photometric_quality"] == "AAXX"
    assert result["contamination_flags"] == "0000"
    assert result["source_id"] == "44212a057-000100"
    assert result["ra_uncertainty_arcsec"] == 0.12
    assert result["dec_uncertainty_arcsec"] == 0.13
    assert result["profile_fit_rchi2"] == 1.1
    assert result["detection_bits"] == 3
    assert result["allwise_source_id"] == 12345
    assert result["allwise_separation_arcsec"] == 0.7
    assert result["allwise_match_count"] == 1
    assert result["tmass_source_id"] == 54321
    assert result["tmass_separation_arcsec"] == 1.1
    assert result["tmass_match_count"] == 1
    assert result["solar_system_association_flag"] == 0
    assert result["w1_transient_flags"] == "0000"
    assert result["w2_transient_flags"] == "0000"
    assert result["synthetic"] is False


def test_search_uses_bounded_ordered_tap_query_and_reports_truncation(monkeypatch):
    rows = [
        {"ra": 1.0, "dec": 2.0, "mjd": 59002.0, "scan_id": "001", "frame_num": 10},
        {"ra": 1.0, "dec": 2.0, "mjd": 59001.0, "scan_id": "001", "frame_num": 9},
        {"ra": 1.0, "dec": 2.0, "mjd": None, "scan_id": "001", "frame_num": 1},
    ]
    calls = {}

    class FakeClient:
        def query_tap(self, query, *, async_job=False, maxrec=None):
            calls["adql"] = query
            calls["maxrec"] = maxrec
            return rows

    @contextmanager
    def fake_irsa_client():
        yield FakeClient()

    monkeypatch.setattr(neowise, "irsa_client", fake_irsa_client)
    results, truncated = neowise.search_neowise_with_status(1.0, 2.0, 15, limit=1)

    assert "TOP 2" in calls["adql"]
    assert "FROM neowiser_p1bs_psd" in calls["adql"]
    assert "ORDER BY mjd ASC, scan_id ASC, frame_num ASC" in calls["adql"]
    for column in (
        "source_id", "sigra", "sigdec", "sigradec", "det_bit", "sso_flg",
        "w1frtr", "w2frtr", "allwise_cntr", "r_allwise", "n_allwise",
        "tmass_key", "r_2mass", "n_2mass",
    ):
        assert column in calls["adql"]
    assert calls["maxrec"] == 2
    assert truncated is True
    assert [item["mjd"] for item in results] == [59001.0]


def test_search_sorts_frame_num_numerically(monkeypatch):
    rows = [
        {"ra": 1.0, "dec": 2.0, "mjd": 59001.0, "scan_id": "001", "frame_num": 10},
        {"ra": 1.0, "dec": 2.0, "mjd": 59001.0, "scan_id": "001", "frame_num": 9},
    ]

    class FakeClient:
        def query_tap(self, query, *, async_job=False, maxrec=None):
            return rows

    @contextmanager
    def fake_irsa_client():
        yield FakeClient()

    monkeypatch.setattr(neowise, "irsa_client", fake_irsa_client)
    results, truncated = neowise.search_neowise_with_status(1.0, 2.0, 15, limit=10)

    assert truncated is False
    assert [item["frame_num"] for item in results] == [9, 10]


def test_search_rejects_invalid_limit():
    with pytest.raises(ValueError, match="positive integer"):
        neowise.search_neowise(1.0, 2.0, 15, limit=0)
