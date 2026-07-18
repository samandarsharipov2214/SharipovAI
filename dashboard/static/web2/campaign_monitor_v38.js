(() => {
  'use strict';
  const PAGE = 'campaigns';
  const POLL_MS = 3000;
  const state = { operations: {}, monitor: {}, error: '', busy: false, updated: 0 };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === PAGE;
  const fmt = (value, digits = 6) => Number.isFinite(Number(value)) ? Number(value).toLocaleString('ru-RU', {maximumFractionDigits: digits}) : '—';
  const when = (value) => Number(value || 0) > 0 ? new Date(Number(value)).toLocaleString('ru-RU') : '—';

  async function request(url, options = {}) {
    const response = await fetch(url, {cache: 'no-store', credentials: 'same-origin', headers: {'Content-Type': 'application/json', Accept: 'application/json'}, ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data?.detail?.message || data?.detail || `HTTP ${response.status}`);
    return data;
  }

  function badge(status) {
    const value = String(status || 'unknown').toLowerCase();
    const kind = ['ok','ready','completed','healthy','resolved'].includes(value) ? 'ok' : ['running','active','scheduled','degraded'].includes(value) ? 'run' : ['idle','pending','not_run'].includes(value) ? 'idle' : 'bad';
    return `<span class="p7-badge ${kind}">${esc(value.toUpperCase())}</span>`;
  }

  function gates(plan) {
    return Object.entries(plan?.gates || {}).map(([name, passed]) => `<span class="p7-gate ${passed ? 'ok' : 'bad'}">${passed ? '✓' : '×'} ${esc(name)}</span>`).join('') || '<span class="p7-muted">Нет gate evidence.</span>';
  }

  function fills(rows) {
    return (Array.isArray(rows) ? rows : []).slice().reverse().map((row) => `<tr><td data-label="Order / execId"><code>${esc(row.order_link_id || '—')}</code><small>${esc((row.exec_ids || []).join(', ') || '—')}</small></td><td data-label="Symbol">${esc(row.symbol || '—')}</td><td data-label="Side">${esc(row.side || '—')}</td><td data-label="Qty">${fmt(row.filled_quantity, 10)}</td><td data-label="Avg price">${fmt(row.average_fill_price, 8)}</td><td data-label="Fee">${fmt(row.actual_fee, 10)} ${esc(row.fee_currency || '')}</td><td data-label="Time">${when(row.last_exec_time_ms)}</td></tr>`).join('');
  }

  function structuredAlerts(alertState) {
    const rows = Array.isArray(alertState?.open_alerts) ? alertState.open_alerts : [];
    if (!rows.length) return '<div class="p7-good">Нет открытых critical alerts.</div>';
    return `<div class="p7-alert-list">${rows.map((row) => `<article class="${esc(row.severity || 'critical')}"><div><b>${esc(row.severity || 'critical')}</b>${badge(row.status)}</div><h4>${esc(row.title || row.code)}</h4><p>${esc(row.message || '')}</p><small>${esc(row.entity_id || 'system')} · ${when(row.first_seen_at_ms)} · ${Number(row.occurrence_count || 1)}×</small></article>`).join('')}</div>`;
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
    const legacyAlerts = Array.isArray(monitor.alerts) ? monitor.alerts : [];
    const alertState = monitor.critical_alerts || {};
    const rows = Array.isArray(monitor.actual_fills) ? monitor.actual_fills : [];
    root.innerHTML = `<article class="p7-hero"><div><small>PHASE 7 LIVE EVIDENCE</small><h2>${esc(monitor.campaign_id || 'Кампания не запущена')}</h2><p>${esc(monitor.experiment_id || 'approved experiment required')} · ${esc(monitor.scope || 'BTCUSDT')}</p></div><div class="p7-hero-actions">${badge(monitor.status || operations.status)}<button id="phase7AlertRefresh" class="p7-button" type="button" ${state.busy ? 'disabled' : ''}>Evaluate alerts</button></div></article><section class="p7-metrics"><article><span>Matched</span><b>${Number(progress.matched_fills || 0)} / ${Number(progress.target_fills || 20)}</b><div class="p7-progress"><i style="width:${percent}%"></i></div><small>Осталось ${Number(progress.remaining_fills || 20)}</small></article><article><span>Private fills</span><b>${Number(monitor.actual_fill_count || 0)}</b><small>Authenticated evidence</small></article><article><span>Actual fees</span><b>${fmt(monitor.actual_fee_total, 10)}</b><small>Private execution fees</small></article><article><span>Heartbeat</span><b>${monitor.heartbeat_stale ? 'STALE' : 'LIVE'}</b><small>${fmt(monitor.heartbeat_age_seconds, 2)} сек.</small></article><article><span>Private stream</span><b>${monitor.private_stream?.ready ? 'READY' : 'BLOCKED'}</b><small>${esc(monitor.private_stream?.status || 'no evidence')}</small></article><article><span>Critical alerts</span><b>${Number(alertState.critical_open_count || 0)}</b><small>${alertState.delivery_configured?.enabled ? 'delivery enabled' : 'persisted locally'}</small></article></section><section class="p7-grid"><article class="p7-card"><h3>Release gates</h3><div class="p7-gates">${gates(plan)}</div><p class="p7-muted">${esc((plan.blockers || []).join(', ') || 'Все gates зелёные.')}</p></article><article class="p7-card"><h3>Canonical blockers</h3>${legacyAlerts.length ? `<div class="p7-alerts">${legacyAlerts.map((item) => `<div>⚠ ${esc(item)}</div>`).join('')}</div>` : '<div class="p7-good">Нет активных blockers.</div>'}</article></section><section class="p7-card"><div class="p7-head"><div><h3>Persistent critical alerts</h3><p class="p7-muted">Kill switch · reconciliation · private stream · campaign blockers</p></div>${badge(alertState.last_result?.status || alertState.status || 'not_run')}</div>${structuredAlerts(alertState)}<small>Webhook ${alertState.delivery_configured?.webhook ? 'configured' : 'off'} · Telegram ${alertState.delivery_configured?.telegram ? 'configured' : 'off'} · updated ${when(alertState.last_result?.evaluated_at_ms || state.updated)}</small></section><section class="p7-table-card"><h3>Actual private executions · ${rows.length}</h3><div class="p7-table-scroll"><table><thead><tr><th>Order / execId</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Avg price</th><th>Fee</th><th>Time</th></tr></thead><tbody>${fills(rows) || '<tr><td colspan="7">Private execution evidence пока отсутствует.</td></tr>'}</tbody></table></div></section><section class="p7-grid"><article class="p7-card"><h3>Authority boundary</h3><p>Launch, schedules, cycles and decisions remain in the existing Campaign Operations panels above. Monitor and alerts are read-only.</p></article><article class="p7-card"><h3>Report export</h3><p>${esc(monitor.final_report_path || 'Atomic JSON будет создан после final report.')}</p><small>Heartbeat: ${when(monitor.last_heartbeat_ms)} · cycle ${Number(monitor.cycle_count || 0)}</small>${state.error ? `<div class="p7-alerts"><div>${esc(state.error)}</div></div>` : ''}</article></section>`;
    document.getElementById('phase7AlertRefresh')?.addEventListener('click', evaluateAlerts);
  }

  async function load(refresh = false) {
    if (!active()) return;
    try {
      [state.operations, state.monitor] = await Promise.all([request('/api/campaigns/operations'), request(`/api/campaigns/phase7/monitor${refresh ? '?refresh=true' : ''}`)]);
      state.updated = Date.now();
      state.error = '';
    } catch (error) {
      state.error = error?.message || 'Monitor unavailable';
    }
    render();
  }

  async function evaluateAlerts() {
    if (state.busy) return;
    state.busy = true;
    render();
    try {
      const result = await request('/api/campaigns/phase7/alerts/refresh', {method: 'POST'});
      state.monitor.critical_alerts = result;
      state.error = '';
    } catch (error) {
      state.error = error?.message || 'Alert evaluation failed';
    } finally {
      state.busy = false;
      state.updated = Date.now();
      render();
    }
  }

  setInterval(() => { if (active() && !state.busy && document.visibilityState === 'visible') load(false); }, POLL_MS);
  document.addEventListener('visibilitychange', () => { if (active() && !state.busy && document.visibilityState === 'visible') load(false); });
  document.addEventListener('click', (event) => { if (event.target?.closest?.('#nav button[data-page="campaigns"]')) setTimeout(() => load(true), 100); });
  const observer = new MutationObserver(() => { if (active() && !document.getElementById('phase7MonitorPanel')) render(); });
  window.addEventListener('DOMContentLoaded', () => {
    const content = document.getElementById('content');
    if (content) observer.observe(content, {childList: true, subtree: true});
    if (active()) setTimeout(() => load(true), 100);
  }, {once: true});
  window.SharipovAIPhase7CampaignMonitor = {version: 39, load, evaluateAlerts};
})();
