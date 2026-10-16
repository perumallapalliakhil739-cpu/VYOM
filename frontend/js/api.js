/**
 * Neurora API Client
 * Centralized asynchronous client for backend communication.
 */

const API = {
  baseUrl: '',

  async getHealth() {
    try {
      const res = await fetch(`${this.baseUrl}/api/health`);
      return await res.json();
    } catch (err) {
      console.error('API Error in getHealth:', err);
      return null;
    }
  },

  async getHotspots(params = {}) {
    const query = new URLSearchParams();
    if (params.satellite && params.satellite !== 'ALL') query.append('satellite', params.satellite);
    if (params.confidence) query.append('confidence', params.confidence);
    if (params.min_frp) query.append('min_frp', params.min_frp);
    if (params.limit) query.append('limit', params.limit);
    if (params.refresh) query.append('refresh', 'true');
    if (params.bbox) {
      query.append('min_lat', params.bbox[0]);
      query.append('min_lon', params.bbox[1]);
      query.append('max_lat', params.bbox[2]);
      query.append('max_lon', params.bbox[3]);
    }

    try {
      const res = await fetch(`${this.baseUrl}/api/hotspots?${query.toString()}`);
      return await res.json();
    } catch (err) {
      console.error('API Error in getHotspots:', err);
      return null;
    }
  },

  async getWeather(lat, lon, name = null) {
    const query = new URLSearchParams({ lat, lon });
    if (name) query.append('name', name);

    try {
      const res = await fetch(`${this.baseUrl}/api/weather?${query.toString()}`);
      return await res.json();
    } catch (err) {
      console.error('API Error in getWeather:', err);
      return null;
    }
  },

  async getRisk(lat, lon, name = null, radiusKm = 50) {
    const query = new URLSearchParams({ lat, lon, radius_km: radiusKm });
    if (name) query.append('name', name);

    try {
      const res = await fetch(`${this.baseUrl}/api/risk?${query.toString()}`);
      return await res.json();
    } catch (err) {
      console.error('API Error in getRisk:', err);
      return null;
    }
  },

  async getForecast(geoId = 'GLOBAL') {
    const query = new URLSearchParams({ geo_id: geoId });
    try {
      const res = await fetch(`${this.baseUrl}/api/forecast?${query.toString()}`);
      return await res.json();
    } catch (err) {
      console.error('API Error in getForecast:', err);
      return null;
    }
  },

  async getRegions() {
    try {
      const res = await fetch(`${this.baseUrl}/api/regions`);
      return await res.json();
    } catch (err) {
      console.error('API Error in getRegions:', err);
      return [];
    }
  },

  async searchPlaces(queryText) {
    if (!queryText || queryText.trim().length < 2) return [];
    try {
      const res = await fetch(`${this.baseUrl}/api/geocode/search?q=${encodeURIComponent(queryText)}`);
      return await res.json();
    } catch (err) {
      console.error('API Error in searchPlaces:', err);
      return [];
    }
  },

  async reverseGeocode(lat, lon) {
    try {
      const res = await fetch(`${this.baseUrl}/api/geocode/reverse?lat=${lat}&lon=${lon}`);
      return await res.json();
    } catch (err) {
      console.error('API Error in reverseGeocode:', err);
      return { resolved: false, display_name: `Coordinates ${lat.toFixed(4)}°, ${lon.toFixed(4)}°` };
    }
  }
};
