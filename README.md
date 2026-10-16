# Neurora — AI-Powered Worldwide Fire Monitoring & Forecasting System

**Global Environmental Hotspot Activity Forecast System**  
*Built with Real Satellite Observations, Global Geospatial Maps, Live Meteorological Data, and Chronological Count Forecasting.*

---

## 1. Project Overview

**Neurora** is an advanced worldwide environmental intelligence dashboard and machine-learning forecasting system designed to monitor active thermal hotspots and forecast daily satellite fire detections across the entire globe.

### Key Capabilities
- **Worldwide Coverage:** Full global map covering all continents, countries, oceans, islands, and custom bounding boxes.
- **Dark Canvas & Real World Satellite Maps:** Instant 1-click toggling between:
  - **🌌 Real Dark Canvas (Active Default):** Official GIS standard Esri World Dark Gray Canvas with crisp geopolitical borders and place labels, tailored for high-contrast thermal hotspot radiation.
  - **✨ NASA Night Earth:** NASA Black Marble (Suomi-NPP VIIRS Day/Night Band) nighttime satellite radiance.
  - **🛰️ Real World Satellite Earth:** High-resolution photographic satellite imagery from space (Esri World Imagery) with geopolitical boundaries and place labels.
- **Real Satellite Observations (NASA FIRMS):** Direct multi-sensor integration of **VIIRS NOAA-20**, **VIIRS NOAA-21**, **VIIRS Suomi-NPP**, and **MODIS Terra/Aqua Collection 6.1**.
- **Live Surface Meteorology (Open-Meteo):** Real-time temperature, relative humidity, wind speed & direction compass, precipitation deficit, and 24-hour forecast trends.
- **Atmospheric Oxygen Integrity:** Explicit reporting indicating that atmospheric oxygen concentration is not measured by standard meteorological stations and is not a direct predictor of wildfire ignition, as ambient tropospheric O₂ (~20.95%) is globally ubiquitous.
- **Explainable Environmental Fire-Risk (EFRI):** Multi-factor risk engine categorizing locations into **RED — HIGH ALERT**, **ORANGE — MEDIUM ALERT**, and **GREEN — LOW RISK** with factor contribution breakdowns, monitoring actions, and transparent limitations.
- **Chronological Time-Series Forecasting:** Predicts next-day satellite-observed fire-detection counts for any region or worldwide, comparing a **Baseline Lag-1 Persistence Benchmark** with a **Regularized Poisson Count Regression Model** on a strictly time-ordered held-out test split.
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
        PANEL_RISK[Fire Risk Gauge & 3-Level Alerts]
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

---

## 4. Atmospheric Oxygen Transparency

In compliance with rigorous scientific principles:
- **Status:** *“Oxygen measurement unavailable from the connected data sources.”*
- **Scientific Rationale:** Standard meteorological stations and global numerical models (Open-Meteo, ECMWF, NOAA GFS) do not record ambient O₂ concentration.
- **Wildfire Dynamics:** Ambient tropospheric oxygen is virtually constant worldwide (~20.95%) and is **not a predictor of wildfire ignition**. Wildfires ignite and propagate based on **fuel moisture deficit, relative humidity depression, high ambient temperature, wind vectors, and ignition triggers**.

---

## 5. Explainable Environmental Fire-Risk (EFRI)

The EFRI module computes an explainable 0–100 index integrating meteorological variables with active satellite observations:

$$\text{EFRI} = 0.65 \times (\text{WeatherBase} + \text{SynergyBoost}) + 0.35 \times \text{ThermalActivity}$$

### Alert Levels
- **RED — HIGH ALERT (Score $\ge 65$):** Elevated environmental fire danger driven by hot, dry, and windy conditions or high density of active satellite hotspots. Requires continuous satellite overpass monitoring.
- **ORANGE — MEDIUM ALERT (Score $35 - 64$):** Moderate environmental risk with drying trends and elevated potential for ignition spread.
- **GREEN — LOW RISK (Score $< 35$):** Evidence does not indicate elevated environmental fire risk. *Explicitly notes that this does not prove a location is completely fire-free (e.g. small surface fires under dense canopy may not be detected).*

---

## 6. Individual Observation Priority Ranking (OPR) & Per-Row Explanations

In wildfire remote sensing, it is critical to distinguish between **location-level environmental risk** (which evaluates ambient weather and terrain conditions) and **individual observation priority** (which evaluates the severity, urgency, and reliability of each specific satellite detection).

| Dimension | Scope | Primary Drivers | Purpose |
| :--- | :--- | :--- | :--- |
| **EFRI (Environmental Fire Risk)** | Location / Area | 65% Surface Weather & Fuel Deficit, 35% Spatial Thermal Context | Evaluates whether atmospheric conditions support fire spread at a coordinate. |
| **OPR (Observation Priority Ranking)** | Individual Satellite Detection | 35% FRP, 25% Repeat Cluster Detections, 25% Observation Time Recency, 15% Confidence | Ranks every individual spaceborne observation to prioritize urgent response. |

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
- **Alternative Model:** Regularized Poisson Count Regression ($\log(\lambda_t) = \beta_0 + \sum \beta_i X_{it}$) with L2 penalty, utilizing multi-day lags ($t-1, t-2, \text{MA}_7$), cyclical day-of-year trigonometric terms, and surface meteorological variables.
- **Evaluation Protocol:** **Strictly chronological held-out test period** (latest 20% of timeline, never randomly shuffled).
- **Reported Metrics:** Mean Absolute Error (MAE), Root Mean Squared Error (RMSE), and 80% prediction intervals.
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
```bash
python -m pytest tests/test_api.py -v
```

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

---

## 10. Data Provider Terms & Attributions

- **NASA FIRMS:** EOSDIS LANCE / LDOPE / SSEC. Real satellite active fire data.
- **Esri & NASA:** Esri World Dark Gray Canvas, World Imagery, and NASA Black Marble (GIBS / EOSDIS).
- **OpenStreetMap:** OpenStreetMap contributors.
