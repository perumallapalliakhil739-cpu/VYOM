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
  hotspotsData: [],
  currentSatelliteFilter: 'ALL',
  currentConfidenceFilter: '',
  currentMinFrp: 0,
  showCluster: true,
  showHeatmap: false,
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


    // 5. OpenStreetMap Topographic / Terrain
    this.basemapLayers['terrain'] = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19
    });

    // Activate Dark Canvas basemap by default
    this.basemapLayers['dark'].addTo(this.map);
    const mapEl = document.getElementById(containerId);
    if (mapEl) mapEl.classList.add('dark-canvas-active');

    // Initialize Layers
    this.markersClusterGroup = L.markerClusterGroup({
      chunkedLoading: true,
      maxClusterRadius: 45,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      zoomToBoundsOnClick: true,
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

    // 1. Render Cluster / Individual Markers
    const markers = [];
    const heatPoints = [];

    filtered.forEach(pt => {
      const lat = pt.latitude;
      const lon = pt.longitude;
      const color = this.getSatelliteColor(pt.satellite);

      heatPoints.push([lat, lon, Math.min(1.0, (pt.frp_mw || 5) / 50.0)]);

      // Custom circle marker
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
    });

    this.markersClusterGroup.addLayers(markers);

    // 2. Render Heatmap if toggled
    if (this.showHeatmap && heatPoints.length > 0 && typeof L.heatLayer === 'function') {
      this.heatmapLayer = L.heatLayer(heatPoints, {
        radius: 20,
        blur: 15,
        maxZoom: 10,
        gradient: {
          0.2: '#06B6D4',
          0.4: '#38BDF8',
          0.6: '#F59E0B',
          0.8: '#F97316',
          1.0: '#EF4444'
        }
      }).addTo(this.map);
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

    return `
      <div class="hotspot-popup-card">
        <div class="popup-header">
          <span class="popup-sat-tag" style="color: ${color}">● ${pt.satellite}</span>
          <span class="popup-time">${pt.acq_date} ${pt.acq_time} UTC</span>
        </div>
        <div class="popup-place-name">Location: ${pt.latitude.toFixed(4)}°, ${pt.longitude.toFixed(4)}°</div>
        <div class="popup-grid">
          <div class="popup-label">Instrument:</div>
          <div class="popup-val">${pt.instrument} (${pt.daynight})</div>
          <div class="popup-label">Fire Rad. Power:</div>
          <div class="popup-val text-amber">${pt.frp_mw || '--'} MW</div>
          <div class="popup-label">Brightness Temp:</div>
          <div class="popup-val">${pt.brightness_k ? `${pt.brightness_k.toFixed(1)} K (${(pt.brightness_k - 273.15).toFixed(1)}°C)` : '--'}</div>
          <div class="popup-label">Confidence:</div>
          <div class="popup-val">${pt.confidence_raw} (${pt.confidence_norm})</div>
          <div class="popup-label">Local Time:</div>
          <div class="popup-val">${localTimeStr}</div>
          <div class="popup-label">Product:</div>
          <div class="popup-val">${pt.product || 'NRT'}</div>
        </div>
        <button class="popup-btn-analyze" onclick="MapController.handleMapClick(${pt.latitude}, ${pt.longitude})">
          🔍 Analyze Environmental Risk & Weather
        </button>
      </div>
    `;
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
      const circle = L.circle([z.lat, z.lon], {
        radius: z.radius,
        color: z.color,
        fillColor: z.color,
        fillOpacity: 0.12,
        weight: 1.5,
        dashArray: '4, 4'
      });

      circle.bindTooltip(`
        <strong>${z.name}</strong><br/>
        Estimated Risk: <span style="color:${z.color};font-weight:700">${z.level} (${z.score}/100)</span>
      `, { sticky: true, className: 'risk-tooltip' });

      circle.on('click', () => {
        this.handleMapClick(z.lat, z.lon);
      });

      this.riskLayerGroup.addLayer(circle);
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
