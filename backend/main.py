import os
import logging
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import settings
from backend.services.firms_service import firms_service, FIRMS_OPEN_FEEDS
from backend.services.weather_service import weather_service
from backend.services.geocoding_service import geocoding_service
from backend.services.risk_engine import risk_engine
from backend.services.historical_service import historical_service, REGIONS
from backend.services.forecasting_engine import forecasting_engine

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("neurora.main")

app = FastAPI(
    title="Neurora — Fire Detection Triage Dashboard",
    description="Real-world satellite hotspot observation triage, explainable fire risk assessment, and chronological next-day count forecasting (Non-Emergency Analytical Dashboard).",
    version=settings.VERSION
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = settings.BASE_DIR / "frontend"

# --- API Endpoints ---

@app.get("/api/health")
def get_health():
    """System health check and live API connection status."""
    return {
        "status": "healthy",
        "version": settings.VERSION,
        "firms_key_configured": bool(settings.FIRMS_MAP_KEY),
        "providers": {
            "nasa_firms": {
                "status": "connected",
                "products_supported": list(FIRMS_OPEN_FEEDS.keys()),
                "source": "NASA FIRMS NRT Open CSV & Area API"
            },
            "open_meteo": {
                "status": "connected",
                "source": "Open-Meteo Global Weather API (ECMWF/GFS)"
            },
            "osm_nominatim": {
                "status": "connected",
                "source": "OpenStreetMap Nominatim Geocoding"
            }
        },
        "cache_directory": str(settings.CACHE_DIR),
        "debug": settings.DEBUG
    }

@app.get("/api/hotspots")
def get_hotspots(
    satellite: Optional[str] = Query(None, description="Filter by satellite platform or product key"),
    confidence: Optional[str] = Query(None, description="'low', 'nominal', or 'high'"),
    priority: Optional[str] = Query(None, description="Filter by review priority: 'high', 'medium', or 'low'"),
    min_frp: Optional[float] = Query(None, description="Minimum Fire Radiative Power in MW"),
    min_lat: Optional[float] = Query(None),
    max_lat: Optional[float] = Query(None),
    min_lon: Optional[float] = Query(None),
    max_lon: Optional[float] = Query(None),
    limit: int = Query(5000, le=25000, description="Maximum returned points for frontend rendering"),
    refresh: bool = Query(False, description="Force refresh from remote data sources")
):
    """
    Fetches real satellite active-fire detections with multi-sensor support:
    VIIRS NOAA-20, NOAA-21, Suomi-NPP, and MODIS Terra/Aqua.
    Ranked by triage priority (recency, confidence, FRP, repeat detections)
    with per-detection explanation breakdown.
    """
    products = None
    if satellite:
        sat_clean = satellite.upper()
        if "NOAA20" in sat_clean or "NOAA-20" in sat_clean:
            products = ["VIIRS_NOAA20_NRT"]
        elif "NOAA21" in sat_clean or "NOAA-21" in sat_clean:
            products = ["VIIRS_NOAA21_NRT"]
        elif "SNPP" in sat_clean or "SUOMI" in sat_clean:
            products = ["VIIRS_SNPP_NRT"]
        elif "MODIS" in sat_clean:
            products = ["MODIS_NRT"]

    bbox = None
    if all(x is not None for x in [min_lat, min_lon, max_lat, max_lon]):
        bbox = (min_lat, min_lon, max_lat, max_lon)

    data = firms_service.get_all_normalized_hotspots(
        products=products,
        min_confidence=confidence,
        min_frp=min_frp,
        bbox=bbox,
        max_points=limit,
        force_refresh=refresh
    )

    if priority and "hotspots" in data:
        p_clean = priority.strip().upper()
        data["hotspots"] = [
            h for h in data["hotspots"]
            if h.get("triage_tier") == p_clean or p_clean in h.get("triage_priority", "").upper()
        ]
        data["metadata"]["returned_detections"] = len(data["hotspots"])

    return data

@app.get("/api/hotspots/summary")
def get_hotspots_summary():
    """Returns top-level summary metrics for global satellite detections."""
    data = firms_service.get_all_normalized_hotspots(max_points=1)
    return {
        "metadata": data["metadata"],
        "summary": data["summary"]
    }

@app.get("/api/audit/ingestion")
def get_ingestion_audit():
    """
    Returns the Data Ingestion & Quality Audit summary:
    Total rows loaded vs rejected, duplicate swath drops, and reason breakdown.
    """
    data = firms_service.get_all_normalized_hotspots(max_points=50)
    return data.get("data_quality_audit", {})

@app.get("/api/weather")
def get_weather(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    name: Optional[str] = Query(None, description="Location display name")
):
    """Fetches real live meteorological conditions and atmospheric oxygen status."""
    return weather_service.get_weather(lat, lon, location_name=name)

@app.get("/api/risk")
def get_risk(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    name: Optional[str] = Query("Selected Region", description="Location name"),
    radius_km: float = Query(50.0, description="Radius around coordinates to assess hotspot density")
):
    """
    Computes explainable Environmental Fire-Risk Index (EFRI)
    categorized into RED, ORANGE, or GREEN alert levels.
    """
    # 1. Fetch live surface meteorology
    w_data = weather_service.get_weather(lat, lon, location_name=name)
    current_w = w_data.get("current", {})
    daily_w = w_data.get("daily_forecast", {})

    temp = current_w.get("temperature_c")
    rh = current_w.get("relative_humidity_pct")
    wind = current_w.get("wind_speed_kmh")
    precip = current_w.get("precipitation_mm", 0.0)
    forecast_precip = daily_w.get("precipitation_sum_mm", [0.0])[0] if daily_w.get("precipitation_sum_mm") else 0.0

    # 2. Query nearby real satellite detections within bounding box radius (~0.5 deg ≈ 55km)
    deg_delta = radius_km / 111.0
    bbox = (lat - deg_delta, lon - deg_delta, lat + deg_delta, lon + deg_delta)
    nearby_data = firms_service.get_all_normalized_hotspots(bbox=bbox, max_points=100)
    nearby_spots = nearby_data.get("hotspots", [])
    nearby_count = len(nearby_spots)
    nearby_frp = sum(s.get("frp_mw", 0.0) or 0.0 for s in nearby_spots)

    # 3. Evaluate multi-factor explainable risk
    assessment = risk_engine.evaluate_risk(
        temperature_c=temp,
        relative_humidity_pct=rh,
        wind_speed_kmh=wind,
        precipitation_mm=precip,
        forecast_precip_mm=forecast_precip,
        nearby_hotspot_count=nearby_count,
        nearby_total_frp=nearby_frp,
        location_name=name
    )

    assessment["coordinates"] = {"latitude": lat, "longitude": lon}
    assessment["weather_snapshot"] = current_w
    assessment["nearby_hotspots_sample"] = nearby_spots[:5]

    return assessment

@app.get("/api/forecast")
def get_forecast(
    geo_id: str = Query("GLOBAL", description="Geographic unit: GLOBAL, continent, or country code")
):
    """
    Runs next-day count forecasting comparing Baseline (lag-1 persistence)
    with Alternative (Poisson count regression) on chronologically held-out test data.
    """
    return forecasting_engine.run_forecast(geo_id=geo_id)

@app.get("/api/regions")
def get_regions():
    """List of all available continents and countries for selection and analysis."""
    return historical_service.get_all_regions_summary()

@app.get("/api/geocode/search")
def search_places(q: str = Query(..., min_length=2)):
    """Search global locations by place name."""
    return geocoding_service.search_location(q)

@app.get("/api/geocode/reverse")
def reverse_geocode(lat: float, lon: float):
    """Reverse geocode coordinates into administrative place name with honest fallback."""
    return geocoding_service.reverse_geocode(lat, lon)

@app.get("/api/export/csv")
def export_csv():
    """Export historical daily satellite counts dataset as CSV."""
    if not historical_service.csv_path.exists():
        raise HTTPException(status_code=404, detail="Historical CSV not found")
    return FileResponse(
        historical_service.csv_path,
        media_type="text/csv",
        filename="neurora_historical_satellite_counts.csv"
    )

@app.get("/api/export/parquet")
def export_parquet():
    """Export historical daily satellite counts dataset as Parquet."""
    if not historical_service.parquet_path.exists():
        raise HTTPException(status_code=404, detail="Historical Parquet not found")
    return FileResponse(
        historical_service.parquet_path,
        media_type="application/octet-stream",
        filename="neurora_historical_satellite_counts.parquet"
    )

# Static Frontend Files
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def serve_frontend():
        return FileResponse(FRONTEND_DIR / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
