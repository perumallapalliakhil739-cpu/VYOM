import sqlite3
import time
import logging
from typing import Optional, Dict, Any, List
import requests
from backend.config import settings

logger = logging.getLogger("neurora.geocoding")

class GeocodingService:
    def __init__(self):
        self.db_path = settings.DATA_DIR / "geocoding.db"
        self._init_db()
        self.last_request_time = 0.0

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS reverse_cache (
                        lat_round REAL,
                        lon_round REAL,
                        display_name TEXT,
                        country TEXT,
                        city TEXT,
                        state TEXT,
                        timestamp REAL,
                        PRIMARY KEY (lat_round, lon_round)
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS search_cache (
                        query TEXT PRIMARY KEY,
                        results_json TEXT,
                        timestamp REAL
                    )
                """)
        except Exception as e:
            logger.error(f"Failed to init geocoding sqlite db: {e}")

    def reverse_geocode(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Reverse geocodes latitude & longitude into real geographical names.
        Rounds to 2 decimal places (~1.1 km) for efficient local caching.
        Falls back to exact coordinate string without fabricating names.
        """
        lat_r = round(lat, 2)
        lon_r = round(lon, 2)

        # Check SQLite cache
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT display_name, country, city, state FROM reverse_cache WHERE lat_round = ? AND lon_round = ?",
                    (lat_r, lon_r)
                )
                row = cur.fetchone()
                if row:
                    return {
                        "resolved": True,
                        "display_name": row[0],
                        "country": row[1] or "Unknown",
                        "city": row[2] or "",
                        "state": row[3] or "",
                        "latitude": lat,
                        "longitude": lon,
                        "source": "cache (Nominatim OSM)"
                    }
        except Exception as e:
            logger.warning(f"Cache check error: {e}")

        # Throttle request to respect Nominatim policy (max 1 req/sec)
        elapsed = time.time() - self.last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

        url = "https://nominatim.openstreetmap.org/reverse"
        headers = {"User-Agent": settings.USER_AGENT}
        params = {
            "lat": lat,
            "lon": lon,
            "format": "jsonv2",
            "zoom": 10,
            "addressdetails": 1
        }

        try:
            self.last_request_time = time.time()
            resp = requests.get(url, headers=headers, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                display_name = data.get("display_name", "")
                address = data.get("address", {})
                country = address.get("country", "")
                city = address.get("city") or address.get("town") or address.get("village") or address.get("county") or ""
                state = address.get("state") or address.get("region") or ""

                if display_name:
                    # Save to cache
                    try:
                        with sqlite3.connect(self.db_path) as conn:
                            conn.execute(
                                "INSERT OR REPLACE INTO reverse_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (lat_r, lon_r, display_name, country, city, state, time.time())
                            )
                    except Exception:
                        pass

                    return {
                        "resolved": True,
                        "display_name": display_name,
                        "country": country or "Unknown",
                        "city": city,
                        "state": state,
                        "latitude": lat,
                        "longitude": lon,
                        "source": "live (Nominatim OSM)"
                    }
        except Exception as e:
            logger.warning(f"Reverse geocode lookup failed: {e}")

        # Honest fallback: coordinate representation without fabricated name
        coord_name = f"Coordinates {lat:.4f}°, {lon:.4f}°"
        return {
            "resolved": False,
            "display_name": coord_name,
            "country": "Remote / Oceanic / Unresolved",
            "city": "",
            "state": "",
            "latitude": lat,
            "longitude": lon,
            "source": "unresolved_coordinates"
        }

    def search_location(self, query: str) -> List[Dict[str, Any]]:
        """Search world location by text query (country, state, city, landmark)."""
        query_clean = query.strip()
        if not query_clean:
            return []

        # Throttle
        elapsed = time.time() - self.last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": settings.USER_AGENT}
        params = {
            "q": query_clean,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 5
        }

        try:
            self.last_request_time = time.time()
            resp = requests.get(url, headers=headers, params=params, timeout=5)
            if resp.status_code == 200:
                results = resp.json()
                formatted = []
                for r in results:
                    lat = float(r.get("lat", 0.0))
                    lon = float(r.get("lon", 0.0))
                    bbox = [float(x) for x in r.get("boundingbox", [lat-1, lat+1, lon-1, lon+1])]
                    formatted.append({
                        "display_name": r.get("display_name", ""),
                        "latitude": lat,
                        "longitude": lon,
                        "type": r.get("type", "location"),
                        "boundingbox": bbox,
                        "importance": r.get("importance", 0.0)
                    })
                return formatted
        except Exception as e:
            logger.error(f"Geocoding search failed: {e}")
            return []

geocoding_service = GeocodingService()
