from app.services import neowise


def test_normalize_detection_keeps_time_photometry_and_quality():
    row = {
        "ra": 127.6,
        "dec": -39.1,
        "mjd": 59000.25,
        "scan_id": "01234",
        "frame_num": 17,
        "w1mpro": 12.3,
        "w1sigmpro": 0.04,
        "w1snr": 25.0,
        "w2mpro": 11.8,
        "w2sigmpro": 0.05,
        "w2snr": 20.0,
        "ph_qual": "AAXX",
        "qual_frame": 10,
        "cc_flags": "0000",
        "saa_sep": 12.0,
    }

    result = neowise.normalize_detection(row)

    assert result["mjd"] == 59000.25
    assert result["w1_mag"] == 12.3
    assert result["w2_mag"] == 11.8
    assert result["photometric_quality"] == "AAXX"
    assert result["frame_quality"] == 10
    assert result["synthetic"] is False


def test_search_uses_neowise_catalog_and_sorts_by_mjd(monkeypatch):
    rows = [
        {"ra": 1.0, "dec": 2.0, "mjd": 59002.0},
        {"ra": 1.0, "dec": 2.0, "mjd": 59001.0},
        {"ra": 1.0, "dec": 2.0, "mjd": None},
    ]
    calls = {}

    def fake_query_region(**kwargs):
        calls.update(kwargs)
        return rows

    monkeypatch.setattr(neowise.Irsa, "query_region", fake_query_region)

    results = neowise.search_neowise(1.0, 2.0, 15, limit=1)

    assert calls["catalog"] == "neowiser_p1bs_psd"
    assert calls["spatial"] == "Cone"
    assert calls["radius"] == 15 * neowise.u.arcsec
    assert [item["mjd"] for item in results] == [59001.0]
