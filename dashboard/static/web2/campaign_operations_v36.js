(() => {
  'use strict';

  const PAGE = 'campaigns';
  const VERSION = 38;
  const REFRESH_MS = 10000;
  const CONFIRMATION = 'I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN';
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  const state = { payload: null, selected: '', busy: false, auto: true, error: '', notice: '', updated: 0, timer: null };

  function active() {
    return (window.SharipovAIPageCoordinator?.activePage?.()
      || document.querySelector('#nav button.active[data-page]')?.dataset.page) === PAGE;
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {
      cache: 'no-store', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data?.detail?.message || data?.detail || data?.message || `HTTP ${response.status}`;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function badge(value) {
    const status = String(value || 'unknown').toLowerCase();
    const cls = ['ok', 'ready', 'completed', 'approved', 'resolved', 'eligible_for_manual_decision'].includes(status)
      ? 'ok' : ['running', 'scheduled', 'active', 'not_run', 'waiting_for_shadow_fills'].includes(status) ? 'run' : 'bad';
    return `<span class="campaign36-badge ${cls}">${esc(status.toUpperCase())}</span>`;
  }

  function time(value) {
    return Number(value || 0) > 0 ? new Date(Number(value)).toLocaleString('ru-RU') : '—';
  }

  function number(value, digits = 6) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toLocaleString('ru-RU', { maximumFractionDigits: digits }) : '—';
  }

  function rows(payload) {
    const map = new Map((payload?.recent_campaigns || []).map((row) => [String(row.campaign_id || ''), row]));
    for (const row of [payload?.active_campaign, payload?.latest_campaign]) {
      if (row?.campaign_id) map.set(String(row.campaign_id), row);
    }
    return [...map.values()];
  }

  function selected(payload) {
    const all = rows(payload);
    const row = all.find((item) => String(item.campaign_id) === state.selected)
      || payload?.active_campaign || payload?.latest_campaign || all[0] || {};
    if (row.campaign_id) state.selected = String(row.campaign_id);
    return row;
  }

  function metric(label, value, note) {
    return `<article class="campaign36-card"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`;
  }

  function health(payload) {
    const alerts = payload.alerts || {};
    const stale = state.updated && Date.now() - state.updated > REFRESH_MS * 3;
    return `<section class="campaign36-health">
      <div><span>API</span>${badge(stale ? 'stale' : payload.status)}</div>
      <div><span>Orchestrator</span>${badge(payload.orchestrator?.status || 'not_run')}</div>
      <div><span>Alert monitor</span>${badge(alerts.status || alerts.last_result?.status || 'not_run')}</div>
      <div><span>Critical</span><b class="${Number(alerts.critical_open_count || 0) ? 'danger' : 'safe'}">${Number(alerts.critical_open_count || 0)}</b></div>
      <div><span>Updated</span><b>${time(state.updated)}</b></div>
    </section>`;
  }

  function selector(payload) {
    const options = rows(payload).map((row) => `<option value="${esc(row.campaign_id)}" ${String(row.campaign_id) === state.selected ? 'selected' : ''}>${esc(row.campaign_id)} · ${esc(row.status)}</option>`).join('');
    return `<section class="campaign36-selector">
      <label for="campaign36CampaignSelect">Selected campaign</label>
      <select id="campaign36CampaignSelect">${options || '<option value="">No campaigns</option>'}</select>
      <button id="campaign36Refresh" type="button">Refresh</button>
      <button id="campaign36AutoRefresh" type="button" aria-pressed="${state.auto}">Auto: ${state.auto ? 'ON' : 'OFF'}</button>
    </section>`;
  }

  function campaignPanel(campaign) {
    if (!campaign?.campaign_id) return '<section class="campaign36-empty"><h3>No campaign</h3><p>The bounded Testnet authorization is free. Every release gate and exact confirmation is still required.</p></section>';
    const progress = campaign.progress || {};
    const integrity = campaign.identity_integrity || {};
    const fees = campaign.fees || {};
    const report = campaign.final_report || {};
    const failed = campaign.failed_gates || [];
    return `<section class="campaign36-section">
      <div class="campaign36-head"><div><div class="campaign36-kicker">SELECTED CAMPAIGN</div><h2>${esc(campaign.campaign_id)}</h2><p>${esc(campaign.experiment_id || '—')} · ${esc(campaign.scope || '—')} · cycle ${Number(campaign.cycle_count || 0)}</p></div>${badge(campaign.status)}</div>
      <div class="campaign36-grid">
        <article class="campaign36-card"><span>Real fills</span><strong>${Number(progress.matched_fills || 0)} / ${Number(progress.target_fills || 20)}</strong><div class="campaign36-progress"><i style="width:${Math.max(0, Math.min(100, Number(progress.percent || 0)))}%"></i></div><small>${number(progress.percent, 2)}% · ${Number(progress.remaining_fills || 0)} remaining</small></article>
        ${metric('Actual fees', number(fees.actual_fee_total, 8), fees.actual_execution_fees ? 'Private fee evidence present' : 'Waiting for execution evidence')}
        ${metric('Final report', report.generated ? 'GENERATED' : report.ready ? 'READY' : 'PENDING', report.report_id || 'Automatic after clean completion')}
        ${metric('Notional', '10–25 USDT', 'Spot Testnet only · Mainnet off')}
      </div>
      <div class="campaign36-integrity">${['orphan_execution_count:Orphans', 'duplicate_order_count:Duplicates', 'unresolved_order_count:Unresolved'].map((entry) => {
        const [key, label] = entry.split(':'); const value = Number(integrity[key] || 0);
        return `<article class="${value ? 'bad' : 'ok'}"><span>${label}</span><b>${value}</b></article>`;
      }).join('')}</div>
      ${failed.length ? `<div class="campaign36-alert"><b>Failed gates</b><div class="campaign36-chips">${failed.map((value) => `<span>${esc(value)}</span>`).join('')}</div></div>` : '<div class="campaign36-success">No recorded identity or reconciliation failures.</div>'}
    </section>`;
  }

  function alertsPanel(alerts) {
    const cards = (alerts.open_alerts || []).map((alert) => `<article class="campaign36-alert-card ${esc(alert.severity || 'critical')}"><div><b>${esc(alert.severity || 'critical')}</b>${badge(alert.status)}</div><h4>${esc(alert.title || alert.code)}</h4><p>${esc(alert.message)}</p><small>${esc(alert.entity_id)} · ${time(alert.first_seen_at_ms)} · ${Number(alert.occurrence_count || 1)}×</small></article>`).join('');
    return `<section class="campaign36-section"><div class="campaign36-head"><div><div class="campaign36-kicker">CRITICAL EVENTS</div><h3>Monitoring & alerting</h3></div><button id="campaign36AlertTick" type="button">Evaluate now</button></div><div class="campaign36-alert-grid">${cards || '<article class="campaign36-empty"><h4>No open alerts</h4><p>Kill switch, reconciliation, private stream and campaign blockers are clear.</p></article>'}</div><small>Webhook ${alerts.delivery_configured?.webhook ? 'configured' : 'off'} · Telegram ${alerts.delivery_configured?.telegram ? 'configured' : 'off'} · delivery ${alerts.delivery_configured?.enabled ? 'enabled' : 'disabled'}.</small></section>`;
  }

  function gatesPanel(plan) {
    const gates = Object.entries(plan?.gates || {}).map(([name, passed]) => `<span class="campaign36-gate ${passed ? 'ok' : 'bad'}">${passed ? '✓' : '×'} ${esc(name)}</span>`).join('');
    const blockers = plan?.blockers || [];
    return `<section class="campaign36-section"><div class="campaign36-head"><div><div class="campaign36-kicker">RELEASE GATES</div><h3>First-campaign readiness</h3></div>${badge(plan?.status || 'blocked')}</div><div class="campaign36-gates">${gates}</div>${blockers.length ? `<div class="campaign36-alert">${blockers.map(esc).join(' · ')}</div>` : '<div class="campaign36-success">All currently evaluated gates pass.</div>'}</section>`;
  }

  function controls(campaign) {
    const terminal = ['completed', 'blocked', 'cancelled'].includes(String(campaign?.status || ''));
    return `<section class="campaign36-section"><div class="campaign36-head"><div><div class="campaign36-kicker">OPERATOR CONTROLS</div><h3>Canonical lifecycle</h3></div><span>Mainnet unavailable</span></div>
      <div class="campaign36-actions"><button id="campaign36Tick">Orchestrator tick</button><button id="campaign36Cycle" ${!campaign?.campaign_id || terminal ? 'disabled' : ''}>Run selected cycle</button><button id="campaign36Report" ${campaign?.status !== 'completed' ? 'disabled' : ''}>Generate final report</button></div>
      <form id="campaign36ScheduleForm" class="campaign36-form compact"><label>Approved experiment<input id="campaign36ScheduleExperiment" required value="${esc(campaign?.experiment_id || '')}"></label><label>Scope<input id="campaign36ScheduleScope" required value="${esc(campaign?.scope || 'BTCUSDT')}"></label><label>Interval, sec<input id="campaign36ScheduleInterval" type="number" min="60" max="86400" value="300"></label><button>Create schedule</button></form>
    </section>`;
  }

  function launch(campaign) {
    return `<section class="campaign36-section"><div class="campaign36-kicker">FIRST REAL TESTNET CAMPAIGN</div><h3>Launch bounded evidence collection</h3><p>20+ actual matched fills, actual fees and zero orphan, duplicate or unresolved evidence.</p><form id="campaign36LaunchForm" class="campaign36-form"><label>Promoted experiment<input id="campaign36Experiment" required value="${esc(campaign?.experiment_id || '')}"></label><label>Scope<input id="campaign36Scope" required value="${esc(campaign?.scope || 'BTCUSDT')}"></label><label class="full">Exact confirmation<div class="campaign36-copy"><input id="campaign36Confirmation" required placeholder="${CONFIRMATION}"><button id="campaign36CopyConfirmation" type="button">Copy</button></div></label><button class="full primary" ${state.busy ? 'disabled' : ''}>Start bounded Testnet campaign</button></form><small>UI never changes deployment flags, credentials, kill switch policy or Mainnet availability.</small></section>`;
  }

  function historyPanel(payload) {
    const cards = rows(payload).map((row) => `<button class="campaign36-history-card ${String(row.campaign_id) === state.selected ? 'active' : ''}" data-campaign-id="${esc(row.campaign_id)}"><div><b>${esc(row.campaign_id)}</b>${badge(row.status)}</div><span>${esc(row.scope || '—')} · ${Number(row.progress?.matched_fills || 0)}/${Number(row.progress?.target_fills || 20)}</span><small>${time(row.updated_at_ms || row.created_at_ms)}</small></button>`).join('');
    return `<section class="campaign36-section"><div class="campaign36-kicker">HISTORY</div><h3>Recent campaigns</h3><div class="campaign36-history">${cards || '<p>No campaign records.</p>'}</div></section>`;
  }

  function schedules(payload) {
    const body = (payload.schedules || []).map((row) => `<tr><td data-label="ID">${esc(row.schedule_id)}</td><td data-label="Experiment">${esc(row.experiment_id)}</td><td data-label="Scope">${esc(row.scope)}</td><td data-label="Next">${time(row.next_run_at_ms)}</td><td data-label="State">${badge(row.enabled ? 'active' : 'disabled')}</td></tr>`).join('');
    return `<section class="campaign36-section"><div class="campaign36-kicker">SCHEDULES</div><h3>Approved schedules</h3><div class="campaign36-table-wrap"><table class="campaign36-table"><thead><tr><th>ID</th><th>Experiment</th><th>Scope</th><th>Next</th><th>State</th></tr></thead><tbody>${body || '<tr><td colspan="5">No schedules.</td></tr>'}</tbody></table></div></section>`;
  }

  function render() {
    if (!active()) return;
    const out = $('content'); if (!out) return;
    if (!state.payload) { out.innerHTML = '<div class="title"><h1>Campaign Operations</h1><p>Loading canonical evidence…</p></div>'; return; }
    const payload = state.payload; const campaign = selected(payload); const alerts = payload.alerts || {};
    out.innerHTML = `<div class="title"><h1>Campaign Operations</h1><p>Bounded Testnet evidence, alerts and final-report readiness</p></div><section class="campaign36-shell"><section class="campaign36-hero"><div><div class="campaign36-kicker">PHASE 7 · PRODUCTION READINESS</div><h2>Bounded Testnet Operations</h2><p>Single authorization · real private fills · persistent alerts · immutable report</p></div>${badge(payload.status)}</section>${health(payload)}${selector(payload)}<section class="campaign36-grid">${metric('Schedules', payload.schedule_count || 0, 'Persisted')}${metric('Campaigns', payload.campaign_count || 0, 'Immutable')}${metric('Matched fills', `${Number(campaign.progress?.matched_fills || 0)} / ${Number(campaign.progress?.target_fills || 20)}`, 'Real private evidence')}${metric('Open alerts', alerts.open_count || 0, `${Number(alerts.critical_open_count || 0)} critical`)}</section>${state.notice ? `<div class="campaign36-success">${esc(state.notice)}</div>` : ''}${state.error ? `<div class="campaign36-alert">${esc(state.error)}</div>` : ''}${campaignPanel(campaign)}${alertsPanel(alerts)}${gatesPanel(payload.plan || {})}${controls(campaign)}${launch(campaign)}${historyPanel(payload)}${schedules(payload)}</section>`;
    bind(campaign);
  }

  async function load(announce = false) {
    if (!active()) return;
    try { state.payload = await api('/api/campaigns/operations'); state.updated = Date.now(); state.error = ''; if (announce) state.notice = 'Snapshot refreshed.'; }
    catch (error) { state.error = `Campaign Operations API: ${error.message}`; }
    render();
  }

  async function mutate(fn) {
    if (state.busy) return; state.busy = true; state.error = ''; state.notice = ''; render();
    try { state.notice = await fn(); await load(); } catch (error) { state.error = error.message || 'Operation blocked'; }
    finally { state.busy = false; render(); }
  }

  function bind(campaign) {
    $('campaign36CampaignSelect')?.addEventListener('change', (event) => { state.selected = event.target.value; render(); });
    document.querySelectorAll('[data-campaign-id]').forEach((button) => button.addEventListener('click', () => { state.selected = button.dataset.campaignId; render(); }));
    $('campaign36Refresh')?.addEventListener('click', () => load(true));
    $('campaign36AutoRefresh')?.addEventListener('click', () => { state.auto = !state.auto; render(); });
    $('campaign36AlertTick')?.addEventListener('click', () => mutate(async () => { const result = await api('/api/campaigns/alerts/tick', { method: 'POST' }); return `Alerts: ${Number(result.open_count || 0)} open.`; }));
    $('campaign36Tick')?.addEventListener('click', () => mutate(async () => { await api('/api/campaigns/orchestrator/tick', { method: 'POST' }); return 'Orchestrator tick complete.'; }));
    $('campaign36Cycle')?.addEventListener('click', () => mutate(async () => { const result = await api(`/api/campaigns/${encodeURIComponent(campaign.campaign_id)}/run`, { method: 'POST' }); return `Campaign: ${result.campaign?.status || 'updated'}.`; }));
    $('campaign36Report')?.addEventListener('click', () => mutate(async () => { const result = await api(`/api/campaigns/${encodeURIComponent(campaign.campaign_id)}/promotion-report`, { method: 'POST' }); return `Report: ${result.report?.report_id || 'generated'}.`; }));
    $('campaign36ScheduleForm')?.addEventListener('submit', (event) => { event.preventDefault(); mutate(async () => { const result = await api('/api/campaigns/schedules', { method: 'POST', body: JSON.stringify({ experiment_id: $('campaign36ScheduleExperiment').value.trim(), scope: $('campaign36ScheduleScope').value.trim(), interval_seconds: Number($('campaign36ScheduleInterval').value), enabled: true }) }); return `Schedule: ${result.schedule?.schedule_id || 'created'}.`; }); });
    $('campaign36LaunchForm')?.addEventListener('submit', (event) => { event.preventDefault(); mutate(async () => { const result = await api('/api/campaigns/first-testnet/start', { method: 'POST', body: JSON.stringify({ experiment_id: $('campaign36Experiment').value.trim(), scope: $('campaign36Scope').value.trim(), confirmation: $('campaign36Confirmation').value }) }); state.selected = result.campaign?.campaign_id || ''; return `Campaign: ${state.selected || 'created'}.`; }); });
    $('campaign36CopyConfirmation')?.addEventListener('click', async () => { try { await navigator.clipboard.writeText(CONFIRMATION); $('campaign36Confirmation').value = CONFIRMATION; state.notice = 'Confirmation copied.'; } catch (_) { state.error = 'Clipboard unavailable.'; } render(); });
  }

  function install() {
    const nav = $('nav'); if (!nav) return;
    let button = nav.querySelector('[data-page="campaigns"]');
    if (!button) { button = document.createElement('button'); button.type = 'button'; button.dataset.page = PAGE; button.textContent = 'Кампании'; nav.appendChild(button); }
    if (button.dataset.campaignVersion === String(VERSION)) return;
    button.dataset.campaignVersion = String(VERSION);
    button.addEventListener('click', () => { nav.querySelectorAll('button[data-page]').forEach((item) => item.classList.remove('active')); button.classList.add('active'); history.replaceState(null, '', '#campaigns'); render(); load(); });
    if (!state.timer) state.timer = setInterval(() => { if (active() && state.auto && !state.busy && document.visibilityState === 'visible') load(); }, REFRESH_MS);
    if (location.hash === '#campaigns') button.click();
  }

  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && active() && state.auto && !state.busy) load(); });
  window.addEventListener('DOMContentLoaded', install);
  window.addEventListener('hashchange', install);
})();
