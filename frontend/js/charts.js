/**
 * Neurora Charts Module
 * Renders interactive Chart.js visualizations for time series, model evaluation, and weather.
 */

const Charts = {
  timeSeriesChart: null,
  forecastEvalChart: null,
  weatherHourlyChart: null,

  init() {
    // Set Chart.js global dark theme defaults
    Chart.defaults.color = '#94A3B8';
    Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.06)';
    Chart.defaults.font.family = "'Inter', sans-serif";
  },

  renderTimeSeries(canvasId, seriesData, regionName = 'Worldwide') {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    if (this.timeSeriesChart) {
      this.timeSeriesChart.destroy();
    }

    if (!seriesData || seriesData.length === 0) return;

    const labels = seriesData.map(d => d.date);
    const counts = seriesData.map(d => d.daily_detection_count);
    
    // Compute 7-day rolling mean
    const rolling7 = counts.map((val, idx, arr) => {
      const start = Math.max(0, idx - 6);
      const slice = arr.slice(start, idx + 1).filter(v => v !== null && v !== undefined);
      if (slice.length === 0) return null;
      const sum = slice.reduce((a, b) => a + b, 0);
      return Math.round(sum / slice.length);
    });

    this.timeSeriesChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            type: 'line',
            label: '7-Day Rolling Baseline',
            data: rolling7,
            borderColor: '#38BDF8',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.2,
            order: 1
          },
          {
            type: 'bar',
            label: 'Daily Satellite Detections',
            data: counts,
            backgroundColor: 'rgba(245, 158, 11, 0.65)',
            hoverBackgroundColor: '#F59E0B',
            borderRadius: 2,
            order: 2
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false
        },
        plugins: {
          legend: {
            position: 'top',
            labels: { boxWidth: 12, font: { size: 11 } }
          },
          tooltip: {
            callbacks: {
              label: (ctx) => ` ${ctx.dataset.label}: ${ctx.raw ? ctx.raw.toLocaleString() : 'Missing'} detections`
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { maxTicksLimit: 12, font: { size: 10 } }
          },
          y: {
            beginAtZero: true,
            ticks: {
              callback: (val) => val >= 1000 ? `${(val / 1000).toFixed(0)}k` : val,
              font: { size: 10 }
            }
          }
        }
      }
    });
  },

  renderForecastEvaluation(canvasId, plotData, alternativeName = 'Poisson regression') {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    if (this.forecastEvalChart) {
      this.forecastEvalChart.destroy();
    }

    if (!plotData || plotData.length === 0) return;

    const labels = plotData.map(d => d.date);
    const actuals = plotData.map(d => d.actual_count);
    const baseline = plotData.map(d => d.baseline_pred);
    const alt = plotData.map(d => d.alt_pred);

    this.forecastEvalChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Observed Actuals',
            data: actuals,
            borderColor: '#F8FAFC',
            backgroundColor: '#F8FAFC',
            borderWidth: 2,
            pointRadius: 3,
            tension: 0.1
          },
          {
            label: 'Baseline Lag-1',
            data: baseline,
            borderColor: '#94A3B8',
            borderWidth: 1.5,
            borderDash: [4, 4],
            pointRadius: 0,
            tension: 0.1
          },
          {
            label: alternativeName,
            data: alt,
            borderColor: '#10B981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            fill: true,
            borderWidth: 2,
            pointRadius: 2,
            tension: 0.2
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false
        },
        plugins: {
          legend: {
            position: 'top',
            labels: { boxWidth: 12, font: { size: 11 } }
          },
          tooltip: {
            callbacks: {
              label: (ctx) => ` ${ctx.dataset.label}: ${ctx.raw ? ctx.raw.toLocaleString() : '--'} detections`
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { maxTicksLimit: 10, font: { size: 10 } }
          },
          y: {
            beginAtZero: false,
            ticks: {
              callback: (val) => val >= 1000 ? `${(val / 1000).toFixed(0)}k` : val,
              font: { size: 10 }
            }
          }
        }
      }
    });
  },

  renderHourlyWeather(canvasId, hourlyData) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    if (this.weatherHourlyChart) {
      this.weatherHourlyChart.destroy();
    }

    if (!hourlyData || !hourlyData.times || hourlyData.times.length === 0) return;

    // Slice 24 hours
    const times = hourlyData.times.slice(0, 24).map(t => t.split('T')[1].substring(0, 5));
    const temps = hourlyData.temperatures_c.slice(0, 24);
    const rhs = hourlyData.relative_humidity_pct.slice(0, 24);

    this.weatherHourlyChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: times,
        datasets: [
          {
            label: 'Temp (°C)',
            data: temps,
            borderColor: '#EF4444',
            borderWidth: 2,
            pointRadius: 0,
            yAxisID: 'yTemp',
            tension: 0.3
          },
          {
            label: 'Humidity (%)',
            data: rhs,
            borderColor: '#38BDF8',
            borderWidth: 1.5,
            borderDash: [3, 3],
            pointRadius: 0,
            yAxisID: 'yRh',
            tension: 0.3
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'top',
            labels: { boxWidth: 10, font: { size: 10 } }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { maxTicksLimit: 6, font: { size: 9 } }
          },
          yTemp: {
            type: 'linear',
            position: 'left',
            ticks: { font: { size: 9 } },
            grid: { color: 'rgba(255, 255, 255, 0.04)' }
          },
          yRh: {
            type: 'linear',
            position: 'right',
            min: 0,
            max: 100,
            grid: { display: false },
            ticks: { font: { size: 9 } }
          }
        }
      }
    });
  }
};
