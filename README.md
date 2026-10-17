# Neurora — Fire Detection Triage Dashboard

**Global Environmental Hotspot Observation Triage & Forecast System**  
*Built with Real Satellite Observations, Global Geospatial Maps, Live Meteorological Data, and Chronological Count Forecasting.*

> [!IMPORTANT]
> **NON-EMERGENCY SYSTEM NOTICE:** Neurora is an analytical triage platform and scientific research dashboard for spaceborne thermal anomalies. It is **NOT** an operational emergency-response system, dispatch service, or civil defense evacuation warning platform. For active emergency situations or immediate danger to life and property, contact official local emergency services and civil protection authorities.

---

## 1. Project Overview

**Neurora** is a worldwide dashboard for reviewing satellite thermal observations, prioritizing detections for analyst review, and forecasting daily satellite detection counts.

### Key Capabilities
- **Worldwide Coverage:** Full global map covering all continents, countries, oceans, islands, and custom bounding boxes.
- **Ranked Observation Triage & Per-Detection Explainability:** Prioritizes individual satellite detections based on **time (recency), confidence, FRP (Fire Radiative Power), and repeat detections**, complete with human-readable per-row explanations (e.g. *"Ranked high because: recent, high FRP, 4 repeats"*).
- **Dark Canvas & Real World Satellite Maps:** Instant 1-click toggling between:
  - **🌌 Real Dark Canvas (Active Default):** Official GIS standard Esri World Dark Gray Canvas with crisp geopolitical borders and place labels, tailored for high-contrast thermal hotspot radiation.
  - **✨ NASA Night Earth:** NASA Black Marble (Suomi-NPP VIIRS Day/Night Band) nighttime satellite radiance.
  - **🛰️ Real World Satellite Earth:** High-resolution photographic satellite imagery from space (Esri World Imagery) with geopolitical boundaries and place labels.
- **Real Satellite Observations (NASA FIRMS):** Direct multi-sensor integration of **VIIRS NOAA-20**, **VIIRS NOAA-21**, **VIIRS Suomi-NPP**, and **MODIS Terra/Aqua Collection 6.1**.
- **Live Surface Meteorology (Open-Meteo):** Real-time temperature, relative humidity, wind speed & direction compass, precipitation deficit, and 24-hour forecast trends.
- **Atmospheric Oxygen Integrity:** Explicit reporting indicating that atmospheric oxygen concentration is not measured by standard meteorological stations and is not a direct predictor of wildfire ignition, as ambient tropospheric O₂ (~20.95%) is globally ubiquitous.
- **Explainable Environmental Fire-Risk (EFRI):** Multi-factor risk engine categorizing locations into **High review priority**, **Medium review priority**, and **Low review priority** with factor contribution breakdowns, analyst review procedures, and transparent limitations.
- **Chronological Time-Series Forecasting:** Predicts next-day satellite-observed fire-detection counts for any region or worldwide, comparing a **Baseline Lag-1 Persistence Benchmark** with a **Poisson regression model** on a strictly time-ordered held-out test split.
- **Historical Data & Reproducible Notebook:** Complete multi-region historical time series exported to CSV and Parquet, accompanied by a Jupyter notebook for verification.

---

## 2. System Architecture

```mermaid
graph TD
    subgraph Data Providers
        FIRMS[NASA FIRMS Satellite Feeds<br/>VIIRS NOAA-20/21/SNPP & MODIS]
        METEO[Open-Meteo Global Weather<br/>ECMWF / GFS / DWD Models]
        OSM[OpenStreetMap Nominatim<br/>Global Geocoding & Reverse Lookup]
    end

    subgraph Neurora Backend (FastAPI)
        FS[firms_service.py<br/>Multi-Sensor Normalization & Cache]
        WS[weather_service.py<br/>Surface Meteorology & Oxygen Note]
        GS[geocoding_service.py<br/>Caching & Coordinate Fallback]
        RE[risk_engine.py<br/>Explainable EFRI Multi-Factor Index]
        FE[forecasting_engine.py<br/>Baseline vs Poisson Held-Out Eval]
        HS[historical_service.py<br/>Daily Counts Dataset & Parquet]
    end

    subgraph Neurora Frontend
        MAP[Leaflet Interactive Global Map<br/>Clustering, Heatmap, Risk Overlays]
        PANEL_RISK[Fire Risk Gauge & Review Priority]
        PANEL_WEATHER[Weather Station & 24h Trends]
        PANEL_FORECAST[Forecast Metrics & Model Comparison]
        PANEL_HIST[Historical Trends & Export Actions]
    end

    FIRMS --> FS
    METEO --> WS
    OSM --> GS
    FS & WS --> RE
    HS & WS --> FE
    RE & FE & WS & FS --> MAP & PANEL_RISK & PANEL_WEATHER & PANEL_FORECAST & PANEL_HIST
```

