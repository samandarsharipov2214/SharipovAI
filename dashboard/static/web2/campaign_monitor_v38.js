(() => {
  'use strict';
  const PAGE = 'campaigns';
  const POLL_MS = 3000;
  const state = { operations: {}, monitor: {}, error: '' };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === PAGE;
  const fmt = (value, digits = 6) => Number.isFinite(Number(value)) ? Number(value).toLocaleString('ru-RU', {maximumFractionDigits: digits}) : '—';
  const when = (value) => Number(value || 0) > 0 ? new Date(Number(value)).toLocaleString('ru-RU') : '—';

  async function get(url) {
    const response = await fetch(url, {cache: 'no-store', credentials: 'same-origin', headers: {Accept: 'application/json'}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data?.detail?.message || data?.detail || `HTTP ${response.status}`);
    return data;
  }

  function badge(status) {
    const value = String(status || 'unknown').toLowerCase();
    const kind = ['ok','ready','completed','healthy'].includes(value) ? 'ok' : ['running','active','scheduled','degraded'].includes(value) ? 'run' : ['idle','pending','not_run'].includes(value) ? 'idle' : 'bad';
    return `<span class="p7-badge ${kind}">${esc(value.toUpperCase())}</span>`;
  }

  function gates(plan) {
    return Object.entries(plan?.gates || {}).map(([name, passed]) => `<span class="p7-gate ${passed ? 'ok' : 'bad'}">${passed ? '✓' : '×'} ${esc(name)}</span>`).join('') || '<span class="p7-muted">Нет gate evidence.</span>';
  }

  function fills(rows) {
    const values = Array.isArray(rows) ? rows : [];
    return values.slice().reverse().map((row) => `<tr><td><code>${esc(row.order_link_id || '—')}</code><small>${esc((row.exec_ids || []).join(', ') || '—')}</small></td><td>${esc(row.symbol || '—')}</td><td>${esc(row.side || '—')}</td><td>${fmt(row.filled_quantity, 10)}</td><td>${fmt(row.average_fill_price, 8)}</td><td>${fmt(row.actual_fee, 10)} ${esc(row.fee_currency || '')}</td><td>${when(row.last_exec_time_ms)}</td></tr>`).join('');
  }

  function host() {
    const shell = document.querySelector('#content .campaign36-shell');
    if (!shell) return null;
    let panel = document.getElementById('phase7MonitorPanel');
    if (!panel) {
      panel = document.createElement('section');
      panel.id = 'phase7MonitorPanel';
      panel.className = 'p7-shell';
      shell.append(panel);
    }
    return panel;
  }

  function render() {
    if (!active()) return;
    const root = host();
    if (!root) return;
    const operations = state.operations || {};
    const monitor = state.monitor || {};
    const plan = operations.plan || {};
    const progress = monitor.progress || {};
    const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)));
    const alerts = Array.isArray(monitor.alerts) ? monitor.alerts : [];
    const rows = Array.isArray(monitor.actual_fills) ? monitor.actual_fills : [];
    root.innerHTML = `<article class="p7-hero"><div><small>PHASE 7 LIVE EVIDENCE</small><h2>${esc(monitor.campaign_id || 'Кампания не запущена')}</h2><p>${esc(monitor.experiment_id || 'approved experiment required')} · ${esc(monitor.scope || 'BTCUSDT')}</p></div>${badge(monitor.status || operations.status)}</article><section class="p7-metrics"><article><span>Matched</span><b>${Number(progress.matched_fills || 0)} / ${Number(progress.target_fills || 20)}</b><div class="p7-progress"><i style="width:${percent}%"></i></div><small>Осталось ${Number(progress.remaining_fills || 20)}</small></article><article><span>Private fills</span><b>${Number(monitor.actual_fill_count || 0)}</b><small>Authenticated evidence</small></article><article><span>Actual fees</span><b>${fmt(monitor.actual_fee_total, 10)}</b><small>Private execution fees</small></article><article><span>Heartbeat</span><b>${monitor.heartbeat_stale ? 'STALE' : 'LIVE'}</b><small>${fmt(monitor.heartbeat_age_seconds, 2)} сек.</small></article><article><span>Private stream</span><b>${monitor.private_stream?.ready ? 'READY' : 'BLOCKED'}</b><small>${esc(monitor.private_stream?.status || 'no evidence')}</small></article><article><span>Report</span><b>${monitor.final_report_ready ? 'READY' : 'PENDING'}</b><small>${esc(monitor.final_report_id || '20+ clean fills')}</small></article></section><section class="p7-grid"><article class="p7-card"><h3>Release gates</h3><div class="p7-gates">${gates(plan)}</div><p class="p7-muted">${esc((plan.blockers || []).join(', ') || 'Все gates зелёные.')}</p></article><article class="p7-card"><h3>Alerts</h3>${alerts.length ? `<div class="p7-alerts">${alerts.map((item) => `<div>⚠ ${esc(item)}</div>`).join('')}</div>` : '<div class="p7-good">Нет активных alerts.</div>'}</article></section><section class="p7-table-card"><h3>Actual private executions · ${rows.length}</h3><div class="p7-table-scroll"><table><thead><tr><th>Order / execId</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Avg price</th><th>Fee</th><th>Time</th></tr></thead><tbody>${fills(rows) || '<tr><td colspan="7">Private execution evidence пока отсутствует.</td></tr>'}</tbody></table></div></section><section class="p7-grid"><article class="p7-card"><h3>Authority boundary</h3><p>Launch, schedules, cycles and decisions remain in the existing Campaign Operations panels above. Monitor is read-only.</p></article><article class="p7-card"><h3>Report export</h3><p>${esc(monitor.final_report_path || 'Atomic JSON будет создан после final report.')}</p><small>Heartbeat: ${when(monitor.last_heartbeat_ms)} · cycle ${Number(monitor.cycle_count || 0)}</small>${state.error ? `<div class="p7-alerts"><div>${esc(state.error)}</div></div>` : ''}</article></section>`;
  }

  async function load(refresh = false) {
    if (!active()) return;
    try {
      [state.operations, state.monitor] = await Promise.all([get('/api/campaigns/operations'), get(`/api/campaigns/phase7/monitor${refresh ? '?refresh=true' : ''}`)]);
      state.error = '';
    } catch (error) {
      state.error = error?.message || 'Monitor unavailable';
    }
    render();
  }

  setInterval(() => { if (active() && document.visibilityState === 'visible') load(false); }, POLL_MS);
  document.addEventListener('click', (event) => { if (event.target?.closest?.('#nav button[data-page="campaigns"]')) setTimeout(() => load(true), 100); });
  const observer = new MutationObserver(() => { if (active() && !document.getElementById('phase7MonitorPanel')) render(); });
  window.addEventListener('DOMContentLoaded', () => {
    const content = document.getElementById('content');
    if (content) observer.observe(content, {childList: true, subtree: true});
    if (active()) setTimeout(() => load(true), 100);
  }, {once: true});
  window.SharipovAIPhase7CampaignMonitor = {version: 38, load};
})();
