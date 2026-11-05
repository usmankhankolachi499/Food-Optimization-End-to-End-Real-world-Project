/* Chart.js dashboards. Degrades gracefully when the CDN is unavailable. */
(function () {
  function readJSON(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  function unavailable() {
    document.querySelectorAll('.chart-box').forEach(function (box) { box.classList.add('chart-unavailable'); });
  }

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
    if (typeof Chart === 'undefined') { unavailable(); return; }

    Chart.defaults.font.family = '"Inter", system-ui, sans-serif';
    Chart.defaults.font.size = 11;
    Chart.defaults.color = '#6b7486';
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 8;
    Chart.defaults.plugins.legend.labels.padding = 16;
    const grid = { color: '#eef2ed', drawBorder: false };

    // -------------------------------------------------- analytics page
    const bundle = readJSON('analyticsData');
    if (bundle) {
      const trendEl = document.getElementById('ordersTrendChart');
      if (trendEl) {
        new Chart(trendEl, {
          type: 'line',
          data: {
            labels: bundle.trend.labels,
            datasets: [
              {
                label: 'Orders',
                data: bundle.trend.orders,
                borderColor: '#d4af6a',
                backgroundColor: 'rgba(212,175,106,.14)',
                fill: true,
                tension: .38,
                borderWidth: 2.5,
                pointRadius: 2.5,
                pointBackgroundColor: '#d4af6a'
              },
              {
                label: 'Delivered',
                data: bundle.trend.delivered,
                borderColor: '#1d2941',
                backgroundColor: 'rgba(31,157,104,.08)',
                fill: true,
                tension: .38,
                borderWidth: 2,
                pointRadius: 2,
                pointBackgroundColor: '#1d2941'
              }
            ]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { position: 'bottom' } },
            scales: {
              x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
              y: { beginAtZero: true, grid: grid, ticks: { precision: 0 } }
            }
          }
        });
      }

      const revenueEl = document.getElementById('revenueChart');
      if (revenueEl) {
        new Chart(revenueEl, {
          type: 'bar',
          data: {
            labels: bundle.trend.labels,
            datasets: [{
              label: 'Revenue (₹)',
              data: bundle.trend.revenue,
              backgroundColor: 'rgba(21,30,45,.78)',
              borderRadius: 7,
              maxBarThickness: 26
            }]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid: { display: false }, ticks: { autoSkip: true, maxTicksLimit: 8 } },
              y: { beginAtZero: true, grid: grid, ticks: { callback: function (v) { return '₹' + v; } } }
            }
          }
        });
      }

      const peakEl = document.getElementById('peakHoursChart');
      if (peakEl) {
        const max = Math.max.apply(null, bundle.peak.values.concat([1]));
        new Chart(peakEl, {
          type: 'bar',
          data: {
            labels: bundle.peak.labels,
            datasets: [{
              label: 'Orders',
              data: bundle.peak.values,
              backgroundColor: bundle.peak.values.map(function (value) {
                return value === max ? '#d4af6a' : 'rgba(212,175,106,.28)';
              }),
              borderRadius: 5,
              maxBarThickness: 16
            }]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid: { display: false }, ticks: { autoSkip: true, maxTicksLimit: 12 } },
              y: { beginAtZero: true, grid: grid, ticks: { precision: 0 } }
            }
          }
        });
      }

      const statusEl = document.getElementById('statusChart');
      if (statusEl) {
        new Chart(statusEl, {
          type: 'doughnut',
          data: {
            labels: bundle.statuses.labels,
            datasets: [{
              data: bundle.statuses.values,
              backgroundColor: bundle.statuses.colors,
              borderWidth: 3,
              borderColor: '#fff',
              hoverOffset: 6
            }]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            cutout: '68%',
            plugins: { legend: { position: 'bottom' } }
          }
        });
      }

      const restaurantsEl = document.getElementById('restaurantsChart');
      if (restaurantsEl) {
        const rows = bundle.top_restaurants || [];
        new Chart(restaurantsEl, {
          type: 'bar',
          data: {
            labels: rows.map(function (row) { return row.restaurant.name; }),
            datasets: [{
              label: 'Orders',
              data: rows.map(function (row) { return row.orders; }),
              backgroundColor: 'rgba(212,175,106,.72)',
              borderRadius: 7,
              maxBarThickness: 24
            }]
          },
          options: {
            indexAxis: 'y',
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { beginAtZero: true, grid: grid, ticks: { precision: 0 } },
              y: { grid: { display: false } }
            }
          }
        });
      }
    }

    // -------------------------------------------------- admin dashboard
    const trend = readJSON('dashboardTrendData');
    const miniEl = document.getElementById('miniTrendChart');
    if (trend && miniEl) {
      new Chart(miniEl, {
        type: 'line',
        data: {
          labels: trend.labels,
          datasets: [{
            data: trend.orders,
            borderColor: '#d4af6a',
            backgroundColor: 'rgba(212,175,106,.14)',
            fill: true,
            tension: .4,
            borderWidth: 2.5,
            pointRadius: 0
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { enabled: true } },
          scales: {
            x: { display: false },
            y: { display: false, beginAtZero: true }
          },
          elements: { line: { capBezierPoints: true } }
        }
      });
    }
  });
})();