---

## 3. Real Satellite Sensors & Attributes

Neurora integrates real NASA FIRMS near-real-time (NRT) datasets:

| Satellite / Platform | Sensor / Instrument | Resolution | Typical Orbit / Revisit | Product Identifier |
| :--- | :--- | :--- | :--- | :--- |
| **NOAA-20 (JPSS-1)** | VIIRS | 375 m | Sun-synchronous (13:30 LT) | `VIIRS_NOAA20_NRT` |
| **NOAA-21 (JPSS-2)** | VIIRS | 375 m | Sun-synchronous (13:30 LT) | `VIIRS_NOAA21_NRT` |
| **Suomi-NPP** | VIIRS | 375 m | Sun-synchronous (13:30 LT) | `VIIRS_SNPP_NRT` |
| **Terra & Aqua** | MODIS | 1 km | Morning / Afternoon Orbit | `MODIS_NRT` (C6.1) |

### Attribute Normalization
For every observation, the system normalizes:
- **Observation Timestamps:** Stored in ISO UTC and converted dynamically to estimated local solar time based on longitude.
- **Fire Radiative Power (FRP):** Measured in Megawatts (MW), indicating rate of radiant energy release.
- **Brightness Temperature:** Recorded in Kelvin (K) and converted to °C.
- **Confidence:** Normalized into standard categories (`low`, `nominal`, `high`) respecting instrument differences.
- **Deduplication:** Composite hashing `(latitude_round, longitude_round, date, time, satellite)` prevents double counting across overlapping swathes.

### Data Ingestion Audit: Rows Loaded vs. Rejected Summary

Every satellite observation ingested into Neurora passes through a deterministic quality and validation pipeline. A continuous audit log tracks **rows evaluated, rows loaded, and rows rejected (with rejection reasons)**:

| Metric / Audit Field | Typical 24h Feed | Pipeline Validation Action & Reason |
| :--- | :--- | :--- |
| **Total Raw Rows Evaluated** | $\sim 28,000 - 45,000$ | Total records retrieved across all 4 satellite feeds (VIIRS NOAA-20, NOAA-21, Suomi-NPP, MODIS). |
| **Valid Rows Loaded** | $\sim 26,000 - 42,000$ | Clean observations with valid coordinates, physical positive FRP, and timestamp integrity. |
| **Duplicate Swaths Deduplicated** | $\sim 1,200 - 3,500$ | **Rejected:** Overlapping orbit swathes from adjacent polar passes observing the same hotspot cell. |
| **Invalid Coordinates** | Filtered ($0$ allowed) | **Rejected:** Out-of-bounds latitude ($\notin [-90, 90]$), longitude ($\notin [-180, 180]$), or NaN values. |
| **Negative / Corrupt FRP** | Filtered ($0$ allowed) | **Rejected:** Unphysical negative Fire Radiative Power values ($\text{FRP} < 0.0\,\text{MW}$) or corrupted telemetry. |
| **Corrupt / Missing Timestamps** | Filtered ($0$ allowed) | **Rejected:** Missing acquisition date or unparseable satellite clock strings. |
| **Spatial / Threshold Filters** | User-defined | **Filtered:** Detections outside requested bounding box or below selected minimum confidence. |

> **Live Audit Endpoint:** Query `GET /api/audit/ingestion` or inspect `data_quality_audit` in any `/api/hotspots` response for a real-time tally of loaded vs. rejected records and exact rejection counts. The dashboard displays this in the **Quality Audit** badge.

---

## 4. Atmospheric Oxygen Transparency

In compliance with rigorous scientific principles:
- **Status:** *“Oxygen measurement unavailable from the connected data sources.”*
- **Scientific Rationale:** Standard meteorological stations and global numerical models (Open-Meteo, ECMWF, NOAA GFS) do not record ambient O₂ concentration.
- **Wildfire Dynamics:** Ambient tropospheric oxygen is virtually constant worldwide (~20.95%) and is **not a predictor of wildfire ignition**. Wildfires ignite and propagate based on **fuel moisture deficit, relative humidity depression, high ambient temperature, wind vectors, and ignition triggers**.

---

