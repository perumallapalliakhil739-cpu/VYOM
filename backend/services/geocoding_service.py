import sqlite3
import time
import logging
import unicodedata
from typing import Optional, Dict, Any, List, Tuple
import requests
from backend.config import settings

logger = logging.getLogger("neurora.geocoding")

def clean_to_english(text: Any) -> str:
    """Normalizes accents and strips non-Latin/non-ASCII characters to guarantee English-only text."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii").strip()
    return norm if any(c.isalpha() for c in norm) else ""

def build_english_name(data: Dict[str, Any], lat: float, lon: float) -> Tuple[str, str, str, str]:
    """
    Constructs a pure English geographic hierarchy:
    [City/Locality, State/Province, Country].
    Ensures zero non-Latin script leakage across any coordinate globally.
    """
    address = data.get("address", {})
    namedetails = data.get("namedetails", {})
    
    city_cand = (
        namedetails.get("name:en") or 
        namedetails.get("int_name") or 
        address.get("city") or 
        address.get("town") or 
        address.get("village") or 
        address.get("municipality") or 
        address.get("county") or
        address.get("suburb") or
        namedetails.get("name")
    )
    city_en = clean_to_english(city_cand)
    state_en = clean_to_english(address.get("state") or address.get("province") or address.get("region"))
    country_en = clean_to_english(address.get("country"))
    
    parts = []
    for item in [city_en, state_en, country_en]:
        if item and item not in parts:
            parts.append(item)
            
    if parts:
        return ", ".join(parts), country_en or "Unknown", city_en, state_en
    return f"Coordinates {lat:.4f}°, {lon:.4f}°", "Remote / Oceanic / Unresolved", "", ""

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

    def clear_cache(self):
        """Purges cached reverse and search entries to ensure newly resolved names are strictly English."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM reverse_cache")
                conn.execute("DELETE FROM search_cache")
        except Exception as e:
            logger.warning(f"Failed to clear geocoding cache: {e}")

    def reverse_geocode(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Reverse geocodes latitude & longitude into guaranteed pure English geographical names.
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
                    clean_disp = clean_to_english(row[0]) or f"Coordinates {lat:.4f}°, {lon:.4f}°"
                    clean_country = clean_to_english(row[1]) or "Unknown"
                    clean_city = clean_to_english(row[2])
                    clean_state = clean_to_english(row[3])
                    return {
                        "resolved": True,
                        "display_name": clean_disp,
                        "country": clean_country,
                        "city": clean_city,
                        "state": clean_state,
                        "latitude": lat,
                        "longitude": lon,
                        "source": "cache (Nominatim OSM English)"
                    }
        except Exception as e:
            logger.warning(f"Cache check error: {e}")

        # Throttle request to respect Nominatim policy (max 1 req/sec)
        elapsed = time.time() - self.last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

        url = "https://nominatim.openstreetmap.org/reverse"
        headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9"
        }
        params = {
            "lat": lat,
            "lon": lon,
            "format": "jsonv2",
            "zoom": 10,
            "addressdetails": 1,
            "namedetails": 1,
            "accept-language": "en"
        }

        try:
            self.last_request_time = time.time()
            resp = requests.get(url, headers=headers, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                display_name, country, city, state = build_english_name(data, lat, lon)

                if display_name and not display_name.startswith("Coordinates"):
                    # Save clean English version to cache
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
                        "country": country,
                        "city": city,
                        "state": state,
                        "latitude": lat,
                        "longitude": lon,
                        "source": "live (Nominatim OSM English)"
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
        """Search world location by text query in English."""
        query_clean = clean_to_english(query) or query.strip()
        if not query_clean:
            return []

        # Throttle
        elapsed = time.time() - self.last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

        url = "https://nominatim.openstreetmap.org/search"
        headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9"
        }
        params = {
            "q": query_clean,
            "format": "jsonv2",
            "addressdetails": 1,
            "namedetails": 1,
            "limit": 5,
            "accept-language": "en"
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
                    display_name, country, city, state = build_english_name(r, lat, lon)
                    if not display_name or display_name.startswith("Coordinates"):
                        raw_disp = clean_to_english(r.get("display_name", ""))
                        display_name = raw_disp or f"Coordinates {lat:.4f}°, {lon:.4f}°"
                    formatted.append({
                        "display_name": display_name,
                        "country": country,
                        "city": city,
                        "state": state,
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
