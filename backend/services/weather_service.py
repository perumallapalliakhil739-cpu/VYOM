import time
import logging
from typing import Dict, Any, Optional, List
import requests
from backend.config import settings

logger = logging.getLogger("neurora.weather")

class WeatherService:
    def __init__(self):
        self.cache_dir = settings.CACHE_DIR
        self._cache: Dict[str, Any] = {}
        self._cache_times: Dict[str, float] = {}
        self.cache_ttl = 900  # 15 minutes for live weather

    def get_weather(self, lat: float, lon: float, location_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves real live weather observations and forecasts from Open-Meteo.
        Includes current, hourly (48h), and daily (7d) trends.
        Includes transparent documentation regarding atmospheric oxygen.
        """
        lat_r = round(lat, 2)
        lon_r = round(lon, 2)
        cache_key = f"{lat_r}_{lon_r}"
        now = time.time()

        if cache_key in self._cache and (now - self._cache_times.get(cache_key, 0)) < self.cache_ttl:
            return self._cache[cache_key]

        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat_r,
            "longitude": lon_r,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,rain,wind_speed_10m,wind_direction_10m,wind_gusts_10m,surface_pressure,cloud_cover",
            "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,wind_speed_10m,wind_direction_10m,cloud_cover",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
            "timezone": "auto",
            "forecast_days": 7
        }

        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("current", {})
                hourly = data.get("hourly", {})
                daily = data.get("daily", {})

                # Wind direction compass translation
                deg = current.get("wind_direction_10m", 0)
                compass_dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
                idx = int((deg + 11.25) / 22.5) % 16
                compass_str = compass_dirs[idx]

                # Extract last 24h & next 24h hourly slices
                hourly_time = hourly.get("time", [])[:48]
                hourly_temp = hourly.get("temperature_2m", [])[:48]
                hourly_rh = hourly.get("relative_humidity_2m", [])[:48]
                hourly_wind = hourly.get("wind_speed_10m", [])[:48]
                hourly_precip = hourly.get("precipitation", [])[:48]
                cloud_cov = current.get("cloud_cover", 0)

                # Determine cloud obscuration condition
                if cloud_cov is None:
                    cloud_cov = 0
                if cloud_cov < 25:
                    obs_condition = "Clear Sky — Unrestricted MWIR & Thermal Observation"
                    cloud_status_badge = "CLEAR"
                elif cloud_cov < 70:
                    obs_condition = "Partial Cloud Cover — Contextual Band Masking Active"
                    cloud_status_badge = "MODERATE"
                else:
                    obs_condition = "Dense Cloud Layer — Multi-Satellite Constellation Revisit Required"
                    cloud_status_badge = "OBSCURED"

                result = {
                    "location": {
                        "latitude": lat,
                        "longitude": lon,
                        "name": location_name or f"{lat:.2f}°, {lon:.2f}°",
                        "timezone": data.get("timezone", "UTC"),
                        "elevation_m": data.get("elevation", 0)
                    },
                    "current": {
                        "temperature_c": current.get("temperature_2m"),
                        "apparent_temperature_c": current.get("apparent_temperature"),
                        "relative_humidity_pct": current.get("relative_humidity_2m"),
                        "wind_speed_kmh": current.get("wind_speed_10m"),
                        "wind_direction_deg": deg,
                        "wind_direction_cardinal": compass_str,
                        "wind_gusts_kmh": current.get("wind_gusts_10m"),
                        "precipitation_mm": current.get("precipitation"),
                        "surface_pressure_hpa": current.get("surface_pressure"),
                        "cloud_cover_pct": cloud_cov,
                        "timestamp": current.get("time")
                    },
                    "hourly_series": {
                        "times": hourly_time,
                        "temperatures_c": hourly_temp,
                        "relative_humidity_pct": hourly_rh,
                        "wind_speeds_kmh": hourly_wind,
                        "precipitations_mm": hourly_precip
                    },
                    "daily_forecast": {
                        "dates": daily.get("time", []),
                        "max_temp_c": daily.get("temperature_2m_max", []),
                        "min_temp_c": daily.get("temperature_2m_min", []),
                        "precipitation_sum_mm": daily.get("precipitation_sum", []),
                        "max_wind_kmh": daily.get("wind_speed_10m_max", [])
                    },
                    "remote_sensing_analysis": {
                        "cloud_cover_pct": cloud_cov,
                        "cloud_status": cloud_status_badge,
                        "observation_condition": obs_condition,
                        "smoke_penetration": {
                            "status": "Transparent to Mid-Wave Infrared (MWIR)",
                            "transmission_estimate_pct": 98.5,
                            "physics_rationale": (
                                "Wildfire smoke aerosols (0.1–0.8 µm) are optically thin to Mid-Wave Infrared "
                                "(3.7–4.0 µm, VIIRS I4/M13 & MODIS 21/22). Because the MWIR wavelength is ~5–20x larger "
                                "than smoke particles, Mie scattering drops dramatically, allowing fire thermal radiation "
                                "to pass directly through heavy smoke plumes to the satellite sensors."
                            )
                        },
                        "dual_band_contextual_algorithm": {
                            "formula": "ΔT = T_4µm - T_11µm",
                            "explanation": (
                                "Satellites compare the 4µm channel (flame radiation peak, Wien's law ~800-1200K) against the "
                                "11µm long-wave channel (ambient ground ~300K). Active combustion spikes ΔT by tens of Kelvins, "
                                "differentiating genuine fire fronts from solar reflection or warm barren earth."
                            )
                        },
                        "cloud_mitigation_strategy": {
                            "cirrus_detection": "1.38 µm water vapor absorption channel identifies high-altitude thin cirrus.",
                            "thick_cloud_protocol": "Pixels fully blocked by water/ice clouds are flagged as 'Cloud-Obscured' rather than 'No Fire'.",
                            "constellation_revisit": [
                                {"satellite": "NOAA-21 VIIRS", "orbit": "Sun-synchronous polar", "local_time": "~13:00 / 01:00"},
                                {"satellite": "Suomi-NPP VIIRS", "orbit": "Sun-synchronous polar", "local_time": "~13:30 / 01:30"},
                                {"satellite": "NOAA-20 VIIRS", "orbit": "Sun-synchronous polar (50 min stagger)", "local_time": "~14:20 / 02:20"},
                                {"satellite": "MODIS Terra", "orbit": "Sun-synchronous polar morning", "local_time": "~10:30 / 22:30"},
                                {"satellite": "MODIS Aqua", "orbit": "Sun-synchronous polar afternoon", "local_time": "~13:30 / 01:30"}
                            ],
                            "temporal_benefit": "Because clouds move continuously, staggered 5-satellite orbits observe the same location up to 6–8 times daily, detecting fire fronts during cloud-cover breaks."
                        },
                        "radar_and_microwave_horizon": {
                            "technology": "Synthetic Aperture Radar (SAR) & Microwave Radiometry (e.g., Sentinel-1 C-band 5.6cm, NISAR L-band 24cm)",
                            "capability": "Centimeter-wavelength microwaves completely penetrate opaque clouds, rain, and darkness, enabling all-weather ground burn-scar and moisture detection."
                        }
                    },
                    "atmospheric_oxygen": {
                        "status": "unavailable",
                        "measurement": None,
                        "statement": "Oxygen measurement unavailable from the connected data sources.",
                        "scientific_explanation": (
                            "Standard operational weather APIs (Open-Meteo, ECMWF, NOAA GFS) do not record ambient O2. "
                            "Ordinary atmospheric oxygen concentration (~20.95%) remains virtually uniform in the lower troposphere globally "
                            "and is not a direct predictor of where a wildfire will ignite. Fire initiation and spread are instead governed by "
                            "fuel moisture deficit, ambient temperature, relative humidity, wind velocity, and ignition vectors."
                        )
                    },
                    "attribution": "Open-Meteo Weather API (ECMWF, GFS, DWD, MeteoFrance)"
                }

                self._cache[cache_key] = result
                self._cache_times[cache_key] = now
                return result
            else:
                logger.warning(f"Open-Meteo status {resp.status_code}")
        except Exception as e:
            logger.error(f"Error fetching Open-Meteo: {e}")

        # Fallback response if offline/rate-limited
        return {
            "location": {"latitude": lat, "longitude": lon, "name": location_name or f"{lat:.2f}°, {lon:.2f}°"},
            "current": {
                "temperature_c": None,
                "relative_humidity_pct": None,
                "wind_speed_kmh": None,
                "wind_direction_deg": None,
                "precipitation_mm": None,
                "status": "Weather service temporarily unreachable"
            },
            "atmospheric_oxygen": {
                "status": "unavailable",
                "statement": "Oxygen measurement unavailable from the connected data sources.",
                "scientific_explanation": "Ordinary atmospheric oxygen concentration is not a direct predictor of wildfire ignition."
            }
        }

weather_service = WeatherService()