## 5. Risk Assessment & Observation Triage Methodologies

Neurora features a dual-layer risk and triage architecture: **Location-Level EFRI** for geographic regions, and **Per-Detection Observation Triage Ranking** for prioritizing individual spaceborne detections.

---

### A. Location-Level: Explainable Environmental Fire-Risk (EFRI)

The EFRI module computes an explainable 0–100 index for any given geographic coordinate or polygon, blending numerical meteorological potential (65%) with spatial hotspot clustering (35%). This 65/35 split is a judgment-based design choice, not an empirically fitted weighting:

$$\text{EFRI} = 0.65 \times (\text{WeatherBase} + \text{SynergyBoost}) + 0.35 \times \text{ThermalActivity}$$

- **WeatherBase:** Synthesized from surface temperature (25%), relative humidity deficit (30%), wind velocity (20%), and precipitation deficit (25%).
- **SynergyBoost:** Non-linear multiplier triggered when extreme heat (>35°C), low RH (<25%), and strong wind (>30 km/h) co-occur.
- **ThermalActivity:** Hotspot counts and cumulative FRP within the surrounding geographic radius (~50 km).

#### Review Priority Categories
- **High review priority (Score $\ge 65$):** Elevated environmental fire indicator driven by high temperatures, low humidity, and strong winds. Analysts should maintain continuous satellite overpass tracking.
- **Medium review priority (Score $35 - 64$):** Moderate environmental indicator with drying trends; periodic satellite review scheduled.
- **Low review priority (Score $< 35$):** Evidence does not indicate elevated environmental fire risk. *Explicitly notes that spaceborne sensors cannot guarantee zero fire activity (e.g. small surface burns under dense canopy or thick cloud cover).*

---

### B. Per-Observation Level: Ranked Observation Triage Engine

While the location EFRI score evaluates regional weather conditions, **the Ranked Observation Triage Engine evaluates individual satellite observations (hotspot pixels)** to prioritize which detections analysts should review first.

Each individual detection is scored across four independent remote sensing dimensions:

1. **Time (Observation Recency, 30% Weight):**
   - Observations $< 1.0\text{h}$ old receive maximum score ($100$).
   - Scores decay smoothly over time: $< 3\text{h}$ (score 85–95), $< 12\text{h}$ (score 50–70), $> 24\text{h}$ (score 10–20).
2. **Fire Radiative Power (FRP, 25% Weight):**
   - Measures radiant heat release in Megawatts (MW) from VIIRS 375m and MODIS 1km sensors.
   - Extreme intense fires ($> 100\text{ MW}$) receive score $100$.
   - Moderate ($25 - 50\text{ MW}$) score 60–80; low ($< 10\text{ MW}$) score 20–40.
3. **Repeat Detections / Vicinity Cluster Density (25% Weight):**
   - Counts the number of overlapping or nearby satellite detections within a **2 km radius** across multiple orbital sweeps (NOAA-20, NOAA-21, Suomi-NPP, MODIS).
   - $\ge 4\text{ repeat detections}$ receives score $100$ (indicates confirmed, persistent fire front).
   - $2 - 3\text{ repeats}$ receives score 60–80; isolated detections ($0\text{ repeats}$) score 15.
4. **Normalized Confidence (20% Weight):**
   - Instrument-normalized detection quality: High (100), Nominal (65), Low (30).

#### Composite Triage Formula
$$\text{TriageScore} = 0.30 \times S_{\text{time}} + 0.25 \times S_{\text{frp}} + 0.25 \times S_{\text{repeat}} + 0.20 \times S_{\text{confidence}}$$

#### Review Priority Tiers & Thresholds
- **High review priority ($\text{TriageScore} \ge 70$):** Immediate analyst inspection recommended due to high intensity, recent pass, and multi-sensor repeat cluster confirmation.
- **Medium review priority ($45 \le \text{TriageScore} < 70$):** Moderate intensity or earlier pass; schedule for standard inspection.
- **Low review priority ($\text{TriageScore} < 45$):** Low FRP, older detection, or isolated single observation.

#### Human-Readable Per-Row Breakdown
Every row in the dashboard's **Ranked Observation Triage Table** displays an explicit natural language breakdown explaining why it was assigned that priority:
- *“Ranked high because: recent (1.2h ago), high FRP (85.4 MW), 4 repeats, high confidence”*
- *“Ranked medium because: earlier pass (8.4h ago), moderate FRP (24.1 MW), 2 repeats, nominal confidence”*
- *“Ranked low because: older detection (21.5h ago), low FRP (4.8 MW), 0 repeats, nominal confidence”*

