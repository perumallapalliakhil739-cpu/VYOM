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
import math
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
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

    # ------------------------------------------------------------------
    # Ingestion helpers (single source of truth for validation rules)
    # ------------------------------------------------------------------
    REPEAT_RADIUS_KM = 2.0      # neighbours within ~2 km count as repeat detections
    EARTH_RADIUS_KM = 6371.0088

    @staticmethod
    def normalize_confidence(conf_raw: Any) -> str:
        """VIIRS: 'l'/'n'/'h' (or full words). MODIS: 0-100. Exact matches only,
        so the word 'nominal' is no longer mistaken for 'low'."""
        if conf_raw is None:
            return "nominal"
        if isinstance(conf_raw, str):
            s = conf_raw.strip().lower()
            if s in ("h", "high"):
                return "high"
            if s in ("l", "low"):
                return "low"
            if s in ("n", "nominal"):
                return "nominal"
            try:
                num = float(s)
            except ValueError:
                return "nominal"
        else:
            try:
                num = float(conf_raw)
            except (TypeError, ValueError):
                return "nominal"
        if math.isnan(num):
            return "nominal"
        if num >= 80:
            return "high"
        if num <= 30:
            return "low"
        return "nominal"

    @staticmethod
    def parse_observation_time(acq_date: Any, acq_time: Any) -> Optional[datetime]:
        """Strictly parse FIRMS acq_date (YYYY-MM-DD) + acq_time (HHMM, UTC).
        Returns None for anything unparseable (garbage text, NaN, hour>23, minute>59)."""
        d = str(acq_date).strip()
        t = str(acq_time).strip()
        if t.endswith(".0"):
            t = t[:-2]
        if not t.isdigit() or len(t) > 4:
            return None
        t = t.zfill(4)
        try:
            return datetime.strptime(f"{d} {t[:2]}:{t[2:]}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def validate_observation_row(
        self,
        row: Dict[str, Any],
        min_confidence: Optional[str] = None,
        min_frp: Optional[float] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Validates one detection row. Rejects: missing/non-finite/out-of-range coordinates,
        missing/NaN/non-finite/negative FRP, and any timestamp that does not parse.
        (The bulk pipeline uses the vectorised twin `_validate_frame`; a parity test keeps them aligned.)
        """
        try:
            lat = float(row.get("latitude"))
            lon = float(row.get("longitude"))
        except (TypeError, ValueError):
            return False, "invalid_or_missing_coordinates", None
        if not (math.isfinite(lat) and math.isfinite(lon)):
            return False, "invalid_or_missing_coordinates", None
        if not (-90.0 <= lat <= 90.0):
            return False, "latitude_out_of_range", None
        if not (-180.0 <= lon <= 180.0):
            return False, "longitude_out_of_range", None

        try:
            frp_val = float(row.get("frp"))
        except (TypeError, ValueError):
            return False, "negative_or_corrupt_frp" if row.get("frp") is not None else "missing_or_nan_frp", None
        if not math.isfinite(frp_val):
            return False, "missing_or_nan_frp", None
        if frp_val < 0.0:
            return False, "negative_or_corrupt_frp", None

        dt = self.parse_observation_time(row.get("acq_date", ""), row.get("acq_time", ""))
        if dt is None:
            return False, "corrupt_or_missing_timestamp", None
        acq_date = str(row.get("acq_date")).strip()
        acq_time_raw = dt.strftime("%H%M")

        if bbox:
            min_lat, min_lon, max_lat, max_lon = bbox
            if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
                return False, "outside_bounding_box", None
        if min_frp is not None and frp_val < min_frp:
            return False, "below_minimum_frp", None

        conf_raw = row.get("confidence", "nominal")
        conf_norm = self.normalize_confidence(conf_raw)
        if min_confidence == "high" and conf_norm != "high":
            return False, "below_confidence_threshold", None
        if min_confidence == "nominal" and conf_norm == "low":
            return False, "below_confidence_threshold", None

        return True, None, {
            "latitude": lat, "longitude": lon, "frp": frp_val,
            "acq_date": acq_date, "acq_time_raw": acq_time_raw,
            "confidence_raw": conf_raw, "confidence_norm": conf_norm,
        }

    def _validate_frame(self, df: pd.DataFrame, min_confidence=None, min_frp=None, bbox=None):
        """Vectorised validation of an ENTIRE raw feed (no pre-sampling).
        Returns (clean_df, Counter_of_rejection_reasons)."""
        n = len(df)

        def col(name, default=np.nan):
            return df[name] if name in df.columns else pd.Series(default, index=df.index)

        lat = pd.to_numeric(col("latitude"), errors="coerce")
        lon = pd.to_numeric(col("longitude"), errors="coerce")
        frp_raw = col("frp")
        frp = pd.to_numeric(frp_raw, errors="coerce")

        t = col("acq_time", "").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        t_ok = t.str.fullmatch(r"\d{1,4}")
        t4 = t.where(t_ok, "").str.zfill(4)
        dt = pd.to_datetime(
            col("acq_date", "").astype(str).str.strip() + " " + t4.str[:2] + ":" + t4.str[2:],
            format="%Y-%m-%d %H:%M", errors="coerce", utc=True,
        ).where(t_ok)

        conf_raw = col("confidence", "nominal")
        conf_norm = conf_raw.astype(object).map(self.normalize_confidence)

        reason = pd.Series([None] * n, index=df.index, dtype=object)

        def mark(mask, name):
            reason.loc[mask.fillna(False) & reason.isna()] = name

        mark(~np.isfinite(lat) | ~np.isfinite(lon), "invalid_or_missing_coordinates")
        mark((lat < -90) | (lat > 90), "latitude_out_of_range")
        mark((lon < -180) | (lon > 180), "longitude_out_of_range")
        mark(frp_raw.notna() & frp.isna(), "negative_or_corrupt_frp")      # present but non-numeric
        mark(~np.isfinite(frp), "missing_or_nan_frp")
        mark(frp < 0, "negative_or_corrupt_frp")
        mark(dt.isna(), "corrupt_or_missing_timestamp")
        if bbox:
            min_lat, min_lon, max_lat, max_lon = bbox
            mark(~((lat >= min_lat) & (lat <= max_lat) & (lon >= min_lon) & (lon <= max_lon)), "outside_bounding_box")
        if min_frp is not None:
            mark(frp < min_frp, "below_minimum_frp")
        if min_confidence == "high":
            mark(conf_norm != "high", "below_confidence_threshold")
        elif min_confidence == "nominal":
            mark(conf_norm == "low", "below_confidence_threshold")

        ok = reason.isna()
        bright = pd.to_numeric(col("bright_ti4"), errors="coerce").fillna(pd.to_numeric(col("brightness"), errors="coerce"))
        clean = pd.DataFrame({
            "latitude": lat[ok], "longitude": lon[ok], "frp": frp[ok], "dt": dt[ok],
            "acq_date": dt[ok].dt.strftime("%Y-%m-%d"), "acq_time_raw": dt[ok].dt.strftime("%H%M"),
            "confidence_raw": conf_raw[ok].astype(str), "confidence_norm": conf_norm[ok],
            "sat_raw": col("satellite", "").astype(str)[ok], "brightness": bright[ok],
            "daynight": col("daynight", "D").astype(str).str.upper()[ok],
            "version": col("version", "NRT").astype(str)[ok],
        })
        return clean, Counter(reason.dropna().tolist())

    @classmethod
    def _repeat_counts(cls, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """Detections (including itself) within REPEAT_RADIUS_KM, by true great-circle distance
        (no grid-cell edge effects). The open FIRMS feeds span 24 h, so every neighbour is
        inside the 48 h repeat window."""
        if len(lat) == 0:
            return np.zeros(0, dtype=int)
        la, lo = np.radians(lat), np.radians(lon)
        xyz = np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])
        chord = 2.0 * math.sin((cls.REPEAT_RADIUS_KM / cls.EARTH_RADIUS_KM) / 2.0)
        return np.asarray(cKDTree(xyz).query_ball_point(xyz, r=chord, return_length=True, workers=-1), dtype=int)

    @staticmethod
    def _score_frame(frp, repeats, age_h, conf_norm) -> np.ndarray:
        """Vectorised twin of calculate_observation_priority (same weights; used only to pre-select top-N)."""
        s_frp = np.minimum(100.0, (np.maximum(frp, 0.0) / 50.0) ** 0.65 * 100.0)
        s_rep = np.minimum(100.0, np.maximum(repeats, 1) * 20.0)
        s_time = np.maximum(15.0, 100.0 - (np.maximum(age_h, 0.0) / 24.0) * 85.0)
        s_conf = np.where(conf_norm == "high", 95.0, np.where(conf_norm == "low", 35.0, 65.0))
        return np.clip(0.35 * s_frp + 0.25 * s_rep + 0.25 * s_time + 0.15 * s_conf, 0.0, 100.0)

    def get_all_normalized_hotspots(
        self,
        products: Optional[List[str]] = None,
        min_confidence: Optional[str] = None,
        min_frp: Optional[float] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,  # (min_lat, min_lon, max_lat, max_lon)
        max_points: int = 5000,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Retrieves satellite detections, validates EVERY raw row (no pre-sampling), de-duplicates,
        counts repeat detections, scores, and returns the top `max_points`.
        Audit invariant: raw rows == valid unique rows + rejected rows.
        """
        if not products:
            products = list(FIRMS_OPEN_FEEDS.keys())

        now_dt = datetime.now(timezone.utc)
        rejection_breakdown: Counter = Counter()
        source_stats: Dict[str, Any] = {}
        sat_breakdown: Dict[str, int] = {}
        frames = []
        total_raw_rows = 0

        for pkey in products:
            feed_info = FIRMS_OPEN_FEEDS.get(pkey)
            if not feed_info:
                continue
            df = self.fetch_product_raw(pkey, force_refresh=force_refresh)
            if df is None or df.empty:
                source_stats[pkey] = {"status": "no_data", "count": 0, "raw_count": 0}
                continue

            inst, prod_name = feed_info["instrument"], feed_info["product_name"]
            platform_default = feed_info["platform_default"]
            cnt = len(df)
            total_raw_rows += cnt
            sat_breakdown[platform_default] = sat_breakdown.get(platform_default, 0) + cnt

            clean, rejects = self._validate_frame(df, min_confidence, min_frp, bbox)
            rejection_breakdown.update(rejects)
            if len(clean):
                names = {s: self.get_source_platform_name(inst, s, platform_default) for s in clean["sat_raw"].unique()}
                clean["platform"] = clean["sat_raw"].map(names)
                clean["instrument"] = inst
                clean["product"] = prod_name
                frames.append(clean)
            source_stats[pkey] = {
                "status": "connected", "instrument": inst, "platform": platform_default,
                "raw_count": cnt, "valid_count": len(clean), "product_name": prod_name,
            }

        if frames:
            allv = pd.concat(frames, ignore_index=True)
            before = len(allv)
            allv = (allv.assign(_la=allv["latitude"].round(4), _lo=allv["longitude"].round(4))
                        .drop_duplicates(subset=["_la", "_lo", "acq_date", "acq_time_raw", "platform"])
                        .drop(columns=["_la", "_lo"]).reset_index(drop=True))
            duplicate_count = before - len(allv)
            if duplicate_count:
                rejection_breakdown["duplicate_spatial_temporal_record"] = duplicate_count
        else:
            allv = pd.DataFrame(columns=["latitude", "longitude", "frp", "dt", "confidence_norm"])
            duplicate_count = 0

        n_valid = len(allv)
        if n_valid:
            allv["age_h"] = ((now_dt - allv["dt"]).dt.total_seconds() / 3600.0).round(1).clip(lower=0.0)
            allv["repeats"] = self._repeat_counts(allv["latitude"].to_numpy(float), allv["longitude"].to_numpy(float))
            allv["pre"] = self._score_frame(allv["frp"].to_numpy(float), allv["repeats"].to_numpy(),
                                            allv["age_h"].to_numpy(float), allv["confidence_norm"].to_numpy(object))
            top = allv.sort_values(["pre", "frp"], ascending=False).head(max_points)
        else:
            top = allv

        records = []
        for r in top.itertuples(index=False):
            score, tier, explanation = self.calculate_observation_priority(
                frp=r.frp, repeats=int(r.repeats), age_hours=float(r.age_h),
                confidence_norm=r.confidence_norm, confidence_raw=r.confidence_raw)
            review_tier = "HIGH" if score >= 70 else "MEDIUM" if score >= 45 else "LOW"
            priority_label = {"HIGH": "High review priority", "MEDIUM": "Medium review priority", "LOW": "Low review priority"}[review_tier]
            triage_explanation = f"Ranked {review_tier.lower()} because: {explanation.split('because: ', 1)[1]}"
            repeats_clean = int(r.repeats)
            age_clean = float(r.age_h)
            frp_clean = float(r.frp)
            confidence_clean = str(r.confidence_norm)
            id_str = f"{r.latitude:.4f}_{r.longitude:.4f}_{r.acq_date}_{r.acq_time_raw}_{r.platform}"
            records.append({
                "id": hashlib.md5(id_str.encode()).hexdigest()[:12],
                "latitude": round(float(r.latitude), 5), "longitude": round(float(r.longitude), 5),
                "satellite": r.platform, "instrument": r.instrument, "product": r.product,
                "acq_date": r.acq_date, "acq_time": f"{r.acq_time_raw[:2]}:{r.acq_time_raw[2:]}",
                "datetime_utc": f"{r.acq_date}T{r.acq_time_raw[:2]}:{r.acq_time_raw[2:]}:00Z",
                "observation_age_hours": float(r.age_h),
                "confidence_raw": r.confidence_raw, "confidence_norm": r.confidence_norm,
                "brightness_k": None if pd.isna(r.brightness) else float(r.brightness),
                "frp_mw": round(float(r.frp), 2),
                "daynight": "Day" if r.daynight == "D" else "Night",
                "version": r.version,
                "ranking_score": score, "priority_tier": tier,
                "repeat_detections": repeats_clean, "ranking_explanation": explanation,
                "triage_score": score, "triage_tier": review_tier, "triage_priority": priority_label,
                "triage_badge": review_tier.title(), "triage_class": {"HIGH": "danger", "MEDIUM": "warning", "LOW": "success"}[review_tier],
                "triage_color": {"HIGH": "#EF4444", "MEDIUM": "#F97316", "LOW": "#10B981"}[review_tier],
                "repeat_count": max(0, repeats_clean - 1), "triage_explanation": triage_explanation,
                "triage_rank": 0,
                "triage_factors": {
                    "time": {"subscore": max(15.0, 100.0 - (age_clean / 24.0) * 85.0), "age_hours": age_clean},
                    "frp": {"subscore": min(100.0, (max(0.0, frp_clean) / 50.0) ** 0.65 * 100.0), "frp_mw": frp_clean},
                    "repeats": {"subscore": min(100.0, repeats_clean * 20.0), "count": max(0, repeats_clean - 1)},
                    "confidence": {"subscore": 95.0 if confidence_clean == "high" else 35.0 if confidence_clean == "low" else 65.0, "norm": confidence_clean},
                },
            })
        records.sort(key=lambda x: (x["ranking_score"], x["frp_mw"]), reverse=True)
        for i, rec in enumerate(records, 1):
            rec["rank"] = i
            rec["triage_rank"] = i

        total_rejected = total_raw_rows - n_valid     # == sum(rejection_breakdown.values())
        valid_frp = allv["frp"] if n_valid else pd.Series(dtype=float)
        detail = ", ".join(f"{v:,} {k.replace('_', ' ')}" for k, v in rejection_breakdown.most_common()) or "none"
        ingestion_audit = {
            "total_raw_rows_fetched": total_raw_rows,
            "valid_rows_loaded": n_valid,
            "rows_returned_to_client": len(records),
            "total_rows_rejected": total_rejected,
            "rejection_breakdown": dict(rejection_breakdown),
            "duplicate_swaths_deduplicated": duplicate_count,
            "retention_rate_pct": round(100.0 * n_valid / total_raw_rows, 2) if total_raw_rows else 100.0,
            "data_integrity_status": "PASSED_ANOMALIES_CLEANED" if total_rejected > 0 else "PASSED_CLEAN",
            "summary_statement": f"{n_valid:,} valid rows loaded from {total_raw_rows:,} raw observations ({total_rejected:,} rejected: {detail})",
        }
        return {
            "metadata": {
                "total_unique_detections": n_valid, "returned_detections": len(records),
                "is_sampled": n_valid > len(records),
                "data_freshness_utc": now_dt.isoformat(), "sources_evaluated": source_stats,
                "ingestion_audit": ingestion_audit,
                "attribution": "NASA FIRMS (EOSDIS LANCE / LDOPE / SSEC). Real satellite observations.",
            },
            "summary": {
                "total_count": n_valid,
                "new_24h_count": int((allv["age_h"] <= 24.0).sum()) if n_valid else 0,
                "high_confidence_count": int((allv["confidence_norm"] == "high").sum()) if n_valid else 0,
                "satellite_breakdown": sat_breakdown,
                "avg_frp_mw": round(float(valid_frp.mean()), 2) if n_valid else 0.0,
                "max_frp_mw": round(float(valid_frp.max()), 2) if n_valid else 0.0,
                "triage_summary": {
                    "high_review_priority_count": sum(r["triage_tier"] == "HIGH" for r in records),
                    "medium_review_priority_count": sum(r["triage_tier"] == "MEDIUM" for r in records),
                    "low_review_priority_count": sum(r["triage_tier"] == "LOW" for r in records),
                    "repeat_cluster_count": sum(r["repeat_count"] > 0 for r in records),
                },
            },
            "data_quality_audit": ingestion_audit,
            "hotspots": records,
        }

firms_service = FIRMSService()