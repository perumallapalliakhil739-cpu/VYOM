"""Offline regression tests for the ingestion/ranking fixes. No network required."""
import math
import numpy as np
import pytest
from backend.services.firms_service import firms_service as fs
from conftest import make_row


def _base(**kw):
    r = dict(latitude=15.0, longitude=25.0, frp=20.0, acq_date="2026-10-16", acq_time="1200", confidence="n")
    r.update(kw)
    return r


# ---- Bug 2: garbage timestamps must be rejected (not silently scored as "just now") ----
@pytest.mark.parametrize("d,t", [("not-a-date", "1200"), ("2026-13-45", "1200"), ("2026-10-16", "2575"),
                                  ("2026-10-16", "abcd"), ("2026-10-16", float("nan")), (float("nan"), "1200")])
def test_garbage_timestamp_rejected(d, t):
    ok, reason, _ = fs.validate_observation_row(_base(acq_date=d, acq_time=t))
    assert ok is False and reason == "corrupt_or_missing_timestamp"


def test_short_time_is_zero_padded_not_rejected():
    ok, _, clean = fs.validate_observation_row(_base(acq_time=5))     # 00:05 stored as int 5
    assert ok and clean["acq_time_raw"] == "0005"


# ---- Bug 3: missing / NaN / inf FRP must be rejected, not turned into 0.0 ----
@pytest.mark.parametrize("frp", [float("nan"), float("inf"), None])
def test_missing_or_nan_frp_rejected(frp):
    ok, reason, _ = fs.validate_observation_row(_base(frp=frp))
    assert ok is False and reason == "missing_or_nan_frp"


def test_frp_key_absent_rejected():
    row = _base(); del row["frp"]
    assert fs.validate_observation_row(row)[1] == "missing_or_nan_frp"


# ---- Smaller fix: confidence parsing ----
@pytest.mark.parametrize("raw,expected", [("h", "high"), ("n", "nominal"), ("l", "low"), ("nominal", "nominal"),
                                          ("high", "high"), ("low", "low"), (85, "high"), (50, "nominal"),
                                          (10, "low"), ("85", "high"), (np.int64(90), "high"), (None, "nominal")])
def test_confidence_normalisation(raw, expected):
    assert fs.normalize_confidence(raw) == expected


# ---- Bug 1: audit must cover EVERY raw row, even when only a few are returned ----
def _messy_feed(now=None):
    rows = [make_row(12.30 + i * 0.001, 77.20, 1 + i, "h", 60 + i, now=now) for i in range(8)]   # cluster
    rows += [make_row(20 + i * 0.3, 30 + i * 0.3, 3, "n", 0.5 + i * 0.01, now=now) for i in range(30)]
    bad_date = make_row(12.7, 77.7, 2, "h", 30, now=now); bad_date["acq_date"] = "not-a-date"
    rows += [make_row(95, 77, 2, "h", 50, now=now), make_row(12, 200, 2, "h", 50, now=now),
             make_row(None, 77, 2, "h", 50, now=now), make_row(12.5, 77.5, 2, "h", -5, now=now),
             make_row(12.6, 77.6, 2, "h", float("nan"), now=now), bad_date, dict(rows[0])]       # last = duplicate
    return rows


def test_audit_counts_every_row_even_when_sampling(offline_feed):
    rows = _messy_feed(); offline_feed(rows)
    res = fs.get_all_normalized_hotspots(max_points=5)
    a = res["data_quality_audit"]
    assert a["total_raw_rows_fetched"] == len(rows)
    assert a["total_rows_rejected"] == 7            # 6 bad rows + 1 duplicate
    assert a["valid_rows_loaded"] == len(rows) - 7
    assert a["total_raw_rows_fetched"] == a["valid_rows_loaded"] + a["total_rows_rejected"]
    assert sum(a["rejection_breakdown"].values()) == a["total_rows_rejected"]
    assert a["rows_returned_to_client"] == len(res["hotspots"]) == 5
    reasons = a["rejection_breakdown"]
    for key in ("latitude_out_of_range", "longitude_out_of_range", "invalid_or_missing_coordinates",
                "negative_or_corrupt_frp", "missing_or_nan_frp", "corrupt_or_missing_timestamp",
                "duplicate_spatial_temporal_record"):
        assert reasons.get(key) == 1, key