Each row is accompanied by individual factor chips (`[⚡ 1.2h ago]`, `[🔥 85.4 MW]`, `[🔁 4 repeats]`, `[✓ high conf]`) and an **Inspect** action that flies the interactive map directly to the observation coordinates.

---

## 6. Individual Observation Priority Ranking (OPR) & Per-Row Explanations

In wildfire remote sensing, it is critical to distinguish between **location-level environmental risk** (which evaluates ambient weather and terrain conditions) and **individual observation priority** (which evaluates the severity, urgency, and reliability of each specific satellite detection).

| Dimension | Scope | Primary Drivers | Purpose |
| :--- | :--- | :--- | :--- |
| **EFRI (Environmental Fire Risk)** | Location / Area | 65% Surface Weather & Fuel Deficit, 35% Spatial Thermal Context | Evaluates whether atmospheric conditions support fire spread at a coordinate. |
| **OPR (Observation Priority Ranking)** | Individual Satellite Detection | 35% FRP, 25% Repeat Cluster Detections, 25% Observation Time Recency, 15% Confidence | Ranks each individual satellite observation to support analyst review. |

### The 4-Factor OPR Ranking Formula

$$\text{OPR} = 0.35 \times S_{\text{frp}} + 0.25 \times S_{\text{repeat}} + 0.25 \times S_{\text{time}} + 0.15 \times S_{\text{conf}}$$

1. **Fire Radiative Power (FRP — 35% weight):**  
   $$S_{\text{frp}} = \min\left(100.0, \left(\frac{\text{FRP}}{50.0}\right)^{0.65} \times 100.0\right)$$  
   Direct proxy for instantaneous biomass combustion rate. Higher MW output directly scales fire front intensity.

2. **Repeat Detections in Spatial Cluster (25% weight):**  
   $$S_{\text{repeat}} = \min(100.0, N_{\text{repeats}} \times 20.0)$$  
   Spatial grouping across a $0.02^\circ$ ($\sim 2.2\,\text{km}$) spatial cell. Single isolated detections may represent temporary industrial flaring or surface glints; **multiple repeat detections across successive sensor passes confirm a persistent, expanding wildfire front**.

3. **Observation Time Recency (25% weight):**  
   $$S_{\text{time}} = \max\left(15.0, 100.0 - \frac{\text{Age}_{\text{hours}}}{24.0} \times 85.0\right)$$  
   Fresh observations ($< 3$ hours) receive highest urgency; older passes ($18+$ hours) may have transitioned or been contained.

4. **Algorithmic Confidence (15% weight):**  
   Normalized from sensor quality flags (High $= 95$, Nominal $= 65$, Low $= 35$).

### Priority Tiers & Explanations

- **CRITICAL (Score $\ge 75$):** Severe active flame front, high FRP ($> 50$ MW), multiple repeat passes, recent satellite observation.
- **HIGH (Score $60 - 74$):** High radiative output or confirmed persistent cluster with recent timestamp.
- **ELEVATED (Score $45 - 59$):** Active anomaly with intermediate energy release or moderate cluster support.
- **MODERATE (Score $30 - 44$):** Low-to-moderate thermal anomaly or older daytime overpass.
- **LOW (Score $< 30$):** Isolated single detection with low FRP or older observation time.

### Transparent Per-Row Breakdown in Dashboard
Each row in the **Ranked Satellite Observations** table includes a direct, human-readable breakdown explaining why it achieved its position:
> *“Ranked critical because: recent (3.3h ago), high FRP (699.5 MW), 4 repeat detections in cluster, high satellite confidence (high)”*  
> *“Ranked moderate because: older pass (14.2h ago), moderate FRP (18.4 MW), isolated detection (1 repeat), nominal confidence”*

### Strict English Geographic Naming
All reverse geocoded coordinates, search queries, and selected location cards are filtered through Unicode NFKD Latin transliteration and ASCII normalization. Place names worldwide (e.g. in Asia, Africa, Eastern Europe, South America) are rendered strictly in English without localized or non-Latin script leakage.

---

## 7. Time-Series Forecasting Methodology

