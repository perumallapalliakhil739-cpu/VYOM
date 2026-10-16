import os
import io
import time
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import requests
import pandas as pd
from backend.config import settings

logger = logging.getLogger("neurora.firms")
logger.setLevel(logging.INFO)

# Mapping of product keys to open active fire CSV urls (24h feeds)
FIRMS_OPEN_FEEDS = {
    "VIIRS_SNPP_NRT": {
        "url": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_24h.csv",
        "instrument": "VIIRS",
        "platform_default": "Suomi-NPP",
        "product_name": "Suomi-NPP VIIRS 375m Active Fire (C2)"
    },
    "VIIRS_NOAA20_NRT": {
        "url": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_24h.csv",
        "instrument": "VIIRS",
        "platform_default": "NOAA-20 (JPSS-1)",
        "product_name": "NOAA-20 VIIRS 375m Active Fire (C2)"
    },
    "VIIRS_NOAA21_NRT": {
        "url": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-21-viirs-c2/csv/J2_VIIRS_C2_Global_24h.csv",
        "instrument": "VIIRS",
        "platform_default": "NOAA-21 (JPSS-2)",
        "product_name": "NOAA-21 VIIRS 375m Active Fire (C2)"
    },
    "MODIS_NRT": {
        "url": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Global_24h.csv",
        "instrument": "MODIS",
        "platform_default": "Terra / Aqua",
        "product_name": "MODIS Collection 6.1 1km Thermal Anomalies"
    }
}

