import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.services.firms_service import firms_service
from backend.services.weather_service import weather_service
from backend.services.geocoding_service import geocoding_service
from backend.services.risk_engine import risk_engine
from backend.services.forecasting_engine import forecasting_engine
from backend.services.historical_service import historical_service

client = TestClient(app)

def test_api_health():
    """Verify system health endpoint and connected services."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "providers" in data
    assert data["providers"]["nasa_firms"]["status"] == "connected"
    assert data["providers"]["open_meteo"]["status"] == "connected"
    assert data["providers"]["osm_nominatim"]["status"] == "connected"

def test_firms_hotspots_normalization():
    """Verify real NASA FIRMS hotspots normalization across all sensors."""
    res = firms_service.get_all_normalized_hotspots(max_points=20)
    assert "metadata" in res
    assert "summary" in res
    assert "hotspots" in res
    assert res["summary"]["total_count"] > 0

    # Check normalized hotspot fields
    if len(res["hotspots"]) > 0:
        spot = res["hotspots"][0]
        assert "id" in spot
        assert "latitude" in spot
        assert "longitude" in spot
        assert "satellite" in spot
        assert "instrument" in spot
        assert "acq_date" in spot
        assert "confidence_norm" in spot
        assert spot["confidence_norm"] in ["low", "nominal", "high"]

def test_hotspots_api_endpoint():
    """Verify /api/hotspots query parameters and response structure."""
    response = client.get("/api/hotspots?limit=15")
    assert response.status_code == 200
    data = response.json()
    assert "hotspots" in data
    assert len(data["hotspots"]) <= 15

def test_satellite_filtering():
    """Verify NOAA-20, NOAA-21, Suomi-NPP, and MODIS filtering."""
    for sat in ["NOAA20", "NOAA21", "SNPP", "MODIS"]:
        response = client.get(f"/api/hotspots?satellite={sat}&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert "hotspots" in data

def test_weather_and_atmospheric_oxygen():
    """Verify live weather and honest atmospheric oxygen reporting."""
    w_data = weather_service.get_weather(52.52, 13.41, "Berlin, Germany")
    assert "current" in w_data
    assert "hourly_series" in w_data
    assert "atmospheric_oxygen" in w_data
    
    # Must explicitly state unavailable and explain scientifically
    oxygen = w_data["atmospheric_oxygen"]
    assert oxygen["status"] == "unavailable"
    assert "Oxygen measurement unavailable" in oxygen["statement"]
    assert "scientific_explanation" in oxygen

def test_geocoding_honest_fallback():
    """Verify that remote / oceanic coordinates return coordinates rather than fake names."""
    geo = geocoding_service.reverse_geocode(-45.0, -120.0)
    assert geo is not None
    assert "latitude" in geo
    assert "longitude" in geo
    # If not resolved, displays coordinates
    assert "Coordinates" in geo["display_name"] or geo["resolved"] is True

def test_risk_engine_alerts():
    """Verify explainable multi-factor fire risk calculation across RED, ORANGE, GREEN with review priority labels."""
    # 1. High danger scenario (Hot, Dry, Windy, Heavy Hotspots) -> RED / High review priority
    red_eval = risk_engine.evaluate_risk(
        temperature_c=41.0,
        relative_humidity_pct=12.0,
        wind_speed_kmh=42.0,
        precipitation_mm=0.0,
        forecast_precip_mm=0.0,
        nearby_hotspot_count=25,
        nearby_total_frp=350.0,
        location_name="Test High Danger"
    )
    assert red_eval["alert_level"] == "RED"
    assert red_eval["alert_title"] == "High review priority"
    assert red_eval["review_priority"] == "High review priority"
    assert red_eval["score"] >= 65
    assert red_eval["color_hex"] == "#EF4444"
    assert len(red_eval["contributing_factors"]) > 0
    assert "NON-EMERGENCY" in red_eval["limitations_disclaimer"]

    # 2. Low danger scenario (Cool, Humid, Rain, Zero Hotspots) -> GREEN / Low review priority
    green_eval = risk_engine.evaluate_risk(
        temperature_c=12.0,
        relative_humidity_pct=85.0,
        wind_speed_kmh=8.0,
        precipitation_mm=18.0,
        forecast_precip_mm=10.0,
        nearby_hotspot_count=0,
        nearby_total_frp=0.0,
        location_name="Test Low Danger"
    )
    assert green_eval["alert_level"] == "GREEN"
    assert green_eval["alert_title"] == "Low review priority"
    assert green_eval["review_priority"] == "Low review priority"
    assert green_eval["score"] < 35
    assert green_eval["color_hex"] == "#10B981"

def test_observation_triage_ranking_and_explanations():
    """Verify explainable observation triage rankings, repeat counts, and per-row breakdown explanations."""
    res = firms_service.get_all_normalized_hotspots(max_points=30)
    hotspots = res.get("hotspots", [])
    assert len(hotspots) > 0

    top_spot = hotspots[0]
    # Check triage fields
    assert "triage_rank" in top_spot
    assert top_spot["triage_rank"] == 1
    assert "triage_score" in top_spot
    assert 0 <= top_spot["triage_score"] <= 100
    assert "triage_priority" in top_spot
    assert top_spot["triage_priority"] in ["High review priority", "Medium review priority", "Low review priority"]
    assert "repeat_count" in top_spot
    assert "triage_explanation" in top_spot
    assert "Ranked " in top_spot["triage_explanation"]
    assert "because:" in top_spot["triage_explanation"]
    assert "triage_factors" in top_spot
    assert "time" in top_spot["triage_factors"]
    assert "frp" in top_spot["triage_factors"]
    assert "repeats" in top_spot["triage_factors"]
    assert "confidence" in top_spot["triage_factors"]

    # Verify API filtering by priority
    response = client.get("/api/hotspots?priority=high&limit=10")
    assert response.status_code == 200
    data = response.json()
    for h in data["hotspots"]:
        assert h["triage_tier"] == "HIGH"

def test_risk_api_endpoint():
    """Verify /api/risk endpoint."""
    response = client.get("/api/risk?lat=-14.23&lon=-51.92&name=Brazil")
    assert response.status_code == 200
    data = response.json()
    assert "score" in data
    assert "alert_level" in data
    assert data["alert_level"] in ["RED", "ORANGE", "GREEN"]
    assert "review_priority" in data
    assert "factors" in data

def test_forecasting_engine_chronological_evaluation():
    """Verify next-day forecasting, held-out split, and model comparison metrics."""
    res = forecasting_engine.run_forecast("GLOBAL")
    assert "next_day_forecast" in res
    assert "model_comparison" in res
    assert "evaluation_protocol" in res
    
    # Must report held-out MAE and RMSE
    comp = res["model_comparison"]
    assert "baseline_model" in comp
    assert "alternative_model" in comp
    assert comp["baseline_model"]["held_out_mae"] > 0
    assert comp["alternative_model"]["held_out_mae"] > 0
    assert "test_period" in res["evaluation_protocol"]
    assert "scientific_limitations" in res

def test_forecast_api_endpoint():
    """Verify /api/forecast endpoint."""
    response = client.get("/api/forecast?geo_id=GLOBAL")
    assert response.status_code == 200
    data = response.json()
    assert "next_day_forecast" in data

def test_historical_dataset_and_exports():
    """Verify historical dataset generation and CSV/Parquet export endpoints."""
    csv_resp = client.get("/api/export/csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers.get("content-type", "")

    parquet_resp = client.get("/api/export/parquet")
    assert parquet_resp.status_code == 200
    assert len(parquet_resp.content) > 100
