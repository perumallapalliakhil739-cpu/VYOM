/**
 * Neurora Application Controller
 * Orchestrates API calls, state updates, UI panels, search, and interactions.
 */

const App = {
  currentRegion: 'GLOBAL',
  currentMode: 'global',
  selectedLocation: {
    lat: -14.235,
    lon: -51.925,
    name: 'Brazil (Amazon / Cerrado Biome)'
  },
  searchDebounceTimer: null,
  rawHotspots: [],
  triageFilters: {
    priority: 'ALL',
    onlyRepeats: false,
    sort: 'rank',
    search: ''
  },

  async init() {
    Charts.init();

    // Initialize Map with location selection callback
    MapController.init('map', (lat, lon) => {
      this.handleLocationClick(lat, lon);
    });

    // Setup UI event listeners
    this.setupEventListeners();
    this.loadFireImageStatus();

    // Initial Load
    await this.loadInitialData();
  },

  setupEventListeners() {
    // Mode Switcher
    const btnGlobal = document.getElementById('btnModeGlobal');
    const btnRegion = document.getElementById('btnModeRegion');
    if (btnGlobal && btnRegion) {
      btnGlobal.addEventListener('click', () => this.switchMode('global'));
      btnRegion.addEventListener('click', () => this.switchMode('region'));
    }

    // Region Select Dropdown
    const regionSelect = document.getElementById('regionSelect');
    if (regionSelect) {
      regionSelect.addEventListener('change', (e) => {
        this.selectRegion(e.target.value);
      });
    }

    // Global Search Input with Debouncing
    const searchInput = document.getElementById('globalSearchInput');
    const searchClear = document.getElementById('searchClearBtn');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        const query = e.target.value;
        if (searchClear) searchClear.style.display = query ? 'block' : 'none';
        clearTimeout(this.searchDebounceTimer);
        this.searchDebounceTimer = setTimeout(() => {
          this.handleSearch(query);
        }, 350);
      });

      searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          this.handleSearchSubmit(searchInput.value);
        }
      });
    }

    if (searchClear) {
      searchClear.addEventListener('click', () => {
        searchInput.value = '';
        searchClear.style.display = 'none';
        document.getElementById('searchResultsDropdown').style.display = 'none';
      });
    }

    // Satellite Filter Buttons
    const satButtons = document.querySelectorAll('#satelliteFilters .filter-btn');
    satButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        satButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const sat = btn.dataset.sat;
        MapController.setSatelliteFilter(sat);
      });
    });

    // Basemap Filter Buttons (Dark Canvas, Real Satellite, Terrain)
    const basemapButtons = document.querySelectorAll('#basemapButtons .filter-btn');
    basemapButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        basemapButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const mode = btn.dataset.basemap;
        MapController.setBasemap(mode);
      });
    });

    // Confidence Dropdown
    const confSelect = document.getElementById('confidenceSelect');
    if (confSelect) {
      confSelect.addEventListener('change', (e) => {
        MapController.setConfidenceFilter(e.target.value);
      });
    }

    // Min FRP Slider
    const frpSlider = document.getElementById('minFrpSlider');
    const frpValText = document.getElementById('minFrpValue');
    if (frpSlider) {
      frpSlider.addEventListener('input', (e) => {
        const val = parseInt(e.target.value, 10);
        if (frpValText) frpValText.innerText = `${val} MW`;
        MapController.setMinFrp(val);
      });
    }

    // Layer Toggles
    const chkCluster = document.getElementById('chkCluster');
    if (chkCluster) {
      chkCluster.addEventListener('change', (e) => MapController.toggleCluster(e.target.checked));
    }
    const chkHeatmap = document.getElementById('chkHeatmap');
    if (chkHeatmap) {
      chkHeatmap.addEventListener('change', (e) => MapController.toggleHeatmap(e.target.checked));
    }
    const chkRisk = document.getElementById('chkRiskLayer');
    if (chkRisk) {
      chkRisk.addEventListener('change', (e) => MapController.toggleRiskLayer(e.target.checked));
    }

    // Reset View Button
    const btnReset = document.getElementById('btnResetView');
    if (btnReset) {
      btnReset.addEventListener('click', () => {
        MapController.resetToWorldView();
      });
    }

    // Refresh Button
    const btnRefresh = document.getElementById('btnRefresh');
    if (btnRefresh) {
      btnRefresh.addEventListener('click', () => this.refreshAllData());
    }

    // Triage Priority Filter Buttons
    const triageBtns = document.querySelectorAll('#triagePriorityFilter .triage-pill-btn');
    triageBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        triageBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.triageFilters.priority = btn.dataset.priority;
        this.renderRankedTriageTable();
      });
    });

    // Triage Repeat Clusters Only Checkbox
    const chkOnlyRepeats = document.getElementById('chkOnlyRepeats');
    if (chkOnlyRepeats) {
      chkOnlyRepeats.addEventListener('change', (e) => {
        this.triageFilters.onlyRepeats = e.target.checked;
        this.renderRankedTriageTable();
      });
    }

    // Triage Sort Dropdown
    const sortSelect = document.getElementById('triageSortSelect');
    if (sortSelect) {
      sortSelect.addEventListener('change', (e) => {
        this.triageFilters.sort = e.target.value;
        this.renderRankedTriageTable();
      });
    }

    // Triage Table Instant Search
    const triageSearch = document.getElementById('triageTableSearchInput');
    if (triageSearch) {
      triageSearch.addEventListener('input', (e) => {
        this.triageFilters.search = e.target.value;
        this.renderRankedTriageTable();
      });
    }

    // Lower Tab Switching
    const tabButtons = document.querySelectorAll('.tab-btn');
    tabButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        tabButtons.forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        const targetId = btn.dataset.tab;
        const targetContent = document.getElementById(targetId);
        if (targetContent) targetContent.classList.add('active');
      });
    });

    const reviewImageButton = document.getElementById('btnReviewFireImage');
    if (reviewImageButton) {
      reviewImageButton.addEventListener('click', () => this.reviewFireImage());
    }

    // Settings Modal
    const btnSettings = document.getElementById('btnSettings');
    const modalSettings = document.getElementById('settingsModal');
    const modalClose = document.getElementById('modalCloseBtn');
    const modalCancel = document.getElementById('modalCancelBtn');
    const modalSave = document.getElementById('modalSaveBtn');

    if (btnSettings && modalSettings) {
      btnSettings.addEventListener('click', () => { modalSettings.style.display = 'flex'; });
    }
    if (modalClose && modalSettings) {
      modalClose.addEventListener('click', () => { modalSettings.style.display = 'none'; });
    }
    if (modalCancel && modalSettings) {
      modalCancel.addEventListener('click', () => { modalSettings.style.display = 'none'; });
    }
    if (modalSave && modalSettings) {
      modalSave.addEventListener('click', () => {
        modalSettings.style.display = 'none';
        this.refreshAllData();
      });
    }

    // Close search dropdown on click outside
    document.addEventListener('click', (e) => {
      const searchBox = document.querySelector('.search-box-container');
      const dropdown = document.getElementById('searchResultsDropdown');
      if (searchBox && dropdown && !searchBox.contains(e.target)) {
        dropdown.style.display = 'none';
      }
    });
  },

  async loadInitialData() {
    this.showLoadingFreshness('Fetching Real Satellite Feeds...');

    // 1. Fetch Hotspots with Triage Rankings
    const hotspotsResponse = await API.getHotspots({ limit: 8000 });
    if (hotspotsResponse) {
      this.rawHotspots = hotspotsResponse.hotspots || [];
      this.updateSummaryMetrics(hotspotsResponse);
      MapController.setHotspots(this.rawHotspots);
      this.renderRankedTriageTable();
      this.updateTriageToolbarCounters();
    }

    // 2. Load Selected Location Analysis (default: Amazon / Cerrado high fire-activity region)
    await this.inspectLocation(this.selectedLocation.lat, this.selectedLocation.lon, this.selectedLocation.name);

    // 3. Load Forecasting & Time Series for current region
    await this.loadForecastAndSeries(this.currentRegion);

    this.showFreshnessSynced();
  },

  async refreshAllData() {
    const btn = document.getElementById('btnRefresh');
    if (btn) btn.classList.add('spinning');
    this.showLoadingFreshness('Updating satellite observations...');

    const hotspotsResponse = await API.getHotspots({ limit: 8000, refresh: true });
    if (hotspotsResponse) {
      this.rawHotspots = hotspotsResponse.hotspots || [];
      this.updateSummaryMetrics(hotspotsResponse);
      MapController.setHotspots(this.rawHotspots);
      this.renderRankedTriageTable();
      this.updateTriageToolbarCounters();
    }

    await this.inspectLocation(this.selectedLocation.lat, this.selectedLocation.lon, this.selectedLocation.name);
    await this.loadForecastAndSeries(this.currentRegion);

    if (btn) btn.classList.remove('spinning');
    this.showFreshnessSynced();
  },

  updateTriageToolbarCounters() {
    if (!this.rawHotspots) return;
    const high = this.rawHotspots.filter(r => r.triage_tier === 'HIGH').length;
    const med = this.rawHotspots.filter(r => r.triage_tier === 'MEDIUM').length;
    const low = this.rawHotspots.filter(r => r.triage_tier === 'LOW').length;
    const clusters = this.rawHotspots.filter(r => (r.repeat_count || 0) > 0).length;

    const elH = document.getElementById('countHighPriority');
    const elM = document.getElementById('countMedPriority');
    const elL = document.getElementById('countLowPriority');
    const elC = document.getElementById('countClusterOnly');

    if (elH) elH.innerText = high.toLocaleString();
    if (elM) elM.innerText = med.toLocaleString();
    if (elL) elL.innerText = low.toLocaleString();
    if (elC) elC.innerText = clusters.toLocaleString();
  },

  switchMode(mode) {
    this.currentMode = mode;
    const btnGlobal = document.getElementById('btnModeGlobal');
    const btnRegion = document.getElementById('btnModeRegion');

    if (mode === 'global') {
      btnGlobal.classList.add('active');
      btnRegion.classList.remove('active');
      document.getElementById('regionSelect').value = 'GLOBAL';
      this.selectRegion('GLOBAL');
      MapController.resetToWorldView();
    } else {
      btnRegion.classList.add('active');
      btnGlobal.classList.remove('active');
      // If currently on global, default to South America
      const sel = document.getElementById('regionSelect');
      if (sel.value === 'GLOBAL') {
        sel.value = 'SOUTH_AMERICA';
        this.selectRegion('SOUTH_AMERICA');
      }
    }
  },

  async selectRegion(geoId) {
    this.currentRegion = geoId;
    const regionSelect = document.getElementById('regionSelect');
    if (regionSelect && regionSelect.value !== geoId) {
      regionSelect.value = geoId;
    }

    // Update time series title
    const selOption = regionSelect ? regionSelect.options[regionSelect.selectedIndex] : null;
    const regName = selOption ? selOption.text : geoId;
    const tsTitle = document.getElementById('tsRegionTitle');
    if (tsTitle) tsTitle.innerText = `${regName} Historical Daily Detections`;

    // Coordinates for region centers
    const regionCenters = {
      'GLOBAL': [20.0, 0.0, 2],
      'AFRICA': [2.0, 21.0, 3],
      'SOUTH_AMERICA': [-15.0, -55.0, 3],
      'NORTH_AMERICA': [45.0, -100.0, 3],
      'ASIA': [35.0, 100.0, 3],
      'OCEANIA': [-25.0, 135.0, 3],
      'EUROPE': [50.0, 15.0, 4],
      'BRAZIL': [-10.0, -52.0, 4],
      'AUSTRALIA': [-25.0, 133.0, 4],
      'UNITED_STATES': [39.0, -98.0, 4],
      'CANADA': [56.0, -106.0, 3],
      'CONGO': [-2.8, 23.6, 5],
      'INDONESIA': [-0.7, 113.9, 5],
      'INDIA': [20.5, 78.9, 4],
      'SPAIN': [40.4, -3.7, 5]
    };

    const target = regionCenters[geoId] || [20.0, 0.0, 2];
    MapController.panToLocation(target[0], target[1], target[2]);

    await this.loadForecastAndSeries(geoId);
  },

  async handleLocationClick(lat, lon) {
    // Reverse geocode clicked coordinates
    const geo = await API.reverseGeocode(lat, lon);
    const locName = geo.display_name || `Coordinates ${lat.toFixed(4)}°, ${lon.toFixed(4)}°`;
    this.selectedLocation = { lat, lon, name: locName };
    await this.inspectLocation(lat, lon, locName);
  },

  async inspectLocation(lat, lon, name) {
    // Update location card
    const nameEl = document.getElementById('selectedLocName');
    const coordsEl = document.getElementById('selectedLocCoords');
    const adminEl = document.getElementById('selectedLocAdmin');
    const resolvedBadge = document.getElementById('locResolvedBadge');

    if (nameEl) nameEl.innerText = name;
    if (coordsEl) coordsEl.innerText = `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`;
    if (adminEl) adminEl.innerText = `Analyzing local meteorological & satellite parameters...`;

    // 1. Fetch live Open-Meteo Weather
    const weather = await API.getWeather(lat, lon, name);
    if (weather) {
      this.updateWeatherUI(weather);
    }

    // 2. Fetch explainable fire risk
    const risk = await API.getRisk(lat, lon, name);
    if (risk) {
      this.updateRiskUI(risk);
    }
  },

  updateSummaryMetrics(data) {
    const summary = data.summary || {};
    const meta = data.metadata || {};

    const elTotal = document.getElementById('metricTotalDetections');
    const elNew24 = document.getElementById('metricNew24h');
    const elNewPct = document.getElementById('metricNew24hPct');
    const elHighConf = document.getElementById('metricHighConf');
    const elAvgFrp = document.getElementById('metricAvgFrp');
    const elMaxFrp = document.getElementById('metricMaxFrp');

    if (elTotal) elTotal.innerText = (summary.total_count || 0).toLocaleString();
    if (elNew24) elNew24.innerText = (summary.new_24h_count || 0).toLocaleString();
    
    if (elNewPct && summary.total_count > 0) {
      const pct = Math.round((summary.new_24h_count / summary.total_count) * 100);
      elNewPct.innerText = `${pct}% of active feed`;
    }

    if (elHighConf) elHighConf.innerText = (summary.high_confidence_count || 0).toLocaleString();
    if (elAvgFrp) elAvgFrp.innerText = `${summary.avg_frp_mw || 0} MW`;
    if (elMaxFrp) elMaxFrp.innerText = `${summary.max_frp_mw || 0} MW`;

    // Satellite breakdown pills in card 1
    const satPillsContainer = document.getElementById('metricSatBreakdownPills');
    if (satPillsContainer && summary.satellite_breakdown) {
      let pillsHtml = '';
      for (const [sat, count] of Object.entries(summary.satellite_breakdown)) {
        pillsHtml += `<span class="footer-val" style="margin-right: 8px;">${sat}: ${count.toLocaleString()}</span>`;
      }
      satPillsContainer.innerHTML = pillsHtml;
    }

    // Ingestion Audit Summary Pill & Table Subtitle
    const audit = data.data_quality_audit || meta.ingestion_audit || {};
    const auditPill = document.getElementById('auditSummaryPill');
    const tableSub = document.getElementById('tableSubtitle');
    if (auditPill && audit.valid_rows_loaded !== undefined) {
      auditPill.innerHTML = `🛡️ Audit: ${audit.valid_rows_loaded.toLocaleString()} Loaded • ${audit.total_rows_rejected.toLocaleString()} Filtered/Rejected`;
      auditPill.title = audit.summary_statement || 'Data Ingestion & Integrity Quality Audit';
    }
    if (tableSub && audit.total_raw_rows_fetched) {
      tableSub.innerText = `${audit.valid_rows_loaded.toLocaleString()} valid observations loaded from ${audit.total_raw_rows_fetched.toLocaleString()} raw detections (${audit.total_rows_rejected.toLocaleString()} rejected / filtered: ${audit.duplicate_swaths_deduplicated || 0} swath duplicates, ${audit.rejection_breakdown?.invalid_or_missing_coordinates || 0} coordinate errors, ${audit.rejection_breakdown?.negative_or_corrupt_frp || 0} corrupt FRPs).`;
    }
  },

  updateWeatherUI(wData) {
    const current = wData.current || {};
    const location = wData.location || {};
    const oxygen = wData.atmospheric_oxygen || {};

    // Metric strip
    const elTemp = document.getElementById('metricCurrentTemp');
    const elHumidity = document.getElementById('metricCurrentHumidity');
    const elWind = document.getElementById('metricCurrentWind');

    if (elTemp && current.temperature_c !== null) elTemp.innerText = `${current.temperature_c.toFixed(1)} °C`;
    if (elHumidity && current.relative_humidity_pct !== null) elHumidity.innerText = `RH: ${current.relative_humidity_pct}%`;
    if (elWind && current.wind_speed_kmh !== null) {
      elWind.innerText = `${current.wind_speed_kmh} km/h ${current.wind_direction_cardinal || ''}`;
    }

    // Sidebar Weather Card
    const wTemp = document.getElementById('weatherTemp');
    const wApparent = document.getElementById('weatherApparent');
    const wHumidity = document.getElementById('weatherHumidity');
    const wWind = document.getElementById('weatherWind');
    const wWindCompass = document.getElementById('weatherWindCompass');
    const wWindGust = document.getElementById('weatherWindGust');
    const wPrecip = document.getElementById('weatherPrecip');
    const wTimestamp = document.getElementById('weatherTimestamp');

    if (wTemp && current.temperature_c !== null) wTemp.innerText = `${current.temperature_c.toFixed(1)} °C`;
    if (wApparent && current.apparent_temperature_c !== null) wApparent.innerText = `Feels like ${current.apparent_temperature_c.toFixed(1)} °C`;
    if (wHumidity && current.relative_humidity_pct !== null) wHumidity.innerText = `${current.relative_humidity_pct}%`;
    if (wWind && current.wind_speed_kmh !== null) wWind.innerText = `${current.wind_speed_kmh} km/h`;
    if (wWindCompass) wWindCompass.innerText = current.wind_direction_cardinal || '';
    if (wWindGust && current.wind_gusts_kmh !== null) wWindGust.innerText = `Gusts: ${current.wind_gusts_kmh} km/h`;
    if (wPrecip && current.precipitation_mm !== null) wPrecip.innerText = `${current.precipitation_mm} mm`;
    if (wTimestamp && current.timestamp) wTimestamp.innerText = `${current.timestamp.replace('T', ' ')} Local`;

    // Render 24h Hourly Weather Chart
    if (wData.hourly_series) {
      Charts.renderHourlyWeather('weatherHourlyChart', wData.hourly_series);
    }

    // Atmospheric Oxygen Note
    const oxyStatement = document.getElementById('oxygenStatement');
    const oxyNote = document.getElementById('oxygenNote');
    if (oxyStatement) oxyStatement.innerText = oxygen.statement || "Oxygen measurement unavailable from the connected data sources.";
    if (oxyNote && oxygen.scientific_explanation) oxyNote.innerText = oxygen.scientific_explanation;

    // Remote Sensing & Cloud Obscuration Status
    const rs = wData.remote_sensing_analysis || {};
    const elCloudVal = document.getElementById('cloudCoverVal');
    const elCloudBadge = document.getElementById('cloudStatusBadge');
    const elCloudBar = document.getElementById('cloudCoverBar');
    const elCloudCond = document.getElementById('cloudConditionText');

    const cloudPct = current.cloud_cover_pct !== undefined ? current.cloud_cover_pct : (rs.cloud_cover_pct || 0);
    if (elCloudVal) elCloudVal.innerText = `${cloudPct}%`;
    if (elCloudBar) elCloudBar.style.width = `${Math.min(100, Math.max(5, cloudPct))}%`;

    const statusBadge = rs.cloud_status || (cloudPct < 25 ? 'CLEAR' : cloudPct < 70 ? 'MODERATE' : 'OBSCURED');
    if (elCloudBadge) {
      elCloudBadge.innerText = statusBadge;
      elCloudBadge.className = `cloud-badge ${statusBadge.toLowerCase()}`;
    }
    if (elCloudCond) {
      elCloudCond.innerText = rs.observation_condition || (
        cloudPct < 25 ? "Optimal MWIR & thermal surface detection active." :
        cloudPct < 70 ? "Partial Cloud Cover — Contextual Band Masking Active." :
        "Dense Cloud Layer — Multi-Satellite Constellation Revisit Required."
      );
    }
  },

  updateRiskUI(riskData) {
    const score = riskData.score || 0;
    const level = riskData.alert_level || 'GREEN';
    const title = riskData.alert_title || (level === 'RED' ? 'High review priority' : level === 'ORANGE' ? 'Medium review priority' : 'Low review priority');
    const priorityLabel = riskData.review_priority || title;
    const factors = riskData.factors || {};

    // Metric card update
    const cardLevel = document.getElementById('metricRiskLevel');
    const cardScore = document.getElementById('metricRiskScore');
    const cardBadge = document.getElementById('riskBadgeSelected');
    const cardLoc = document.getElementById('metricRiskLocation');

    if (cardLevel) {
      cardLevel.innerText = level === 'RED' ? 'High' : level === 'ORANGE' ? 'Medium' : 'Low';
      cardLevel.className = `metric-number text-${level === 'RED' ? 'red' : level === 'ORANGE' ? 'amber' : 'emerald'}`;
    }
    if (cardScore) cardScore.innerText = `Score: ${score}/100`;
    if (cardBadge) {
      cardBadge.innerText = priorityLabel;
      cardBadge.className = `metric-badge ${level.toLowerCase()}`;
    }
    if (cardLoc) cardLoc.innerHTML = `<span>Location: ${riskData.location_name || 'Selected'}</span>`;

    // Sidebar Risk Panel
    const riskPill = document.getElementById('riskAlertPill');
    const alertBanner = document.getElementById('riskAlertBanner');
    const alertTitle = document.getElementById('riskAlertTitle');
    const gaugeScore = document.getElementById('riskGaugeScore');
    const gaugeOuter = document.querySelector('.gauge-circle-outer');
    const summaryText = document.getElementById('riskSummaryText');

    const lvlLower = level.toLowerCase();
    if (riskPill) {
      riskPill.innerText = priorityLabel;
      riskPill.className = `alert-status-pill ${lvlLower}`;
    }
    if (alertBanner) {
      alertBanner.className = `alert-banner ${lvlLower}`;
    }
    if (alertTitle) alertTitle.innerText = title;
    if (gaugeScore) gaugeScore.innerText = score;
    if (gaugeOuter) {
      gaugeOuter.className = `gauge-circle-outer ${lvlLower}`;
    }
    if (summaryText) summaryText.innerText = riskData.summary || '';

    // Factors Progress Bars
    if (factors.temperature) {
      document.getElementById('factTempVal').innerText = `${factors.temperature.raw.toFixed(1)}°C`;
      document.getElementById('factTempBar').style.width = `${factors.temperature.subscore}%`;
    }
    if (factors.relative_humidity) {
      document.getElementById('factRhVal').innerText = `${factors.relative_humidity.raw.toFixed(0)}%`;
      document.getElementById('factRhBar').style.width = `${factors.relative_humidity.subscore}%`;
    }
    if (factors.wind_speed) {
      document.getElementById('factWindVal').innerText = `${factors.wind_speed.raw.toFixed(1)} km/h`;
      document.getElementById('factWindBar').style.width = `${factors.wind_speed.subscore}%`;
    }
    if (factors.moisture_deficit) {
      const p = factors.moisture_deficit.raw_precip;
      document.getElementById('factMoistVal').innerText = p > 0 ? `${p} mm rain` : 'Dry Spell';
      document.getElementById('factMoistBar').style.width = `${factors.moisture_deficit.subscore}%`;
    }
    if (factors.thermal_activity) {
      const cnt = factors.thermal_activity.nearby_hotspots;
      const frp = factors.thermal_activity.total_frp_mw;
      document.getElementById('factHotspotVal').innerText = `${cnt} detection(s) (${frp.toFixed(1)} MW)`;
      document.getElementById('factHotspotBar').style.width = `${factors.thermal_activity.subscore}%`;
    }

    // Recommendations list
    const recList = document.getElementById('riskRecList');
    if (recList && riskData.recommendations) {
      recList.innerHTML = riskData.recommendations.map(r => `<li>${r}</li>`).join('');
    }
  },

  async loadForecastAndSeries(geoId) {
    const forecast = await API.getForecast(geoId);
    if (!forecast || forecast.error) return;

    const nextDay = forecast.next_day_forecast || {};
    const comp = forecast.model_comparison || {};
    const evalProto = forecast.evaluation_protocol || {};

    // Update Next-Day forecast Metric card
    const fCount = document.getElementById('metricForecastCount');
    const fTrend = document.getElementById('metricForecastTrend');
    const fBaseline = document.getElementById('metricBaselineCount');
    const fModel = document.getElementById('metricForecastModel');

    if (fCount) fCount.innerText = (nextDay.prediction ?? nextDay.baseline_prediction ?? 0).toLocaleString();
    if (fTrend) fTrend.innerText = `${nextDay.trend_vs_yesterday} vs Yesterday`;
    if (fBaseline) fBaseline.innerText = (nextDay.baseline_prediction || 0).toLocaleString();
    if (fModel) fModel.innerText = nextDay.model_name || 'Lag-1 persistence';

    // Update Lower Forecasting Tab
    const evalPill = document.getElementById('evalPeriodPill');
    if (evalPill && evalProto.test_period) {
      evalPill.innerText = `Held-Out Test: ${evalProto.test_period.start_date} to ${evalProto.test_period.end_date} (${evalProto.test_period.evaluated_days} days)`;
    }

    const bMae = document.getElementById('evalBaselineMae');
    const bRmse = document.getElementById('evalBaselineRmse');
    const aMae = document.getElementById('evalAltMae');
    const aModelName = document.getElementById('evalAltModelName');
    const aRmse = document.getElementById('evalAltRmse');
    const narrative = document.getElementById('evalNarrative');
    const improveStat = document.getElementById('evalImprovementStat');

    if (bMae) bMae.innerText = comp.baseline_model?.held_out_mae?.toLocaleString() || '--';
    if (bRmse) bRmse.innerText = comp.baseline_model?.held_out_rmse?.toLocaleString() || '--';
    if (aMae) aMae.innerText = comp.alternative_model?.held_out_mae?.toLocaleString() || '--';
    if (aModelName) aModelName.innerText = comp.alternative_model?.name || 'Poisson regression';
    if (aRmse) aRmse.innerText = comp.alternative_model?.held_out_rmse?.toLocaleString() || '--';
    if (narrative) narrative.innerText = comp.narrative || '';
    if (improveStat) {
      const baselineMae = comp.baseline_model?.held_out_mae;
      const alternativeMae = comp.alternative_model?.held_out_mae;
      if (typeof baselineMae === 'number' && typeof alternativeMae === 'number') {
        if (alternativeMae < baselineMae && baselineMae > 0) {
          const pct = ((baselineMae - alternativeMae) / baselineMae * 100).toFixed(1);
          improveStat.innerText = `Alternative model MAE ${pct}% lower than lag-1`;
          improveStat.style.color = '#10B981';
        } else if (alternativeMae > baselineMae && baselineMae > 0) {
          const pct = ((alternativeMae - baselineMae) / baselineMae * 100).toFixed(1);
          improveStat.innerText = `Alternative model MAE ${pct}% higher than lag-1`;
          improveStat.style.color = '#FCA5A5';
        } else if (alternativeMae === baselineMae) {
          improveStat.innerText = 'Held-out MAE tied';
          improveStat.style.color = '#94A3B8';
        } else {
          improveStat.innerText = `Held-out MAE: regression ${alternativeMae.toLocaleString()}, lag-1 ${baselineMae.toLocaleString()}`;
          improveStat.style.color = '#FCA5A5';
        }
      } else {
        improveStat.innerText = 'Held-out MAE comparison unavailable';
      }
    }

    // Render Evaluation Chart
    if (forecast.recent_series_plot) {
      Charts.renderForecastEvaluation('forecastEvalChart', forecast.recent_series_plot, comp.alternative_model?.name || 'Poisson regression');
    }

    // Render Historical Daily Time Series Tab
    if (forecast.recent_series_plot) {
      // Re-map for the main time series bar chart
      const tsData = forecast.recent_series_plot.map(d => ({
        date: d.date,
        daily_detection_count: d.actual_count
      }));
      Charts.renderTimeSeries('timeSeriesChart', tsData, forecast.geographic_unit?.name);
    }
  },

  async loadFireImageStatus() {
    const status = document.getElementById('fireImageStatus');
    if (!status) return;
    const response = await API.getFireImageStatus();
    status.innerText = response?.message || 'Image review service is unavailable.';
  },

  async reviewFireImage() {
    const input = document.getElementById('fireImageInput');
    const result = document.getElementById('fireImageStatus');
    const file = input?.files?.[0];
    if (!result) return;
    if (!file) {
      result.innerText = 'Choose an image first.';
      return;
    }
    result.innerText = 'Reviewing image...';
    const response = await API.reviewFireImage(file);
    if (!response || response.error) {
      result.innerText = response?.error || 'Image review failed.';
      return;
    }
    const scores = Object.entries(response.class_scores || {})
      .map(([name, score]) => `${name}: ${(score * 100).toFixed(1)}%`).join(' · ');
    result.innerText = `${response.label} — model score ${(response.score * 100).toFixed(1)}%. ${scores}. ${response.note}`;
  },

  populateHotspotsTable(records) {
    if (records) this.rawHotspots = records;
    this.renderRankedTriageTable();
  },

  renderRankedTriageTable() {
    const tbody = document.getElementById('hotspotsTableBody');
    const countBadge = document.getElementById('tableCountBadge');
    if (!tbody) return;

    if (!this.rawHotspots || this.rawHotspots.length === 0) {
      tbody.innerHTML = `<tr><td colspan="11" class="loading-td">No satellite detections available.</td></tr>`;
      if (countBadge) countBadge.innerText = '0 records';
      return;
    }

    let list = [...this.rawHotspots];

    // Priority filter (ALL, HIGH, MEDIUM, LOW)
    if (this.triageFilters.priority && this.triageFilters.priority !== 'ALL') {
      list = list.filter(r => r.triage_tier === this.triageFilters.priority);
    }

    // Only multi-detection clusters (repeats > 0)
    if (this.triageFilters.onlyRepeats) {
      list = list.filter(r => (r.repeat_count || 0) > 0);
    }

    // Search query filter
    if (this.triageFilters.search && this.triageFilters.search.trim().length > 0) {
      const q = this.triageFilters.search.trim().toLowerCase();
      list = list.filter(r => {
        return (
          (r.satellite && r.satellite.toLowerCase().includes(q)) ||
          (r.instrument && r.instrument.toLowerCase().includes(q)) ||
          (r.acq_date && r.acq_date.toLowerCase().includes(q)) ||
          (r.triage_explanation && r.triage_explanation.toLowerCase().includes(q)) ||
          String(r.latitude).includes(q) ||
          String(r.longitude).includes(q)
        );
      });
    }

    // Sorting
    if (this.triageFilters.sort === 'frp') {
      list.sort((a, b) => (b.frp_mw || 0) - (a.frp_mw || 0));
    } else if (this.triageFilters.sort === 'recency') {
      list.sort((a, b) => (a.observation_age_hours || 0) - (b.observation_age_hours || 0));
    } else if (this.triageFilters.sort === 'repeats') {
      list.sort((a, b) => (b.repeat_count || 0) - (a.repeat_count || 0));
    } else {
      // Default: triage rank (composite score)
      list.sort((a, b) => (a.triage_rank || 0) - (b.triage_rank || 0));
    }

    if (countBadge) {
      countBadge.innerText = `${list.length.toLocaleString()} of ${this.rawHotspots.length.toLocaleString()} ranked detections`;
    }

    if (list.length === 0) {
      tbody.innerHTML = `<tr><td colspan="11" class="loading-td">No satellite observations match current triage filters.</td></tr>`;
      return;
    }

    // Render top 120 rows for high responsiveness
    const slice = list.slice(0, 120);
    let html = '';
    slice.forEach(r => {
      const tier = (r.triage_tier || 'LOW').toLowerCase();
      const priorityLabel = r.triage_priority || 'Low review priority';
      const ageHours = r.observation_age_hours !== undefined ? r.observation_age_hours : 0;
      const ageStr = ageHours <= 1.0 ? '<1h ago' : `${ageHours.toFixed(1)}h ago`;
      const repeats = r.repeat_count || 0;
      const explanation = r.triage_explanation || 'Satellite thermal observation.';

      html += `
        <tr class="triage-row triage-${tier}">
          <td>
            <div class="rank-badge ${r.triage_rank <= 3 ? 'rank-top' : ''}">#${r.triage_rank}</div>
          </td>
          <td>
            <span class="triage-priority-pill ${tier}">
              <span class="pill-dot"></span> ${priorityLabel}
            </span>
          </td>
          <td>
            <div class="triage-score-cell">
              <span class="score-number">${r.triage_score !== undefined ? r.triage_score : '--'}</span>
              <div class="mini-score-bar">
                <div class="mini-score-fill ${tier}" style="width: ${r.triage_score || 0}%"></div>
              </div>
            </div>
          </td>
          <td>
            <div class="triage-explanation-wrapper">
              <div class="explanation-main-text">
                <strong>${explanation}</strong>
              </div>
              <div class="triage-driver-chips">
                <span class="driver-chip chip-time" title="Observation Recency">⚡ ${ageStr}</span>
                <span class="driver-chip chip-frp" title="Fire Radiative Power">🔥 ${r.frp_mw || 0} MW</span>
                <span class="driver-chip chip-repeat ${repeats > 0 ? 'active' : ''}" title="Repeat Detections in 2km vicinity">🔁 ${repeats} repeat${repeats === 1 ? '' : 's'}</span>
                <span class="driver-chip chip-conf" title="Sensor Confidence">✓ ${r.confidence_norm} conf</span>
              </div>
            </div>
          </td>
          <td>
            <div class="time-primary"><strong>${r.acq_time}</strong> <span class="text-dim">UTC</span></div>
            <div class="time-secondary text-dim">${ageStr} • ${r.acq_date}</div>
          </td>
          <td>
            <strong class="text-amber">${r.frp_mw !== undefined ? r.frp_mw.toFixed(1) : '--'}</strong>
            <span class="text-dim"> MW</span>
          </td>
          <td>
            <span class="repeat-count-tag ${repeats >= 3 ? 'high-rep' : repeats >= 1 ? 'cluster-rep' : 'isolated-rep'}">
              ${repeats > 0 ? `${repeats} in 2km` : '0 (isolated)'}
            </span>
          </td>
          <td>
            <span class="conf-badge conf-${r.confidence_norm}">
              ${(r.confidence_norm || 'NOMINAL').toUpperCase()}
            </span>
          </td>
          <td>
            <div class="sat-name"><strong>${r.satellite}</strong></div>
            <div class="sat-sub text-dim">${r.instrument} (${r.daynight})</div>
          </td>
          <td>
            <span class="coords-mono">${r.latitude.toFixed(4)}°, ${r.longitude.toFixed(4)}°</span>
          </td>
          <td>
            <button class="btn-sm btn-inspect-triage" onclick="App.inspectAndFocusDetection('${r.id}')" title="Inspect on map and assess weather">
              Inspect
            </button>
          </td>
        </tr>
      `;
    });

    tbody.innerHTML = html;
  },

  inspectAndFocusDetection(id) {
    const r = this.rawHotspots.find(x => x.id === id);
    if (!r) return;

    MapController.focusHotspot(r.latitude, r.longitude, r);
    this.handleLocationClick(r.latitude, r.longitude);

    const mapCard = document.querySelector('.map-card');
    if (mapCard) {
      mapCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  },

  async handleSearch(query) {
    const dropdown = document.getElementById('searchResultsDropdown');
    if (!dropdown) return;

    if (!query || query.trim().length < 2) {
      dropdown.style.display = 'none';
      return;
    }

    // Check if user entered raw coordinates e.g. "52.52, 13.41" or "-14.23, -51.92"
    const coordMatch = query.match(/^(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)$/);
    if (coordMatch) {
      const lat = parseFloat(coordMatch[1]);
      const lon = parseFloat(coordMatch[2]);
      if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
        dropdown.innerHTML = `
          <div class="search-result-item" onclick="App.selectSearchResult(${lat}, ${lon}, 'Coordinates: ${lat.toFixed(4)}°, ${lon.toFixed(4)}°')">
            <div class="search-res-title">Direct Geographic Coordinate</div>
            <div class="search-res-coords">Latitude: ${lat.toFixed(4)}°, Longitude: ${lon.toFixed(4)}°</div>
          </div>
        `;
        dropdown.style.display = 'block';
        return;
      }
    }

    // Otherwise forward geocode with Nominatim
    const results = await API.searchPlaces(query);
    if (!results || results.length === 0) {
      dropdown.innerHTML = `<div class="search-result-item" style="color: var(--text-dim);">No locations found matching "${query}"</div>`;
      dropdown.style.display = 'block';
      return;
    }

    let itemsHtml = '';
    results.forEach(item => {
      const nameEscaped = item.display_name.replace(/'/g, "\\'");
      itemsHtml += `
        <div class="search-result-item" onclick="App.selectSearchResult(${item.latitude}, ${item.longitude}, '${nameEscaped}')">
          <div class="search-res-title">${item.display_name}</div>
          <div class="search-res-coords">${item.latitude.toFixed(4)}°, ${item.longitude.toFixed(4)}°</div>
        </div>
      `;
    });

    dropdown.innerHTML = itemsHtml;
    dropdown.style.display = 'block';
  },

  handleSearchSubmit(query) {
    const coordMatch = query.match(/^(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)$/);
    if (coordMatch) {
      const lat = parseFloat(coordMatch[1]);
      const lon = parseFloat(coordMatch[2]);
      this.selectSearchResult(lat, lon, `Coordinates: ${lat.toFixed(4)}°, ${lon.toFixed(4)}°`);
    } else {
      const firstResult = document.querySelector('.search-result-item');
      if (firstResult) firstResult.click();
    }
  },

  selectSearchResult(lat, lon, name) {
    const dropdown = document.getElementById('searchResultsDropdown');
    const searchInput = document.getElementById('globalSearchInput');
    if (dropdown) dropdown.style.display = 'none';
    if (searchInput) searchInput.value = name;

    MapController.panToLocation(lat, lon, 7);
    this.handleLocationClick(lat, lon);
  },

  showLoadingFreshness(msg) {
    const el = document.getElementById('freshnessText');
    if (el) el.innerText = msg;
  },

  showFreshnessSynced() {
    const el = document.getElementById('freshnessText');
    if (el) {
      const now = new Date();
      const timeStr = now.toISOString().substring(11, 16);
      el.innerText = `FIRMS Live NRT: Synced (${timeStr} UTC)`;
    }
  }
};

// Auto-boot on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