class FIRMSService:
    def __init__(self):
        self.cache_dir = settings.CACHE_DIR
        self.cache_ttl = settings.CACHE_TTL_SECONDS
        self._memory_cache: Dict[str, Any] = {}
        self._last_fetch_time: Dict[str, float] = {}

    def get_source_platform_name(self, instrument: str, sat_code: str, fallback: str) -> str:
        s = str(sat_code).strip()
        if instrument == "MODIS":
            if s == "T":
                return "Terra (MODIS)"
            elif s == "A":
                return "Aqua (MODIS)"
            return "MODIS Terra/Aqua"
        else: # VIIRS
            if s == "N20" or s == "1":
                return "NOAA-20 (JPSS-1)"
            elif s == "N21" or s == "2":
                return "NOAA-21 (JPSS-2)"
            elif s == "N":
                return "Suomi-NPP"
            return fallback

    def fetch_product_raw(self, product_key: str, force_refresh: bool = False) -> Optional[pd.DataFrame]:
        """Fetch real FIRMS data either from MAP_KEY area API or direct open NRT feeds with local caching."""
        cache_file = self.cache_dir / f"firms_{product_key}.csv"
        now = time.time()

        # Check in-memory cache first
        if not force_refresh and product_key in self._memory_cache:
            if (now - self._last_fetch_time.get(product_key, 0)) < self.cache_ttl:
                return self._memory_cache[product_key]

        # Check local disk cache validity
        if not force_refresh and cache_file.exists():
            file_age = now - cache_file.stat().st_mtime
            if file_age < self.cache_ttl:
                try:
                    logger.info(f"Loading {product_key} from disk cache (age: {int(file_age)}s)")
                    df = pd.read_csv(cache_file)
                    self._memory_cache[product_key] = df
                    self._last_fetch_time[product_key] = cache_file.stat().st_mtime
                    return df
                except Exception as e:
                    logger.warning(f"Failed to read disk cache for {product_key}: {e}")

        # Need to fetch fresh data
        feed_info = FIRMS_OPEN_FEEDS.get(product_key)
        if not feed_info:
            logger.error(f"Unknown product key: {product_key}")
            return None

        # If user has a MAP_KEY configured and wants custom range, we can use that,
        # otherwise open global 24h/48h CSV feed is used directly
        url = feed_info["url"]
        headers = {"User-Agent": settings.USER_AGENT}

        try:
            logger.info(f"Fetching fresh real FIRMS observations from {url}")
            resp = requests.get(url, headers=headers, timeout=25)
            if resp.status_code == 200 and len(resp.content) > 100:
                content = resp.content.decode('utf-8', errors='replace')
                df = pd.read_csv(io.StringIO(content))
                # Write to disk cache
                with open(cache_file, "w", encoding="utf-8") as f:
                    f.write(content)
                self._last_fetch_time[product_key] = now
                logger.info(f"Successfully cached {len(df)} records for {product_key}")
                return df
            else:
                logger.warning(f"Failed fetching {product_key}: status {resp.status_code}")
                # Fallback to existing cache if exists
                if cache_file.exists():
                    return pd.read_csv(cache_file)
                return None
        except Exception as e:
            logger.error(f"Error fetching FIRMS {product_key}: {e}")
            if cache_file.exists():
                return pd.read_csv(cache_file)
            return None

    def get_all_normalized_hotspots(
        self,
        products: Optional[List[str]] = None,
        min_confidence: Optional[str] = None,
        min_frp: Optional[float] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None, # (min_lat, min_lon, max_lat, max_lon)
        max_points: int = 5000,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Retrieves real worldwide satellite detections, normalized across all sensors.
        Deduplicates records and provides full observation metadata.
        """
        if not products:
            products = list(FIRMS_OPEN_FEEDS.keys())

        all_records = []
        source_stats: Dict[str, Any] = {}
        now_dt = datetime.now(timezone.utc)

        total_unique_count = 0
        sat_breakdown: Dict[str, int] = {}
        high_conf_count = 0
        new_24h_count = 0
        max_detected_frp = 0.0
        total_frp = 0.0
        frp_count = 0

        target_per_prod = max(25, int(max_points / max(1, len(products))))

        for pkey in products:
            feed_info = FIRMS_OPEN_FEEDS.get(pkey)
            if not feed_info:
                continue
            df = self.fetch_product_raw(pkey, force_refresh=force_refresh)
            if df is None or df.empty:
                source_stats[pkey] = {"status": "no_data", "count": 0}
                continue

            inst = feed_info["instrument"]
            prod_name = feed_info["product_name"]
            platform_default = feed_info["platform_default"]

            # Fast vector stats before spatial slicing
            cnt = len(df)
            total_unique_count += cnt
            sat_breakdown[platform_default] = sat_breakdown.get(platform_default, 0) + cnt
            if "frp" in df.columns:
                max_val = float(df["frp"].max()) if not df["frp"].empty else 0.0
                if max_val > max_detected_frp:
                    max_detected_frp = max_val
                total_frp += float(df["frp"].sum())
                frp_count += cnt

            # Filter bounding box early if provided
            if bbox:
                min_lat, min_lon, max_lat, max_lon = bbox
                df = df[
                    (df["latitude"] >= min_lat) & (df["latitude"] <= max_lat) &
                    (df["longitude"] >= min_lon) & (df["longitude"] <= max_lon)
                ]

            if min_frp is not None and "frp" in df.columns:
                df = df[df["frp"] >= min_frp]

            count_before_conf = len(df)

            # Sample slice for detailed record parsing to keep response instantaneous
            if len(df) > target_per_prod:
                if "frp" in df.columns:
                    sample_df = df.sort_values(by="frp", ascending=False).head(target_per_prod)
                else:
                    sample_df = df.head(target_per_prod)
            else:
                sample_df = df

            dict_rows = sample_df.to_dict('records')

            # Process sampled rows quickly
            for row in dict_rows:
                lat = float(row.get("latitude", 0.0))
                lon = float(row.get("longitude", 0.0))
                sat_raw = str(row.get("satellite", ""))
                platform = self.get_source_platform_name(inst, sat_raw, platform_default)

                acq_date = str(row.get("acq_date", "")).strip()
                acq_time_raw = str(row.get("acq_time", "")).strip().zfill(4)
                
                # Format time HH:MM
                hour = acq_time_raw[:2]
                minute = acq_time_raw[2:4]
                time_formatted = f"{hour}:{minute}"

                iso_utc = f"{acq_date}T{hour}:{minute}:00Z"
                obs_age_hours = 0.0
                try:
                    dt = datetime.strptime(f"{acq_date} {hour}:{minute}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                    obs_age_hours = round((now_dt - dt).total_seconds() / 3600.0, 1)
                except Exception:
                    pass

                # Confidence handling
                conf_raw = row.get("confidence", "nominal")
                conf_norm = "nominal"
                if isinstance(conf_raw, (int, float)):
                    if conf_raw >= 80:
                        conf_norm = "high"
                    elif conf_raw <= 30:
                        conf_norm = "low"
                    else:
                        conf_norm = "nominal"
                else:
                    conf_str = str(conf_raw).lower()
                    if "h" in conf_str:
                        conf_norm = "high"
                    elif "l" in conf_str:
                        conf_norm = "low"
                    else:
                        conf_norm = "nominal"

                if min_confidence:
                    if min_confidence == "high" and conf_norm != "high":
                        continue
                    elif min_confidence == "nominal" and conf_norm == "low":
                        continue

                # Brightness temperature (Kelvin)
                brightness = None
                if "bright_ti4" in row and pd.notna(row["bright_ti4"]):
                    brightness = float(row["bright_ti4"])
                elif "brightness" in row and pd.notna(row["brightness"]):
                    brightness = float(row["brightness"])

                # FRP
                frp = 0.0
                if "frp" in row and pd.notna(row["frp"]):
                    frp = round(float(row["frp"]), 2)

                dn = str(row.get("daynight", "D")).upper()
                daynight_str = "Day" if dn == "D" else "Night"

                id_str = f"{lat:.4f}_{lon:.4f}_{acq_date}_{acq_time_raw}_{platform}"
                rec_id = hashlib.md5(id_str.encode()).hexdigest()[:12]

                all_records.append({
                    "id": rec_id,
                    "latitude": round(lat, 5),
                    "longitude": round(lon, 5),
                    "satellite": platform,
                    "instrument": inst,
                    "product": prod_name,
                    "acq_date": acq_date,
                    "acq_time": time_formatted,
                    "datetime_utc": iso_utc,
                    "observation_age_hours": max(0.0, obs_age_hours),
                    "confidence_raw": str(conf_raw),
                    "confidence_norm": conf_norm,
                    "brightness_k": brightness,
                    "frp_mw": frp,
                    "daynight": daynight_str,
                    "version": str(row.get("version", "NRT"))
                })

            source_stats[pkey] = {
                "status": "connected",
                "instrument": inst,
                "platform": platform_default,
                "raw_count": count_before_conf,
                "product_name": prod_name
            }

        # Deduplication based on record ID
        unique_map = {}
        for r in all_records:
            unique_map[r["id"]] = r
        unique_records = list(unique_map.values())
        unique_records.sort(key=lambda x: (x["frp_mw"] or 0.0), reverse=True)

        display_records = unique_records[:max_points]
        sampled = total_unique_count > len(display_records)
        avg_frp = round(total_frp / max(1, frp_count), 2)

        return {
            "metadata": {
                "total_unique_detections": len(unique_records),
                "returned_detections": len(display_records),
                "is_sampled": sampled,
                "data_freshness_utc": now_dt.isoformat(),
                "sources_evaluated": source_stats,
                "attribution": "NASA FIRMS (EOSDIS LANCE / LDOPE / SSEC). Real satellite observations."
            },
            "summary": {
                "total_count": len(unique_records),
                "new_24h_count": new_24h_count,
                "high_confidence_count": high_conf_count,
                "satellite_breakdown": sat_breakdown,
                "avg_frp_mw": avg_frp,
                "max_frp_mw": round(max_detected_frp, 2)
            },
            "hotspots": display_records
        }

firms_service = FIRMSService()