def test_audit_same_regardless_of_max_points(offline_feed):
    offline_feed(_messy_feed())
    a1 = fs.get_all_normalized_hotspots(max_points=3)["data_quality_audit"]
    a2 = fs.get_all_normalized_hotspots(max_points=500)["data_quality_audit"]
    assert a1["rejection_breakdown"] == a2["rejection_breakdown"]
    assert a1["valid_rows_loaded"] == a2["valid_rows_loaded"]


def test_bad_rows_never_appear_or_get_scored(offline_feed):
    offline_feed(_messy_feed())
    hs = fs.get_all_normalized_hotspots(max_points=500)["hotspots"]
    assert all(h["frp_mw"] > 0 for h in hs)
    assert not any(abs(h["latitude"] - 12.7) < 1e-3 for h in hs)          # garbage-date row is gone
    assert not any(h["latitude"] == 0 and h["longitude"] == 0 for h in hs)  # no Null-Island points


# ---- Bug 4: summary counters must be computed ----
def test_summary_counters_are_computed(offline_feed):
    offline_feed(_messy_feed())
    s = fs.get_all_normalized_hotspots(max_points=10)["summary"]
    assert s["total_count"] == 38 + 0 and s["new_24h_count"] == 38
    assert s["high_confidence_count"] == 8            # the 8 cluster points
    assert s["max_frp_mw"] == 67.0


# ---- Bug 5: repeat detections by real distance, not grid cells ----
def test_repeats_across_old_grid_boundary(offline_feed):
    rows = [make_row(30.0049, 40.0, 2, "n", 30), make_row(30.0051, 40.0, 2, "n", 30),   # ~22 m apart, straddling .005
            make_row(30.5, 40.5, 2, "n", 30)]                                           # far away
    offline_feed(rows)
    hs = {round(h["latitude"], 4): h for h in fs.get_all_normalized_hotspots(max_points=10)["hotspots"]}
    assert hs[30.0049]["repeat_detections"] == 2 and hs[30.0051]["repeat_detections"] == 2
    assert hs[30.5]["repeat_detections"] == 1


def test_repeat_radius_is_about_two_km():
    lat = np.array([10.0, 10.0 + 1.5 / 111.0, 10.0 + 3.0 / 111.0])       # 0, 1.5 km, 3 km north
    lon = np.zeros(3)
    c = fs._repeat_counts(lat, lon)
    assert c[0] == 2 and c[1] == 3 and c[2] == 2    # middle point sees both neighbours (1.5 km each)


# ---- Ranking sanity end-to-end and vector/scalar parity ----
def test_strong_recent_cluster_ranks_first(offline_feed):
    offline_feed(_messy_feed())
    hs = fs.get_all_normalized_hotspots(max_points=10)["hotspots"]
    assert [h["rank"] for h in hs] == list(range(1, len(hs) + 1))
    assert all(abs(h["latitude"] - 12.30) < 0.02 for h in hs[:5])
    assert all(hs[i]["ranking_score"] >= hs[i + 1]["ranking_score"] for i in range(len(hs) - 1))


def test_vector_and_scalar_scores_agree():
    rng = np.random.default_rng(1)
    frp = rng.uniform(0, 200, 200); rep = rng.integers(1, 12, 200); age = rng.uniform(0, 48, 200)
    conf = rng.choice(["low", "nominal", "high"], 200).astype(object)
    vec = fs._score_frame(frp, rep, age, conf)
    for i in range(200):
        scalar = fs.calculate_observation_priority(frp[i], int(rep[i]), age[i], conf[i])[0]
        assert abs(vec[i] - scalar) <= 0.051
