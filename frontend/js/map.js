/**
 * Neurora Map Controller
 * Global Leaflet Map with multi-satellite layers, clustering, heatmap, risk overlays,
 * and coordinate click inspection.
 */

const MapController = {
  map: null,
  markersClusterGroup: null,
  heatmapLayer: null,
  riskLayerGroup: null,
  clickPinMarker: null,

  // Current active data & filters
  // Current active data & filters
  hotspotsData: [],
  currentSatelliteFilter: 'ALL',
  currentConfidenceFilter: '',
  currentMinFrp: 0,
  showCluster: false,
  showHeatmap: true,
  showRiskLayer: true,

  // Selected Location Callback
  onLocationSelected: null,

  basemapLayers: {},
  currentBasemap: 'dark',

  init(containerId = 'map', onLocSelect = null) {
    this.onLocationSelected = onLocSelect;

    // Initialize Leaflet map with global view & date line wrapping
    this.map = L.map(containerId, {
      center: [20.0, 0.0],
      zoom: 2,
      minZoom: 2,
      maxZoom: 20,
      worldCopyJump: true
    });

    // 1. Real Dark Gray Canvas (Official Esri GIS Standard Dark Canvas)
    const esriDarkBase = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
      maxZoom: 16
    });
    const esriDarkRef = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Reference &copy; Esri',
      maxZoom: 16
    });
    this.basemapLayers['dark'] = L.layerGroup([esriDarkBase, esriDarkRef]);

    // 2. NASA Black Marble (Earth at Night Satellite Radiance - VIIRS Day/Night Band)
    const nasaNight = L.tileLayer('https://map1.vis.earthdata.nasa.gov/wmts-webmerc/VIIRS_CityLights_2012/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpg', {
      attribution: 'Imagery &copy; NASA Earthdata / GIBS &mdash; Suomi-NPP VIIRS Day/Night Band',
      maxZoom: 8
    });
    const nightRef = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Boundaries &copy; Esri',
      maxZoom: 19
    });
    this.basemapLayers['night'] = L.layerGroup([nasaNight, nightRef]);

    // 3. Real World Satellite Imagery - Esri High-Resolution Satellite
    const satBase = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
      maxZoom: 19
    });
    const satRef = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Boundaries &copy; Esri',
      maxZoom: 19
    });
    this.basemapLayers['satellite'] = L.layerGroup([satBase, satRef]);

    // 4. OpenStreetMap Topographic / Terrain
    this.basemapLayers['terrain'] = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19
    });

    // Activate Dark Canvas basemap by default
    this.basemapLayers['dark'].addTo(this.map);
    const mapEl = document.getElementById(containerId);
    if (mapEl) mapEl.classList.add('dark-canvas-active');

    // Initialize Layers (disable spiderfy fragmentation)
    this.markersClusterGroup = L.markerClusterGroup({
      chunkedLoading: true,
      maxClusterRadius: 40,
      spiderfyOnMaxZoom: false,
      showCoverageOnHover: false,
      zoomToBoundsOnClick: true,
      disableClusteringAtZoom: 12,
      iconCreateFunction: (cluster) => {
        const count = cluster.getChildCount();
        let cClass = 'marker-cluster-small';
        if (count > 200) cClass = 'marker-cluster-large';
        else if (count > 40) cClass = 'marker-cluster-medium';

        return new L.DivIcon({
          html: `<div><span>${count >= 1000 ? (count / 1000).toFixed(1) + 'k' : count}</span></div>`,
          className: `marker-cluster ${cClass}`,
          iconSize: new L.Point(40, 40)
        });
      }
    });

    this.riskLayerGroup = L.layerGroup();

    if (this.showCluster) {
      this.map.addLayer(this.markersClusterGroup);
    }
    if (this.showRiskLayer) {
      this.map.addLayer(this.riskLayerGroup);
    }

    // Zoom listener for dynamic smooth expanding heat canopy
    this.map.on('zoomend', () => {
      this.updateHeatmapForZoom();
    });

    // Map Event Listeners
    this.map.on('mousemove', (e) => {
      const lat = e.latlng.lat.toFixed(4);
      const lon = e.latlng.lng.toFixed(4);
      const coordsEl = document.getElementById('mapHoverCoords');
      if (coordsEl) coordsEl.innerText = `Lat: ${lat}°, Lon: ${lon}°`;
    });

    this.map.on('click', (e) => {
      this.handleMapClick(e.latlng.lat, e.latlng.lng);
    });

    // Populate default regional risk zones
    this.renderRegionalRiskZones();
  },

  updateHeatmapForZoom() {
    if (!this.heatmapLayer || !this.map) return;
    const zoom = this.map.getZoom();
    // Dynamically expand thermal canopy radius as user zooms in:
    // Zoom 2: 18px radius, 14px blur
    // Zoom 5: 28px radius, 22px blur
    // Zoom 8: 42px radius, 32px blur
    // Zoom 11+: 60px radius, 44px blur
    const radius = Math.min(68, Math.max(16, Math.round(14 + Math.pow(zoom, 1.35) * 1.6)));
    const blur = Math.min(48, Math.max(12, Math.round(radius * 0.72)));
    this.heatmapLayer.setOptions({
      radius: radius,
      blur: blur,
      maxZoom: 16
    });
  },

  setHotspots(hotspots) {
    this.hotspotsData = hotspots || [];
    this.applyFiltersAndRender();
  },

  applyFiltersAndRender() {
    if (!this.map) return;

    // Filter points based on state
    let filtered = this.hotspotsData.filter(pt => {
      // Satellite filter
      if (this.currentSatelliteFilter !== 'ALL') {
        const satUpper = pt.satellite.toUpperCase();
        if (this.currentSatelliteFilter === 'NOAA20' && !satUpper.includes('NOAA-20')) return false;
        if (this.currentSatelliteFilter === 'NOAA21' && !satUpper.includes('NOAA-21')) return false;
        if (this.currentSatelliteFilter === 'SNPP' && !satUpper.includes('SUOMI')) return false;
        if (this.currentSatelliteFilter === 'MODIS' && !satUpper.includes('MODIS') && !satUpper.includes('TERRA') && !satUpper.includes('AQUA')) return false;
      }

      // Confidence filter
      if (this.currentConfidenceFilter) {
        if (this.currentConfidenceFilter === 'high' && pt.confidence_norm !== 'high') return false;
        if (this.currentConfidenceFilter === 'nominal' && pt.confidence_norm === 'low') return false;
      }

      // Min FRP filter
      if (this.currentMinFrp > 0) {
        if ((pt.frp_mw || 0) < this.currentMinFrp) return false;
      }

      return true;
    });

    // Clear previous markers
    this.markersClusterGroup.clearLayers();

    // Clear heatmap if active
    if (this.heatmapLayer) {
      this.map.removeLayer(this.heatmapLayer);
      this.heatmapLayer = null;
    }

    const markers = [];
    const heatPoints = [];

    filtered.forEach(pt => {
      const lat = pt.latitude;
      const lon = pt.longitude;
      const color = this.getSatelliteColor(pt.satellite);

      // FRP weighted intensity for vibrant thermal canopy
      const intensity = Math.min(1.0, Math.max(0.25, (pt.frp_mw || 10) / 40.0));
      heatPoints.push([lat, lon, intensity]);

      // Only build individual circle markers if pinpoint clustering is enabled
      if (this.showCluster) {
        const marker = L.circleMarker([lat, lon], {
          radius: Math.max(3.5, Math.min(8.0, 3.5 + (pt.frp_mw || 0) / 40.0)),
          fillColor: color,
          color: '#FFFFFF',
          weight: 1,
          opacity: 0.9,
          fillOpacity: 0.85
        });

        // Bind rich popup with UTC & Local Time
        const popupHtml = this.createPopupHtml(pt);
        marker.bindPopup(popupHtml, { maxWidth: 300 });

        markers.push(marker);
      }
    });

    // 1. Render Heat Shade (Expanding Continuous Canopy without breaking into pieces)
    if (this.showHeatmap && heatPoints.length > 0 && typeof L.heatLayer === 'function') {
      const currentZoom = this.map.getZoom();
      const radius = Math.min(68, Math.max(16, Math.round(14 + Math.pow(currentZoom, 1.35) * 1.6)));
      const blur = Math.min(48, Math.max(12, Math.round(radius * 0.72)));

      this.heatmapLayer = L.heatLayer(heatPoints, {
        radius: radius,
        blur: blur,
        maxZoom: 16,
        minOpacity: 0.28,
        gradient: {
          0.15: '#38BDF8', // Cyan ambient warm perimeter
          0.35: '#F59E0B', // Amber active flame edge
          0.60: '#F97316', // Orange burning front
          0.82: '#EF4444', // Red high intensity core
          0.98: '#FFFFFF'  // White-hot peak radiation
        }
      }).addTo(this.map);
    }

    // 2. Render Pinpoint Markers if toggled
    if (this.showCluster) {
      this.markersClusterGroup.addLayers(markers);
      if (!this.map.hasLayer(this.markersClusterGroup)) {
        this.map.addLayer(this.markersClusterGroup);
      }
    } else {
      if (this.map.hasLayer(this.markersClusterGroup)) {
        this.map.removeLayer(this.markersClusterGroup);
      }
    }
  },

  getSatelliteColor(satelliteStr) {
    const s = String(satelliteStr).toUpperCase();
    if (s.includes('NOAA-20')) return '#06B6D4'; // Cyan
    if (s.includes('NOAA-21')) return '#A855F7'; // Purple
    if (s.includes('SUOMI') || s.includes('SNPP')) return '#F59E0B'; // Gold / Amber
    if (s.includes('MODIS') || s.includes('TERRA') || s.includes('AQUA')) return '#F43F5E'; // Crimson
    return '#E2E8F0';
  },

  createPopupHtml(pt) {
    const color = this.getSatelliteColor(pt.satellite);
    
    // Estimate local time from longitude offset
    let localTimeStr = '--:--';
    try {
      const parts = pt.acq_time.split(':');
      if (parts.length === 2) {
        const utcHours = parseInt(parts[0], 10);
        const utcMins = parseInt(parts[1], 10);
        const lonOffsetHours = pt.longitude / 15.0; // 15 degrees per hour
        let localH = (utcHours + lonOffsetHours) % 24;
        if (localH < 0) localH += 24;
        const hr = Math.floor(localH).toString().padStart(2, '0');
        const mn = utcMins.toString().padStart(2, '0');
        const sign = lonOffsetHours >= 0 ? '+' : '';
        localTimeStr = `${hr}:${mn} (UTC${sign}${Math.round(lonOffsetHours)} approx)`;
      }
    } catch (e) {
      localTimeStr = pt.acq_time;
    }

    const rankBadge = pt.triage_rank ? `<span class="popup-rank-badge">Rank #${pt.triage_rank}</span>` : '';
    const priorityLabel = pt.triage_priority || 'Low review priority';
    const priorityColor = pt.triage_color || '#10B981';
    const explanationText = pt.triage_explanation || 'Satellite thermal anomaly observation.';
    const repeatsText = pt.repeat_count !== undefined ? `${pt.repeat_count} in 8km radius` : '0 (isolated)';

    return `
      <div class="hotspot-popup-card">
        <div class="popup-header">
          <div class="popup-header-tags">
            ${rankBadge}
            <span class="popup-priority-tag" style="background: ${priorityColor}22; color: ${priorityColor}; border: 1px solid ${priorityColor}55;">
              ${priorityLabel}
            </span>
          </div>
          <span class="popup-time">${pt.acq_date} ${pt.acq_time} UTC</span>
        </div>
        <div class="popup-explanation-bar">
          <strong>${explanationText}</strong>
        </div>
        <div class="popup-place-name">Location: ${pt.latitude.toFixed(4)}°, ${pt.longitude.toFixed(4)}°</div>
        <div class="popup-grid">
          <div class="popup-label">Triage Score:</div>
          <div class="popup-val" style="color: ${priorityColor}; font-weight: 700;">${pt.triage_score || '--'} / 100</div>
          <div class="popup-label">Satellite / Sensor:</div>
          <div class="popup-val" style="color: ${color}; font-weight: 600;">● ${pt.satellite} (${pt.instrument})</div>
          <div class="popup-label">Fire Rad. Power:</div>
          <div class="popup-val text-amber">${pt.frp_mw || '--'} MW</div>
          <div class="popup-label">Repeat Detections:</div>
          <div class="popup-val">${repeatsText}</div>
          <div class="popup-label">Brightness Temp:</div>
          <div class="popup-val">${pt.brightness_k ? `${pt.brightness_k.toFixed(1)} K (${(pt.brightness_k - 273.15).toFixed(1)}°C)` : '--'}</div>
          <div class="popup-label">Confidence:</div>
          <div class="popup-val">${pt.confidence_raw} (${pt.confidence_norm})</div>
          <div class="popup-label">Local Time:</div>
          <div class="popup-val">${localTimeStr}</div>
        </div>
        <button class="popup-btn-analyze" onclick="MapController.focusHotspot(${pt.latitude}, ${pt.longitude})">
          🔍 Inspect Local Meteorology & EFRI
        </button>
      </div>
    `;
  },

  focusHotspot(lat, lon, hotspot = null) {
    if (!this.map) return;
    this.map.flyTo([lat, lon], 8, { duration: 1.0 });
    this.handleMapClick(lat, lon);
    if (hotspot) {
      const popupHtml = this.createPopupHtml(hotspot);
      L.popup({ maxWidth: 320 })
        .setLatLng([lat, lon])
        .setContent(popupHtml)
        .openOn(this.map);
    }
  },

  handleMapClick(lat, lon) {
    if (this.clickPinMarker) {
      this.map.removeLayer(this.clickPinMarker);
    }

    // Add glowing pin
    const pinIcon = L.divIcon({
      className: 'click-pin-icon',
      html: `
        <div style="
          width: 18px;
          height: 18px;
          background: #38BDF8;
          border: 3px solid #FFFFFF;
          border-radius: 50%;
          box-shadow: 0 0 16px #38BDF8, 0 0 24px #06B6D4;
          animation: pulse 1.5s infinite;
        "></div>
      `,
      iconSize: [18, 18],
      iconAnchor: [9, 9]
    });

    this.clickPinMarker = L.marker([lat, lon], { icon: pinIcon }).addTo(this.map);

    if (this.onLocationSelected) {
      this.onLocationSelected(lat, lon);
    }
  },

  panToLocation(lat, lon, zoom = 6) {
    if (!this.map) return;
    this.map.flyTo([lat, lon], zoom, { duration: 1.5 });
    this.handleMapClick(lat, lon);
  },

  resetToWorldView() {
    if (!this.map) return;
    this.map.flyTo([20.0, 0.0], 2, { duration: 1.2 });
  },

  renderRegionalRiskZones() {
    if (!this.riskLayerGroup) return;
    this.riskLayerGroup.clearLayers();

    // Predefined indicative environmental risk monitoring zones
    const zones = [
      { name: "Amazon Basin (Brazil)", lat: -7.5, lon: -56.0, radius: 450000, level: "RED", score: 78, color: "#EF4444" },
      { name: "Cerrado Biome (Brazil)", lat: -14.0, lon: -48.0, radius: 350000, level: "RED", score: 72, color: "#EF4444" },
      { name: "Congo Basin (DRC)", lat: -2.0, lon: 24.0, radius: 420000, level: "ORANGE", score: 58, color: "#F97316" },
      { name: "Sahel Transition Zone", lat: 12.0, lon: 15.0, radius: 500000, level: "ORANGE", score: 52, color: "#F97316" },
      { name: "Northern Territory (Australia)", lat: -18.0, lon: 133.0, radius: 400000, level: "RED", score: 68, color: "#EF4444" },
      { name: "Southern California (USA)", lat: 34.5, lon: -118.5, radius: 250000, level: "ORANGE", score: 61, color: "#F97316" },
      { name: "Iberian Peninsula (Spain/Portugal)", lat: 40.0, lon: -4.0, radius: 300000, level: "GREEN", score: 28, color: "#10B981" },
      { name: "Southeast Asia (Sumatra/Borneo)", lat: -1.0, lon: 110.0, radius: 380000, level: "ORANGE", score: 48, color: "#F97316" }
    ];

    zones.forEach(z => {
      // 1. Outer alert perimeter (smooth broad shade)
      const outerCircle = L.circle([z.lat, z.lon], {
        radius: z.radius,
        color: z.color,
        fillColor: z.color,
        fillOpacity: 0.08,
        weight: 1.2,
        dashArray: '4, 4'
      });

      // 2. Inner core intensity shade (expands smoothly when zooming in)
      const innerCore = L.circle([z.lat, z.lon], {
        radius: Math.round(z.radius * 0.45),
        color: z.color,
        fillColor: z.color,
        fillOpacity: 0.18,
        weight: 1.5
      });

      // 3. Central anchor badge marker (always visible and clickable)
      const badgeIcon = L.divIcon({
        className: 'risk-badge-marker',
        html: `
          <div class="risk-zone-badge" style="border-color: ${z.color}; color: ${z.color};">
            <span class="badge-dot" style="background: ${z.color};"></span>
            <span>${z.level} ${z.score}</span>
          </div>
        `,
        iconSize: [85, 24],
        iconAnchor: [42, 12]
      });
      const badgeMarker = L.marker([z.lat, z.lon], { icon: badgeIcon });

      const tooltipContent = `
        <strong>${z.name}</strong><br/>
        Estimated Risk: <span style="color:${z.color};font-weight:700">${z.level} (${z.score}/100)</span>
      `;

      outerCircle.bindTooltip(tooltipContent, { sticky: true, className: 'risk-tooltip' });
      innerCore.bindTooltip(tooltipContent, { sticky: true, className: 'risk-tooltip' });
      badgeMarker.bindTooltip(tooltipContent, { sticky: true, className: 'risk-tooltip' });

      outerCircle.on('click', () => this.handleMapClick(z.lat, z.lon));
      innerCore.on('click', () => this.handleMapClick(z.lat, z.lon));
      badgeMarker.on('click', () => this.handleMapClick(z.lat, z.lon));

      this.riskLayerGroup.addLayer(outerCircle);
      this.riskLayerGroup.addLayer(innerCore);
      this.riskLayerGroup.addLayer(badgeMarker);
    });
  },

  setBasemap(type) {
    if (!this.basemapLayers[type]) return;
    // Remove all basemaps
    Object.values(this.basemapLayers).forEach(layer => {
      if (this.map.hasLayer(layer)) {
        this.map.removeLayer(layer);
      }
    });
    // Add selected basemap
    const selected = this.basemapLayers[type];
    selected.addTo(this.map);
    if (selected.bringToBack) {
      selected.bringToBack();
    } else if (selected.eachLayer) {
      selected.eachLayer(sub => { if (sub.bringToBack) sub.bringToBack(); });
    }
    this.currentBasemap = type;

    const mapEl = document.getElementById('map');
    if (mapEl) {
      if (type === 'dark' || type === 'night') {
        mapEl.classList.add('dark-canvas-active');
      } else {
        mapEl.classList.remove('dark-canvas-active');
      }
    }
  },

  setSatelliteFilter(sat) {
    this.currentSatelliteFilter = sat;
    this.applyFiltersAndRender();
  },

  setConfidenceFilter(conf) {
    this.currentConfidenceFilter = conf;
    this.applyFiltersAndRender();
  },

  setMinFrp(frp) {
    this.currentMinFrp = frp;
    this.applyFiltersAndRender();
  },

  toggleCluster(enabled) {
    this.showCluster = enabled;
    if (enabled) {
      if (!this.map.hasLayer(this.markersClusterGroup)) {
        this.map.addLayer(this.markersClusterGroup);
      }
    } else {
      if (this.map.hasLayer(this.markersClusterGroup)) {
        this.map.removeLayer(this.markersClusterGroup);
      }
    }
    this.applyFiltersAndRender();
  },

  toggleHeatmap(enabled) {
    this.showHeatmap = enabled;
    this.applyFiltersAndRender();
  },

  toggleRiskLayer(enabled) {
    this.showRiskLayer = enabled;
    if (enabled) {
      if (!this.map.hasLayer(this.riskLayerGroup)) {
        this.map.addLayer(this.riskLayerGroup);
      }
    } else {
      if (this.map.hasLayer(this.riskLayerGroup)) {
        this.map.removeLayer(this.riskLayerGroup);
      }
    }
  }
};
