(function () {
  const body = document.body;
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

  // CSRF for any form not already having it
  document.querySelectorAll('form').forEach(function (form) {
    if (form.querySelector('input[name="csrf_token"]')) return;
    if (form.method.toLowerCase() === 'post' || form.method.toLowerCase() === 'delete') {
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'csrf_token';
      input.value = csrfToken;
      form.appendChild(input);
    }
  });

  // Attach CSRF to fetch/XHR
  const originalFetch = window.fetch;
  window.fetch = function (resource, options) {
    options = options || {};
    const method = (options.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      options.headers = options.headers || {};
      if (!(options.headers instanceof Headers)) {
        options.headers = new Headers(options.headers);
      }
      if (!options.headers.has('X-CSRFToken')) {
        options.headers.set('X-CSRFToken', csrfToken);
      }
      if (!options.headers.has('Content-Type') && options.body && typeof options.body === 'string') {
        options.headers.set('Content-Type', 'application/json');
      }
    }
    return originalFetch.call(this, resource, options);
  };

  // Notifications
  const notifBadge = document.getElementById('notifBadge');
  const notifList = document.getElementById('notifList');
  const markAllRead = document.getElementById('markAllRead');
  const notifToggle = document.getElementById('notifToggle');

  async function loadNotifications() {
    if (!notifList) return;
    try {
      const res = await fetch('/api/notifications', { headers: { 'Accept': 'application/json' } });
      const data = await res.json();
      if (!data.ok) return;
      updateBadge(data.unread);
      renderNotifications(data.items || []);
    } catch (error) {
      notifList.innerHTML = '<div class="notif-empty">Could not load notifications</div>';
    }
  }

  function updateBadge(count) {
    if (!notifBadge) return;
    if (count && count > 0) {
      notifBadge.textContent = count > 9 ? '9+' : count;
      notifBadge.classList.remove('d-none');
    } else {
      notifBadge.textContent = '0';
      notifBadge.classList.add('d-none');
    }
  }

  function renderNotifications(items) {
    if (!notifList) return;
    if (items.length === 0) {
      notifList.innerHTML = '<div class="notif-empty">All caught up ✨</div>';
      return;
    }
    notifList.innerHTML = items.map(function (item) {
      return '<a class="notif-item ' + (item.is_read ? '' : 'unread') + '" href="' + (item.link || '#') + '" data-id="' + item.id + '">' +
        '<div class="notif-icon"><i class="bi bi-' + (item.icon || 'bell') + '"></i></div>' +
        '<div class="notif-body"><strong>' + escapeHtml(item.title) + '</strong>' +
        (item.message ? '<p>' + escapeHtml(item.message) + '</p>' : '') +
        '<time>' + formatTimeAgo(item.created_at) + '</time></div></a>';
    }).join('');
  }

  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function formatTimeAgo(iso) {
    if (!iso) return '';
    try {
      const date = new Date(iso);
      const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
      if (seconds < 60) return 'just now';
      if (seconds < 3600) return Math.floor(seconds / 60) + ' min ago';
      if (seconds < 86400) return Math.floor(seconds / 3600) + ' hr ago';
      return Math.floor(seconds / 86400) + ' day(s) ago';
    } catch (e) { return ''; }
  }

  if (markAllRead) {
    markAllRead.addEventListener('click', async function () {
      try {
        await fetch('/api/notifications/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ all: true }) });
        loadNotifications();
      } catch (e) {}
    });
  }

  notifList && notifList.addEventListener('click', async function (event) {
    const item = event.target.closest('.notif-item[data-id]');
    if (!item) return;
    const id = item.getAttribute('data-id');
    if (item.classList.contains('unread')) {
      try { await fetch('/api/notifications/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id }) }); } catch (e) {}
    }
  });

  if (notifToggle && body.dataset.authenticated === '1') {
    loadNotifications();
    setInterval(loadNotifications, 45000);
  }

  // Password toggle
  document.querySelectorAll('[data-password-toggle]').forEach(function (button) {
    button.addEventListener('click', function () {
      const target = document.getElementById(button.dataset.passwordToggle);
      if (!target) return;
      const isPassword = target.getAttribute('type') === 'password';
      target.setAttribute('type', isPassword ? 'text' : 'password');
      button.querySelector('i').classList.toggle('bi-eye', !isPassword);
      button.querySelector('i').classList.toggle('bi-eye-slash', isPassword);
    });
  });

  // Session timeout warning
  const timeoutMinutes = parseInt(body.dataset.timeout || document.querySelector('meta[name="session-timeout"]')?.getAttribute('content') || '30', 10);
  if (body.dataset.authenticated === '1' && timeoutMinutes > 0) {
    let lastActivity = Date.now();
    ['click', 'keydown', 'mousemove', 'scroll', 'touchstart'].forEach(function (event) {
      document.addEventListener(event, function () { lastActivity = Date.now(); }, { passive: true });
    });
    setInterval(function () {
      if (Date.now() - lastActivity > timeoutMinutes * 60 * 1000 - 2 * 60 * 1000) {
        const seconds = Math.ceil((timeoutMinutes * 60 * 1000 - (Date.now() - lastActivity)) / 1000);
        if (seconds > 0 && seconds <= 120) {
          showToast('Session expiring soon', 'You will be signed out in ' + seconds + 's due to inactivity.', 'warning');
        }
      }
    }, 10000);
  }

  // Toast helper
  window.showToast = function (title, message, variant) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    variant = variant || 'info';
    const el = document.createElement('div');
    el.className = 'toast align-items-center border-0 shadow-soft show';
    el.setAttribute('role', 'alert');
    el.innerHTML = '<div class="d-flex"><div class="toast-body"><strong>' + escapeHtml(title) + '</strong><div class="small text-muted">' + escapeHtml(message) + '</div></div><button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast"></button></div>';
    el.style.borderLeft = variant === 'success' ? '3px solid #1f9d68' : variant === 'warning' ? '3px solid #f0a20a' : variant === 'danger' ? '3px solid #dc3545' : '3px solid #2563eb';
    container.appendChild(el);
    setTimeout(function () { el.classList.remove('show'); setTimeout(function () { el.remove(); }, 300); }, 4200);
  };

  // Online/offline banner
  function updateOnline() {
    body.classList.toggle('is-offline', !navigator.onLine);
  }
  window.addEventListener('online', updateOnline);
  window.addEventListener('offline', updateOnline);
  updateOnline();

  // Navbar scroll effect
  const navbar = document.querySelector('.app-navbar');
  window.addEventListener('scroll', function () {
    navbar.classList.toggle('scrolled', window.scrollY > 8);
  }, { passive: true });

  // Auto-dismiss alerts after 6s
  document.querySelectorAll('.app-alert').forEach(function (alert) {
    setTimeout(function () {
      try { bootstrap.Alert.getOrCreateInstance(alert).close(); } catch (e) {}
    }, 6000);
  });
})();
