/* Live order tracking, route maps and location pickers (Leaflet). */
(function () {
  const hasLeaflet = typeof L !== 'undefined';
  const markerIcons = {
    restaurant: { emoji: '🍽️', className: 'pin-restaurant' },
    customer: { emoji: '🏠', className: 'pin-customer' },
    partner: { emoji: '🛵', className: 'pin-partner' },
    pickup: { emoji: '🍽️', className: 'pin-restaurant' },
    drop: { emoji: '🏠', className: 'pin-customer' },
    start: { emoji: '🛵', className: 'pin-partner' }
  };

  function icon(kind) {
    const info = markerIcons[kind] || markerIcons.customer;
    return L.divIcon({
      className: 'map-pin-wrap',
      html: '<div class="map-pin ' + info.className + '">' + info.emoji + '</div>',
      iconSize: [30, 30],
      iconAnchor: [15, 26]
    });
  }

  function fallback(el, message) {
    el.innerHTML = '<div class="map-fallback"><div><i class="bi bi-map fs-2 d-block mb-2"></i>' + message + '</div></div>';
  }

  function parseJSON(value, fallbackValue) {
    if (!value) return fallbackValue;
    try { return JSON.parse(value.replace(/&quot;/g, '"')); } catch (e) { return fallbackValue; }
  }

  function addTileLayer(map) {
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);
  }

  // ------------------------------------------------------------------
  // Live order tracking map
  // ------------------------------------------------------------------
  const maps = {};

  function initTrackingMap(el) {
    const orderId = el.dataset.orderId;
    if (!orderId) return;
    const initial = parseJSON(el.dataset.track, null);
    const url = el.dataset.trackingUrl || '/api/orders/' + orderId + '/tracking';

    if (!hasLeaflet) {
      fallback(el, 'Interactive map needs Leaflet (CDN). Order updates still work below.');
      pollTracking(el, url, null, null);
      return;
    }

    const map = L.map(el, { zoomControl: true, scrollWheelZoom: false });
    addTileLayer(map);
    el._leafletMap = map;
    const state = { map: map, markers: {}, trail: null, routeLine: null, delivered: false };
    maps[orderId] = state;

    function render(payload) {
      if (!payload || !payload.ok) return;
      updateStatusUI(payload);
      const order = payload.order || {};
      const restaurant = payload.restaurant || {};
      const destination = payload.destination || {};
      const partner = payload.partner || {};
      const points = [];

      setMarker(state, 'restaurant', [restaurant.lat, restaurant.lng], restaurant.name || 'Restaurant');
      setMarker(state, 'customer', [destination.lat, destination.lng], 'Delivery address');

      if (partner.lat != null && partner.lng != null) {
        setMarker(state, 'partner', [partner.lat, partner.lng], partner.name || 'Delivery partner');
        points.push([partner.lat, partner.lng]);
      }
      if (restaurant.lat != null && restaurant.lng != null) points.push([restaurant.lat, restaurant.lng]);
      if (destination.lat != null && destination.lng != null) points.push([destination.lat, destination.lng]);

      const trailPoints = (payload.track || []).map(function (point) { return [point.lat, point.lng]; });
      if (trailPoints.length > 1) {
        if (!state.trail) {
          state.trail = L.polyline(trailPoints, { color: '#d4af6a', weight: 3, opacity: .65, dashArray: '6 7' }).addTo(map);
        } else {
          state.trail.setLatLngs(trailPoints);
        }
      }

      const routePoints = [];
      if (partner.lat != null) routePoints.push([partner.lat, partner.lng]);
      if (restaurant.lat != null) routePoints.push([restaurant.lat, restaurant.lng]);
      if (destination.lat != null) routePoints.push([destination.lat, destination.lng]);
      if (routePoints.length > 1) {
        if (!state.routeLine) {
          state.routeLine = L.polyline(routePoints, { color: '#1d2941', weight: 4, opacity: .75 }).addTo(map);
        } else {
          state.routeLine.setLatLngs(routePoints);
        }
      }

      if (points.length && !state.fitted) {
        map.fitBounds(L.latLngBounds(points).pad(0.28), { maxZoom: 16 });
        state.fitted = true;
      } else if (partner.lat != null) {
        map.panTo([partner.lat, partner.lng], { animate: true });
      }

      if (order.status === 'delivered' || order.status === 'cancelled') {
        state.delivered = true;
      }
    }

    function setMarker(state, key, latlng, title) {
      if (latlng[0] == null || latlng[1] == null) return;
      if (state.markers[key]) {
        state.markers[key].setLatLng(latlng);
      } else {
        state.markers[key] = L.marker(latlng, { icon: icon(key), title: title || '' }).addTo(map);
      }
    }

    if (initial && initial.ok) {
      render(initial);
    } else {
      map.setView([18.5204, 73.8567], 12);
    }
    pollTracking(el, url, render, state);
  }

  function updateStatusUI(payload) {
    const order = payload.order || {};
    const progress = document.getElementById('trackProgressBar');
    if (progress) progress.style.width = (order.progress || 0) + '%';
    const statusText = document.getElementById('trackStatusText');
    if (statusText) statusText.textContent = order.status_label || order.status || '';
    const updated = document.getElementById('trackLastUpdated');
    if (updated) updated.textContent = 'Updated ' + new Date().toLocaleTimeString();
    const partnerName = document.getElementById('trackPartnerName');
    if (partnerName && payload.partner && payload.partner.name) partnerName.textContent = payload.partner.name;
    const partnerPhone = document.getElementById('trackPartnerPhone');
    if (partnerPhone && payload.partner && payload.partner.phone) {
      partnerPhone.textContent = payload.partner.phone;
      partnerPhone.href = 'tel:' + payload.partner.phone;
    }
    const liveDot = document.getElementById('trackLiveDot');
    if (liveDot && (order.status === 'delivered' || order.status === 'cancelled')) {
      liveDot.style.background = '#a6b1aa';
    }
  }

  function pollTracking(el, url, render, state) {
    let stopped = false;
    async function tick() {
      if (stopped || !navigator.onLine) return;
      if (state && state.delivered) { stopped = true; return; }
      try {
        const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
        if (res.status === 401 || res.status === 403) { stopped = true; return; }
        const data = await res.json();
        if (data.ok && render) render(data);
      } catch (error) { /* keep the last known position */ }
    }
    setInterval(tick, 7000);
  }

  // ------------------------------------------------------------------
  // Route optimization map
  // ------------------------------------------------------------------
  function initRouteMaps() {
    document.querySelectorAll('.route-map[data-route]').forEach(function (el) {
      const data = parseJSON(el.dataset.route, null);
      if (!data || !data.stops || !data.stops.length) {
        if (hasLeaflet) {
          const map = L.map(el).setView([18.5204, 73.8567], 12);
          addTileLayer(map);
        } else {
          fallback(el, 'No route points yet. Add coordinates to the customer profile / restaurants.');
        }
        return;
      }
      if (!hasLeaflet) {
        fallback(el, 'Route map needs Leaflet. The optimized stop order is shown next to the map.');
        return;
      }
      const map = L.map(el, { scrollWheelZoom: false });
      addTileLayer(map);
      const points = [];
      data.stops.forEach(function (stop, index) {
        const latlng = [stop.lat, stop.lng];
        points.push(latlng);
        let html = stop.kind === 'partner'
          ? '<div class="map-pin">🛵</div>'
          : '<div class="map-pin route-num">' + (stop.sequence || (index)) + '</div>';
        L.marker(latlng, {
          icon: L.divIcon({ className: 'map-pin-wrap', html: html, iconSize: [30, 30], iconAnchor: [15, 15] })
        }).addTo(map).bindPopup('<strong>' + escapeHtml(stop.label || '') + '</strong>' + (stop.address ? '<br><small>' + escapeHtml(stop.address) + '</small>' : ''));
      });
      L.polyline(points, { color: '#d4af6a', weight: 4, opacity: .8 }).addTo(map);
      if (points.length) map.fitBounds(L.latLngBounds(points).pad(0.22), { maxZoom: 16 });
    });
  }

  // ------------------------------------------------------------------
  // Location picker (checkout / profile)
  // ------------------------------------------------------------------
  function initLocationPickers() {
    document.querySelectorAll('.location-picker').forEach(function (picker, index) {
      const latInput = document.getElementById(picker.dataset.latInput || 'latitude');
      const lngInput = document.getElementById(picker.dataset.lngInput || 'longitude');
      const mapEl = picker.querySelector('.map-box');
      const status = picker.querySelector('[data-location-status]');
      if (!latInput || !lngInput) return;
      let map = null;
      let marker = null;

      function setValues(lat, lng) {
        latInput.value = Number(lat).toFixed(6);
        lngInput.value = Number(lng).toFixed(6);
        if (status) status.textContent = 'Location set to ' + Number(lat).toFixed(5) + ', ' + Number(lng).toFixed(5);
      }

      function place(lat, lng, pan) {
        if (!hasLeaflet) return;
        if (!map) {
          map = L.map(mapEl).setView([lat, lng], 15);
          addTileLayer(map);
          map.on('click', function (event) {
            place(event.latlng.lat, event.latlng.lng, false);
            setValues(event.latlng.lat, event.latlng.lng);
          });
        }
        if (marker) marker.setLatLng([lat, lng]);
        else marker = L.marker([lat, lng], { icon: icon('customer'), draggable: true }).addTo(map);
        marker.on('dragend', function () {
          const pos = marker.getLatLng();
          setValues(pos.lat, pos.lng);
        });
        if (pan) map.setView([lat, lng], 15);
        setValues(lat, lng);
      }

      if (hasLeaflet && mapEl) {
        const startLat = parseFloat(latInput.value);
        const startLng = parseFloat(lngInput.value);
        if (!isNaN(startLat) && !isNaN(startLng)) {
          place(startLat, startLng, true);
        } else {
          map = L.map(mapEl).setView([18.5204, 73.8567], 12);
          addTileLayer(map);
          map.on('click', function (event) {
            place(event.latlng.lat, event.latlng.lng, false);
            setValues(event.latlng.lat, event.latlng.lng);
          });
        }
      } else if (mapEl) {
        fallback(mapEl, 'Map needs Leaflet. You can still type coordinates below.');
      }

      const useBtn = picker.querySelector('[data-use-location]');
      if (useBtn) {
        useBtn.addEventListener('click', function () {
          if (!navigator.geolocation) {
            window.showToast('Location unavailable', 'This browser does not support geolocation.', 'warning');
            return;
          }
          useBtn.disabled = true;
          navigator.geolocation.getCurrentPosition(function (position) {
            place(position.coords.latitude, position.coords.longitude, true);
            useBtn.disabled = false;
          }, function () {
            useBtn.disabled = false;
            window.showToast('Location denied', 'Allow location access or pick the point on the map.', 'warning');
          }, { enableHighAccuracy: true, timeout: 8000 });
        });
      }
    });
  }

  // ------------------------------------------------------------------
  // Partner "share live location" buttons
  // ------------------------------------------------------------------
  function initShareLocation() {
    document.querySelectorAll('[data-share-location]').forEach(function (button) {
      button.addEventListener('click', function () {
        if (!navigator.geolocation) {
          window.showToast('Location unavailable', 'This browser does not support geolocation.', 'warning');
          return;
        }
        button.disabled = true;
        const original = button.innerHTML;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Locating…';
        navigator.geolocation.getCurrentPosition(async function (position) {
          const payload = {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            speed: position.coords.speed
          };
          if (button.dataset.orderId) payload.order_id = button.dataset.orderId;
          try {
            const res = await fetch('/api/partners/location', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.error || 'Could not update location');
            window.showToast('Location shared', 'Your live location has been updated.', 'success');
            document.querySelectorAll('[data-live-coords]').forEach(function (el) {
              el.textContent = Number(payload.latitude).toFixed(5) + ', ' + Number(payload.longitude).toFixed(5);
            });
            const mapEl = document.getElementById('trackingMap');
            if (mapEl && mapEl._leafletMap) mapEl._leafletMap.fire('invalidateSize');
            setTimeout(function () { if (button.dataset.reload === '1') window.location.reload(); }, 900);
          } catch (error) {
            window.showToast('Update failed', error.message, 'danger');
          } finally {
            button.disabled = false;
            button.innerHTML = original;
          }
        }, function () {
          button.disabled = false;
          button.innerHTML = original;
          window.showToast('Location denied', 'Allow location access to share live tracking.', 'warning');
        }, { enableHighAccuracy: true, timeout: 10000 });
      });
    });
  }

  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.map-box[data-order-id]').forEach(initTrackingMap);
    initRouteMaps();
    initLocationPickers();
    initShareLocation();
  });
})();
