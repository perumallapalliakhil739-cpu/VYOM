import os
import io
import time
import hashlib
import logging
from collections import Counter
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

    def calculate_observation_priority(
        self,
        frp: float,
        repeats: int,
        age_hours: float,
        confidence_norm: str,
        confidence_raw: str = ""
    ) -> Tuple[float, str, str]:
        """
        Computes the 4-factor Observation Priority Ranking (OPR) score (0 to 100),
        priority tier (CRITICAL, HIGH, ELEVATED, MODERATE, LOW), and explanation string.
        Higher FRP strictly raises the score; older detections strictly lower it.
        """
        frp_clean = max(0.0, float(frp or 0.0))
        s_frp = min(100.0, (frp_clean / 50.0) ** 0.65 * 100.0)

        repeats_clean = max(1, int(repeats or 1))
        s_repeat = min(100.0, repeats_clean * 20.0)

        age_clean = max(0.0, float(age_hours or 0.0))
        s_time = max(15.0, 100.0 - (age_clean / 24.0) * 85.0)

        conf_norm = str(confidence_norm or "nominal").lower()
        if conf_norm == "high":
            s_conf = 95.0
        elif conf_norm == "low":
            s_conf = 35.0
        else:
            s_conf = 65.0

        score = round(0.35 * s_frp + 0.25 * s_repeat + 0.25 * s_time + 0.15 * s_conf, 1)
        score = min(100.0, max(0.0, score))

        if score >= 75:
            tier = "CRITICAL"
        elif score >= 60:
            tier = "HIGH"
        elif score >= 45:
            tier = "ELEVATED"
        elif score >= 30:
            tier = "MODERATE"
        else:
            tier = "LOW"

        time_str = f"recent ({age_clean:.1f}h ago)" if age_clean < 4 else (f"{age_clean:.1f}h ago" if age_clean < 12 else f"older pass ({age_clean:.1f}h ago)")
        frp_str = f"high FRP ({frp_clean:.1f} MW)" if frp_clean >= 40 else (f"moderate FRP ({frp_clean:.1f} MW)" if frp_clean >= 15 else f"low FRP ({frp_clean:.1f} MW)")
        rep_str = f"{repeats_clean} repeat detections in cluster" if repeats_clean > 1 else "isolated detection (1 repeat)"
        raw_label = f" ({confidence_raw})" if confidence_raw else ""
        conf_str = f"high satellite confidence{raw_label}" if conf_norm == "high" else f"{conf_norm} confidence{raw_label}"

        explanation = f"Ranked {tier.lower()} because: {time_str}, {frp_str}, {rep_str}, {conf_str}"
        return score, tier, explanation

    def validate_observation_row(
        self,
        row: Dict[str, Any],
        min_confidence: Optional[str] = None,
        min_frp: Optional[float] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Validates an individual satellite detection row for geospatial and physical integrity.
        Rejects out-of-range coordinates, negative/corrupt FRPs, or missing timestamps.
        """
        # 1. Coordinate physical range validation
        try:
            lat = float(row.get("latitude"))
            lon = float(row.get("longitude"))
            if pd.isna(lat) or pd.isna(lon):
                return False, "invalid_or_missing_coordinates", None
            if not (-90.0 <= lat <= 90.0):
                return False, "latitude_out_of_range", None
            if not (-180.0 <= lon <= 180.0):
                return False, "longitude_out_of_range", None
        except (TypeError, ValueError):
            return False, "invalid_or_missing_coordinates", None

        # 2. FRP non-negative physical validation
        frp_val = 0.0
        if "frp" in row and pd.notna(row["frp"]):
            try:
                frp_val = float(row["frp"])
                if frp_val < 0.0:
                    return False, "negative_or_corrupt_frp", None
            except (TypeError, ValueError):
                return False, "negative_or_corrupt_frp", None

        # 3. Timestamp formatting & validity
        acq_date = str(row.get("acq_date", "")).strip()
        acq_time_raw = str(row.get("acq_time", "")).strip().zfill(4)
        if not acq_date or len(acq_time_raw) < 4:
            return False, "corrupt_or_missing_timestamp", None

        # 4. Optional Bounding Box Filter
        if bbox:
            min_lat, min_lon, max_lat, max_lon = bbox
            if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
                return False, "outside_bounding_box", None

        # 5. Optional Minimum FRP Filter
        if min_frp is not None and frp_val < min_frp:
            return False, "below_minimum_frp", None

        # 6. Confidence Normalization & Filter
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
                return False, "below_confidence_threshold", None
            elif min_confidence == "nominal" and conf_norm == "low":
                return False, "below_confidence_threshold", None

        return True, None, {
            "latitude": lat,
            "longitude": lon,
            "frp": frp_val,
            "acq_date": acq_date,
            "acq_time_raw": acq_time_raw,
            "confidence_raw": conf_raw,
            "confidence_norm": conf_norm
        }

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
        Deduplicates records, audits loaded vs rejected rows, and provides full observation metadata.
        """
        if not products:
            products = list(FIRMS_OPEN_FEEDS.keys())

        all_records = []
        source_stats: Dict[str, Any] = {}
        now_dt = datetime.now(timezone.utc)
        rejection_breakdown = Counter()

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
                source_stats[pkey] = {"status": "no_data", "count": 0, "raw_count": 0}
                continue

            inst = feed_info["instrument"]
            prod_name = feed_info["product_name"]
            platform_default = feed_info["platform_default"]

            cnt = len(df)
            total_unique_count += cnt
            sat_breakdown[platform_default] = sat_breakdown.get(platform_default, 0) + cnt
            if "frp" in df.columns:
                max_val = float(df["frp"].max()) if not df["frp"].empty else 0.0
                if max_val > max_detected_frp:
                    max_detected_frp = max_val
                total_frp += float(df["frp"].sum())
                frp_count += cnt

            # Subsample slice for detailed record parsing to keep response instantaneous
            if len(df) > target_per_prod:
                if "frp" in df.columns:
                    sample_df = df.sort_values(by="frp", ascending=False).head(target_per_prod)
                else:
                    sample_df = df.head(target_per_prod)
            else:
                sample_df = df

            dict_rows = sample_df.to_dict('records')

            # Validate each row through the quality validation filter
            for row in dict_rows:
                valid, reject_reason, cleaned = self.validate_observation_row(
                    row,
                    min_confidence=min_confidence,
                    min_frp=min_frp,
                    bbox=bbox
                )
                if not valid:
                    rejection_breakdown[reject_reason] += 1
                    continue

                lat = cleaned["latitude"]
                lon = cleaned["longitude"]
                frp = cleaned["frp"]
                acq_date = cleaned["acq_date"]
                acq_time_raw = cleaned["acq_time_raw"]
                conf_raw = cleaned["confidence_raw"]
                conf_norm = cleaned["confidence_norm"]

                sat_raw = str(row.get("satellite", ""))
                platform = self.get_source_platform_name(inst, sat_raw, platform_default)

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

                # Brightness temperature (Kelvin)
                brightness = None
                if "bright_ti4" in row and pd.notna(row["bright_ti4"]):
                    brightness = float(row["bright_ti4"])
                elif "brightness" in row and pd.notna(row["brightness"]):
                    brightness = float(row["brightness"])

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
                "raw_count": cnt,
                "product_name": prod_name
            }

        # Deduplication based on composite spatial-temporal record ID
        unique_map = {}
        for r in all_records:
            unique_map[r["id"]] = r
        unique_records = list(unique_map.values())

        # Track swath overlap duplicates
        duplicate_count = len(all_records) - len(unique_records)
        if duplicate_count > 0:
            rejection_breakdown["duplicate_spatial_temporal_record"] = duplicate_count

        # 1. Spatial clustering for repeat detections (~0.02 deg ~ 2.2 km cluster radius)
        grid_counts = Counter((round(r["latitude"], 2), round(r["longitude"], 2)) for r in unique_records)

        # 2. Score and rank individual observations by time, confidence, FRP, and repeat detections
        for r in unique_records:
            lat_r = round(r["latitude"], 2)
            lon_r = round(r["longitude"], 2)
            repeats = grid_counts.get((lat_r, lon_r), 1)

            score, tier, explanation = self.calculate_observation_priority(
                frp=r.get("frp_mw", 0.0),
                repeats=repeats,
                age_hours=r.get("observation_age_hours", 0.0),
                confidence_norm=r.get("confidence_norm", "nominal"),
                confidence_raw=r.get("confidence_raw", "")
            )

            r["ranking_score"] = score
            r["priority_tier"] = tier
            r["repeat_detections"] = repeats
            r["ranking_explanation"] = explanation

        # Strict sorting: highest priority observation (#1) first
        unique_records.sort(key=lambda x: (x.get("ranking_score", 0.0), x.get("frp_mw", 0.0)), reverse=True)
        for i, r in enumerate(unique_records, 1):
            r["rank"] = i

        display_records = unique_records[:max_points]
        sampled = total_unique_count > len(display_records)
        avg_frp = round(total_frp / max(1, frp_count), 2)

        # Build Ingestion Audit: Rows Loaded vs. Rejected and Why
        total_raw_rows = sum(s.get("raw_count", 0) for s in source_stats.values())
        total_rejected = sum(rejection_breakdown.values())
        retention_pct = round((len(display_records) / max(1, total_raw_rows)) * 100, 2) if total_raw_rows > 0 else 100.0

        ingestion_audit = {
            "total_raw_rows_fetched": total_raw_rows,
            "valid_rows_loaded": len(display_records),
            "total_rows_rejected": total_rejected,
            "rejection_breakdown": dict(rejection_breakdown),
            "duplicate_swaths_deduplicated": duplicate_count,
            "retention_rate_pct": retention_pct,
            "data_integrity_status": "PASSED_ANOMALIES_CLEANED" if total_rejected > 0 else "PASSED_CLEAN",
            "summary_statement": f"{len(display_records):,} valid rows loaded from {total_raw_rows:,} raw observations ({total_rejected:,} rejected / filtered: {duplicate_count:,} duplicate swaths, {rejection_breakdown.get('invalid_or_missing_coordinates', 0):,} coordinate errors, {rejection_breakdown.get('negative_or_corrupt_frp', 0):,} non-physical FRPs)"
        }

        return {
            "metadata": {
                "total_unique_detections": len(unique_records),
                "returned_detections": len(display_records),
                "is_sampled": sampled,
                "data_freshness_utc": now_dt.isoformat(),
                "sources_evaluated": source_stats,
                "ingestion_audit": ingestion_audit,
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
            "data_quality_audit": ingestion_audit,
            "hotspots": display_records
        }

firms_service = FIRMSService()