The forecasting pipeline predicts **next-day satellite fire-detection counts**:
- **Baseline Model:** Lag-1 persistence benchmark ($y_t = y_{t-1}$).
- **Alternative Model:** Poisson regression, a statistical count model, using an L2 penalty, recent count lags, seasonal terms, and surface weather variables.
- **Evaluation Protocol:** **Strictly chronological held-out test period** (latest 20% of timeline, never randomly shuffled).
- **Reported Metrics:** Held-out Mean Absolute Error (MAE) and Root Mean Squared Error (RMSE) for both lag-1 persistence and Poisson regression, plus a direct statement of whether regression beats the baseline on MAE. No prediction interval is reported.
- **Definition:** Predicts satellite-observed active fire detections under defined counting rules, not confirmed ground fire perimeters.

---

## 8. Installation & Quick Start

### Prerequisites
- Python 3.10+ (Tested on Python 3.14)
- Modern Web Browser (Chrome, Edge, Firefox, Safari)

### 1. Clone & Setup Environment
```bash
git clone <repo-url>
cd Neurora
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment (Optional)
Copy `.env.example` to `.env`:
```bash
copy .env.example .env
```
*(Optional: add your NASA FIRMS `MAP_KEY` if you have one. Public feeds work out of the box without any key!)*

### 3. Run Automated Tests

The test suite covers end-to-end API verification, observation priority scoring behavior, and data validation/row rejection:

```bash
# Run all 25 automated tests across the entire suite:
python -m pytest tests/ -v
```

#### Test Suite Breakdown:

| Test Module | Test Coverage | Key Invariants Verified |
| :--- | :--- | :--- |
| **`tests/test_scoring.py`** | Observation Priority Ranking (OPR) | • **Higher FRP strictly raises score** (FRP 250 MW > 45 MW > 5 MW)<br/>• **Older detections strictly lower score** (1h ago > 8h ago > 22h ago)<br/>• **Repeat detections raise score** (5 cluster repeats > 1 isolated detection)<br/>• **Confidence scaling** (High > Nominal > Low)<br/>• **Score bounded in $[0, 100]$** and priority tiers correctly assigned<br/>• **Per-row human explanations** accurately describe the ranking drivers |
| **`tests/test_validation.py`** | Row Validation & Rejection Pipeline | • **Valid rows accepted** and normalized<br/>• **Out-of-range coordinates rejected** (Lat $> 90$ or $< -90$, Lon $> 180$ or $< -180$)<br/>• **NaN and corrupted coordinates rejected** (`invalid_or_missing_coordinates`)<br/>• **Negative or non-numeric FRP rejected** (`negative_or_corrupt_frp`)<br/>• **Corrupt/missing timestamps rejected** (`corrupt_or_missing_timestamp`)<br/>• **Spatial bounding box filter rejection** (`outside_bounding_box`)<br/>• **Swath overlap deduplication audit consistency** |
| **`tests/test_api.py`** | End-to-End API & Integration | • Multi-sensor satellite endpoints (`/api/hotspots`)<br/>• Sensor filtering (NOAA-20, NOAA-21, Suomi-NPP, MODIS)<br/>• Surface meteorology & atmospheric oxygen status (`/api/weather`)<br/>• Reverse geocoding English fallback (`/api/geocode/reverse`)<br/>• EFRI 3-tier risk alerts (`/api/risk`)<br/>• Chronological forecasting with held-out test split (`/api/forecast`)<br/>• Historical exports (`/api/export/csv`, `/api/export/parquet`) |

### 4. Launch the Dashboard
```bash
python -m backend.main
```
Open your browser at: **[http://localhost:8000](http://localhost:8000)**

---

## 9. Exporting Data & Reproducible Notebooks

- **CSV Export:** `GET /api/export/csv` or via the dashboard "Export CSV" button.
- **Parquet Export:** `GET /api/export/parquet` for fast analytical querying.
- **Jupyter Notebook:** Open `notebooks/forecasting_evaluation.ipynb` to step through model training, held-out evaluation, and residual plotting.
- **Optional CIFAR-10 CNN example:** `notebooks/cifar10_cnn.py` trains a small image classifier on general CIFAR-10 objects. Install its separate dependencies with `pip install -r requirements-cifar10.txt`, then run `python notebooks/cifar10_cnn.py`. It downloads CIFAR-10 into `data/cifar10/` and saves weights under `models/`; this model is not used by the wildfire dashboard and does not classify fire imagery.

---

## 10. Data Provider Terms & Attributions

- **NASA FIRMS:** EOSDIS LANCE / LDOPE / SSEC. Real satellite active fire data.
- **Esri & NASA:** Esri World Dark Gray Canvas, World Imagery, and NASA Black Marble (GIBS / EOSDIS).
- **OpenStreetMap:** OpenStreetMap contributors.
