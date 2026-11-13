// Live dashboard feed - /api/live/summary ko poll karta hai
// [data-live-*] elements update karta hai aur naye orders pe toast dikhata hai
(function () {
  if (!document.body || document.body.dataset.authenticated !== '1') return;

  let last = null;

  function setText(name, value) {
    document.querySelectorAll('[data-live="' + name + '"]').forEach(function (el) {
      el.textContent = value;
    });
  }

  function money(value) {
    const n = Number(value || 0);
    return 'Rs ' + n.toLocaleString('en-PK', { maximumFractionDigits: 0 });
  }

  async function poll() {
    let data;
    try {
      const res = await fetch('/api/live/summary', { headers: { 'Accept': 'application/json' } });
      if (!res.ok) return;
      data = await res.json();
      if (!data.ok) return;
    } catch (e) {
      return; // offline / server restart - agla poll try kare ga
    }

    setText('new10', data.new_orders_10min !== undefined ? data.new_orders_10min : '');
    setText('openJobs', data.open_jobs !== undefined ? data.open_jobs : '');
    setText('activeOrders', data.active_orders !== undefined ? data.active_orders : '');
    setText('ordersToday', data.orders_today !== undefined ? data.orders_today : '');
    setText('revenueToday', data.revenue_today !== undefined ? money(data.revenue_today) : '');
    setText('earnedToday', data.earned_today !== undefined ? money(data.earned_today) : '');
    setText('deliveredToday', data.delivered_today !== undefined ? data.delivered_today : '');
    setText('unassigned', data.unassigned !== undefined ? data.unassigned : '');

    const signal = JSON.stringify({ n: data.new_orders_10min, j: data.open_jobs, r: data.revenue_today, e: data.earned_today });
    if (last && signal !== last) {
      if (data.new_orders_10min !== undefined && last.n !== undefined && data.new_orders_10min > last.n) {
        window.showToast('New order activity', data.new_orders_10min + ' orders placed in the last 10 minutes.', 'info');
      } else if (data.open_jobs !== undefined && last.j !== undefined && data.open_jobs > last.j) {
        window.showToast('New delivery request', 'A new job is waiting in your assignments.', 'success');
      } else if (data.earned_today !== undefined && last.e !== undefined && data.earned_today > last.e) {
        window.showToast('Income updated', 'You earned ' + money(data.earned_today - last.e) + ' more today.', 'success');
      } else if (data.revenue_today !== undefined && last.r !== undefined && data.revenue_today > last.r) {
        window.showToast('Income updated', 'Today\'s revenue is now ' + money(data.revenue_today) + '.', 'success');
      }
    }
    last = { n: data.new_orders_10min, j: data.open_jobs, r: data.revenue_today, e: data.earned_today };
  }

  poll();
  setInterval(poll, 30000);
})();
