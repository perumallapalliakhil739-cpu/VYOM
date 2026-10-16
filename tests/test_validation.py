import pytest
import numpy as np
from backend.services.firms_service import firms_service

def test_valid_row_acceptance():
    """Verify clean, physical satellite observation is accepted."""
    valid_row = {
        "latitude": 37.7749,
        "longitude": -122.4194,
        "frp": 25.4,
        "acq_date": "2026-10-16",
        "acq_time": "1420",
        "confidence": "high",
        "satellite": "N"
    }
    is_valid, reason, cleaned = firms_service.validate_observation_row(valid_row)
    assert is_valid is True
    assert reason is None
    assert cleaned is not None
    assert cleaned["latitude"] == 37.7749
    assert cleaned["frp"] == 25.4
    assert cleaned["confidence_norm"] == "high"

def test_reject_out_of_range_latitude():
    """Verify observations with invalid or out-of-range latitude are rejected."""
    # Latitude > 90.0
    bad_row_north = {
        "latitude": 92.5,
        "longitude": 10.0,
        "frp": 12.0,
        "acq_date": "2026-10-16",
        "acq_time": "1200"
    }
    is_valid, reason, _ = firms_service.validate_observation_row(bad_row_north)
    assert is_valid is False
    assert reason == "latitude_out_of_range"

    # Latitude < -90.0
    bad_row_south = {
        "latitude": -95.0,
        "longitude": 10.0,
        "frp": 12.0,
        "acq_date": "2026-10-16",
        "acq_time": "1200"
    }
    is_valid, reason, _ = firms_service.validate_observation_row(bad_row_south)
    assert is_valid is False
    assert reason == "latitude_out_of_range"

def test_reject_out_of_range_longitude():
    """Verify observations with longitude outside [-180, 180] are rejected."""
    bad_row = {
        "latitude": 20.0,
        "longitude": 195.0,
        "frp": 15.0,
        "acq_date": "2026-10-16",
        "acq_time": "1200"
    }
    is_valid, reason, _ = firms_service.validate_observation_row(bad_row)
    assert is_valid is False
    assert reason == "longitude_out_of_range"

def test_reject_missing_or_nan_coordinates():
    """Verify missing, corrupt, or NaN coordinates are rejected."""
    row_nan = {
        "latitude": float("nan"),
        "longitude": 45.0,
        "frp": 10.0,
        "acq_date": "2026-10-16",
        "acq_time": "1200"
    }
    is_valid, reason, _ = firms_service.validate_observation_row(row_nan)
    assert is_valid is False
    assert "coordinates" in reason

    row_corrupt = {
        "latitude": "invalid_lat",
        "longitude": 45.0,
        "frp": 10.0,
        "acq_date": "2026-10-16",
        "acq_time": "1200"
    }
    is_valid, reason, _ = firms_service.validate_observation_row(row_corrupt)
    assert is_valid is False
    assert "coordinates" in reason

def test_reject_negative_or_corrupt_frp():
    """Verify negative Fire Radiative Power is rejected (unphysical in radiometry)."""
    bad_frp_row = {
        "latitude": 15.0,
        "longitude": 25.0,
        "frp": -8.5,
        "acq_date": "2026-10-16",
        "acq_time": "1200"
    }
    is_valid, reason, _ = firms_service.validate_observation_row(bad_frp_row)
    assert is_valid is False
    assert reason == "negative_or_corrupt_frp"

def test_reject_corrupt_or_missing_timestamp():
    """Verify missing date or truncated time string is rejected."""
    bad_time_row = {
        "latitude": 15.0,
        "longitude": 25.0,
        "frp": 20.0,
        "acq_date": "",
        "acq_time": ""
    }
    is_valid, reason, _ = firms_service.validate_observation_row(bad_time_row)
    assert is_valid is False
    assert reason == "corrupt_or_missing_timestamp"

def test_spatial_bbox_filtering():
    """Verify observation outside requested spatial bounding box is rejected."""
    row = {
        "latitude": 40.0,
        "longitude": -5.0,
        "frp": 10.0,
        "acq_date": "2026-10-16",
        "acq_time": "1200"
    }
    # bbox in South America: (-20, -60, -10, -50)
    is_valid, reason, _ = firms_service.validate_observation_row(row, bbox=(-20.0, -60.0, -10.0, -50.0))
    assert is_valid is False
    assert reason == "outside_bounding_box"

def test_ingestion_audit_reporting():
    """Verify the ingestion audit summary structure and loaded vs rejected totals."""
    res = firms_service.get_all_normalized_hotspots(max_points=25)
    assert "data_quality_audit" in res
    audit = res["data_quality_audit"]
    
    assert "total_raw_rows_fetched" in audit
    assert "valid_rows_loaded" in audit
    assert "total_rows_rejected" in audit
    assert "rejection_breakdown" in audit
    assert "summary_statement" in audit
    
    assert audit["total_raw_rows_fetched"] >= audit["valid_rows_loaded"]
    assert audit["valid_rows_loaded"] > 0
    assert audit["retention_rate_pct"] > 0.0
