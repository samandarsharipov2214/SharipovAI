(() => {
  'use strict';

  const VERSION = 36;
  const PAGE = 'campaigns';
  const CONFIRMATION = 'I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN';
  const REFRESH_MS = 10000;
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  const state = {
    payload: null,
    error: '',
    busy: false,
    result: '',
    loadedAt: 0,
    timer: null,
  };

  function active() {
    return (window.SharipovAIPageCoordinator?.activePage?.()
      || document.querySelector('#nav button.active[data-page]')?.dataset.page) === PAGE;
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {
      cache: 'no-store',
      credentials: 'same-origin',
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

  function fmtTime(value) {
    const number = Number(value || 0);
    return number > 0 ? new Date(number).toLocaleString('ru-RU') : '—';
  }

  function fmtNumber(value, digits = 4) {
    const number = Number(value);
    return Number.isFinite(number)
      ? number.toLocaleString('ru-RU', { maximumFractionDigits: digits })
      : '—';
  }

  function badge(status) {
    const clean = String(status || 'unknown').toLowerCase();
    const cls = ['completed', 'ready', 'ok', 'eligible_for_manual_decision', 'approved'].includes(clean)
      ? 'ok'
      : ['running', 'scheduled', 'active', 'waiting_for_shadow_fills', 'deferred'].includes(clean)
        ? 'running'
        : 'blocked';
    return `<span class="campaign36-badge ${cls}">${esc(clean.toUpperCase())}</span>`;
  }

  function selectedCampaign(payload) {
    return payload?.active_campaign?.campaign_id
      ? payload.active_campaign
      : payload?.latest_campaign || {};
  }

  function campaignPanel(campaign) {
    if (!campaign || !campaign.campaign_id) {
      return `<article class="campaign36-card"><span>Активная кампания</span><strong>НЕТ</strong><small>Глобальный Testnet authorization свободен.</small></article>`;
    }
    const progress = campaign.progress || {};
    const integrity = campaign.identity_integrity || {};
    const fees = campaign.fees || {};
    const report = campaign.final_report || {};
    const failed = Array.isArray(campaign.failed_gates) ? campaign.failed_gates : [];
    return `<section class="campaign36-shell">
      <article class="campaign36-hero">
        <div><div class="campaign36-kicker">SELECTED TESTNET SHADOW CAMPAIGN</div><h2>${esc(campaign.campaign_id)}</h2><p>${esc(campaign.experiment_id || '—')} · ${esc(campaign.scope || '—')} · цикл ${Number(campaign.cycle_count || 0)}</p></div>
        ${badge(campaign.status)}
      </article>
      <section class="campaign36-grid">
        <article class="campaign36-card"><span>Fill progress</span><strong>${Number(progress.matched_fills || 0)} / ${Number(progress.target_fills || 20)}</strong><div class="campaign36-progress"><i style="width:${Math.max(0, Math.min(100, Number(progress.percent || 0)))}%"></i></div><small>Осталось: ${Number(progress.remaining_fills || 0)}</small></article>
        <article class="campaign36-card"><span>Actual fees</span><strong>${fmtNumber(fees.actual_fee_total, 8)}</strong><small>${fees.actual_execution_fees ? 'Фактические execution fees подтверждены' : 'Ожидается private execution evidence'}</small></article>
        <article class="campaign36-card"><span>Final report</span><strong>${report.generated ? 'ГОТОВ' : report.ready ? 'READY' : 'PENDING'}</strong><small>${esc(report.report_id || 'Автоматически после 20+ clean fills')}</small></article>
        <article class="campaign36-card"><span>Notional policy</span><strong>10–25 USDT</strong><small>Mainnet compiled out · manual promotion only</small></article>
      </section>
      <section class="campaign36-integrity">
        ${counter('Orphans', integrity.orphan_execution_count)}
        ${counter('Duplicates', integrity.duplicate_order_count)}
        ${counter('Unresolved', integrity.unresolved_order_count)}
      </section>
      ${failed.length ? `<div class="campaign36-alert"><b>Незакрытые gates:</b> ${failed.map(esc).join(', ')}</div>` : '<div class="campaign36-success">Campaign evidence gates не содержат ошибок идентичности.</div>'}
    </section>`;
  }

  function counter(label, value) {
    const number = Number(value || 0);
    return `<article class="campaign36-counter ${number === 0 ? 'ok' : 'bad'}"><span>${esc(label)}</span><b>${number}</b></article>`;
  }

  function schedulesTable(schedules) {
    const rows = (Array.isArray(schedules) ? schedules : []).map((item) => `<tr>
      <td><b>${esc(item.schedule_id || '—')}</b><div class="campaign36-muted">${esc(item.experiment_id || '—')}</div></td>
      <td>${esc(item.scope || '—')}</td>
      <td>${badge(item.status)}</td>
      <td>${Number(item.interval_seconds || 0)} сек.</td>
      <td>${fmtTime(item.next_run_at_ms)}</td>
      <td>${Number(item.run_count || 0)}</td>
      <td>${esc(item.last_error || item.last_deferred_reason || '—')}</td>
    </tr>`).join('');
    return `<article class="campaign36-table-wrap"><div class="campaign36-kicker">SCHEDULES</div><h3>Расписания Testnet campaigns</h3><table class="campaign36-table"><thead><tr><th>Schedule / Experiment</th><th>Scope</th><th>Status</th><th>Interval</th><th>Next run</th><th>Runs</th><th>Evidence</th></tr></thead><tbody>${rows || '<tr><td colspan="7">Расписаний пока нет.</td></tr>'}</tbody></table></article>`;
  }

  function gatesPanel(plan) {
    const gates = plan?.gates || {};
    const tags = Object.entries(gates).map(([name, passed]) => `<span class="campaign36-gate ${passed ? 'ok' : 'bad'}">${passed ? '✓' : '×'} ${esc(name)}</span>`).join('');
    const blockers = Array.isArray(plan?.blockers) ? plan.blockers : [];
    return `<article class="campaign36-card" style="grid-column:1/-1"><span>First Testnet release gates</span><div class="campaign36-gates">${tags || '<span class="campaign36-muted">Нет данных.</span>'}</div>${blockers.length ? `<small>Blocked: ${blockers.map(esc).join(', ')}</small>` : '<small>Все gates зелёные.</small>'}</article>`;
  }

  function launchPanel(plan) {
    return `<article class="campaign36-launch">
      <div class="campaign36-kicker">FIRST REAL TESTNET CAMPAIGN</div>
      <h3>Ограниченный Shadow Campaign</h3>
      <p>10–25 USDT на ордер, минимум 20 matched fills, zero orphan/duplicate/unresolved, actual fees и автоматический final report. UI не меняет runtime flags и не отключает kill switch.</p>
      <form id="campaign36LaunchForm" class="campaign36-form">
        <label>Promoted experiment ID<input id="campaign36Experiment" name="experiment_id" autocomplete="off" required placeholder="experiment_..."></label>
        <label>Scope<input id="campaign36Scope" name="scope" value="BTCUSDT" required></label>
        <label class="full">Точное подтверждение<input id="campaign36Confirmation" name="confirmation" autocomplete="off" required placeholder="${CONFIRMATION}"></label>
        <button id="campaign36Start" class="full" type="submit" ${state.busy ? 'disabled' : ''}>${state.busy ? 'Выполняю…' : 'Запустить bounded Testnet campaign'}</button>
      </form>
      <small>Required phrase: <code>${CONFIRMATION}</code></small>
      <p class="campaign36-muted">Текущий plan status: ${esc(plan?.status || 'unknown')}. Нужны green CI release gate, Testnet credentials, private order+execution stream, fill harvester, scheduler, kill switch off и отдельное promoted experiment approval.</p>
    </article>`;
  }

  function operationsPanel(payload, campaign) {
    const terminal = ['completed', 'blocked', 'cancelled'].includes(String(campaign?.status || ''));
    const canCycle = Boolean(campaign?.campaign_id) && !terminal;
    const report = campaign?.final_report || {};
    const canReport = String(campaign?.status || '') === 'completed' && !report.generated;
    return `<article class="campaign36-launch">
      <div class="campaign36-kicker">OPERATOR CONTROLS</div>
      <h3>Schedule, cycle и report operations</h3>
      <p>Все действия идут только через admin API и текущие canonical state machines. Raw order endpoint отсутствует.</p>
      <form id="campaign36ScheduleForm" class="campaign36-form">
        <label>Approved experiment ID<input id="campaign36ScheduleExperiment" required autocomplete="off" placeholder="experiment_..."></label>
        <label>Scope<input id="campaign36ScheduleScope" value="BTCUSDT" required></label>
        <label>Interval, seconds<input id="campaign36ScheduleInterval" type="number" min="60" max="86400" value="300" required></label>
        <button type="submit" ${state.busy ? 'disabled' : ''}>Создать schedule</button>
      </form>
      <div class="campaign37-actions">
        <button id="campaign36Tick" type="button" ${state.busy ? 'disabled' : ''}>Orchestrator tick</button>
        <button id="campaign36Cycle" type="button" ${state.busy || !canCycle ? 'disabled' : ''}>Run campaign cycle</button>
        <button id="campaign36Report" type="button" ${state.busy || !canReport ? 'disabled' : ''}>Generate final report</button>
        <button id="campaign36Refresh" type="button" ${state.busy ? 'disabled' : ''}>Refresh snapshot</button>
      </div>
      <small>Selected campaign: <code>${esc(campaign?.campaign_id || 'none')}</code> · auto-refresh ${REFRESH_MS / 1000}s · last update ${fmtTime(state.loadedAt)}</small>
      ${state.result ? `<div class="campaign36-success">${esc(state.result)}</div>` : ''}
      ${state.error ? `<div class="campaign36-alert">${esc(state.error)}</div>` : ''}
    </article>`;
  }

  function render() {
    if (!active()) return;
    const out = $('content');
    if (!out) return;
    const payload = state.payload || {};
    const campaign = selectedCampaign(payload);
    out.innerHTML = `<div class="title"><h1>Campaign Operations</h1><p>Расписания, Testnet execution evidence, fill integrity и final promotion readiness</p></div>
      <section class="campaign36-shell">
        <article class="campaign36-hero"><div><div class="campaign36-kicker">PHASE 7 CONTROL PLANE</div><h2>Bounded Testnet Evidence</h2><p>Single global authorization · actual private execution fees · automatic immutable report</p></div>${badge(payload.status || 'loading')}</article>
        <section class="campaign36-grid">
          <article class="campaign36-card"><span>Schedules</span><strong>${Number(payload.schedule_count || 0)}</strong><small>Enabled and deferred schedules</small></article>
          <article class="campaign36-card"><span>Campaigns</span><strong>${Number(payload.campaign_count || 0)}</strong><small>Immutable campaign records</small></article>
          <article class="campaign36-card"><span>Active authorization</span><strong>${Number(payload.active_campaign_count || 0)}</strong><small>Hard maximum: 1</small></article>
          <article class="campaign36-card"><span>Reports</span><strong>${Number(payload.report_count || 0)}</strong><small>Final promotion evidence</small></article>
          ${gatesPanel(payload.plan)}
        </section>
        ${campaignPanel(campaign)}
        ${schedulesTable(payload.schedules)}
        ${operationsPanel(payload, campaign)}
        ${launchPanel(payload.plan)}
      </section>`;
    bindControls(campaign);
  }

  function bindControls(campaign) {
    $('campaign36LaunchForm')?.addEventListener('submit', startCampaign);
    $('campaign36ScheduleForm')?.addEventListener('submit', createSchedule);
    $('campaign36Tick')?.addEventListener('click', tickOrchestrator);
    $('campaign36Cycle')?.addEventListener('click', () => runCampaignCycle(campaign?.campaign_id));
    $('campaign36Report')?.addEventListener('click', () => generateReport(campaign?.campaign_id));
    $('campaign36Refresh')?.addEventListener('click', () => load({ announce: true }));
  }

  async function load({ announce = false, quiet = false } = {}) {
    if (!active() || state.busy && quiet) return;
    if (!quiet) state.error = '';
    try {
      state.payload = await api('/api/campaigns/operations');
      state.loadedAt = Date.now();
      if (announce) state.result = 'Campaign Operations snapshot обновлён.';
    } catch (error) {
      state.error = `Campaign Operations API: ${error?.message || 'unknown error'}`;
    }
    render();
  }

  async function mutate(action) {
    if (state.busy) return;
    state.busy = true;
    state.error = '';
    state.result = '';
    render();
    try {
      state.result = await action();
      await load({ quiet: true });
    } catch (error) {
      state.error = error?.message || 'Операция заблокирована';
    } finally {
      state.busy = false;
      render();
    }
  }

  async function startCampaign(event) {
    event.preventDefault();
    const experiment = $('campaign36Experiment')?.value?.trim() || '';
    const scope = $('campaign36Scope')?.value?.trim() || 'BTCUSDT';
    const confirmation = $('campaign36Confirmation')?.value || '';
    await mutate(async () => {
      const result = await api('/api/campaigns/first-testnet/start', {
        method: 'POST',
        body: JSON.stringify({ experiment_id: experiment, scope, confirmation }),
      });
      return `Campaign started: ${result?.campaign?.campaign_id || 'created'}`;
    });
  }

  async function createSchedule(event) {
    event.preventDefault();
    const experimentId = $('campaign36ScheduleExperiment')?.value?.trim() || '';
    const scope = $('campaign36ScheduleScope')?.value?.trim() || 'BTCUSDT';
    const intervalSeconds = Number($('campaign36ScheduleInterval')?.value || 300);
    await mutate(async () => {
      const result = await api('/api/campaigns/schedules', {
        method: 'POST',
        body: JSON.stringify({
          experiment_id: experimentId,
          scope,
          interval_seconds: intervalSeconds,
          enabled: true,
        }),
      });
      return `Schedule created: ${result?.schedule?.schedule_id || 'created'}`;
    });
  }

  async function tickOrchestrator() {
    await mutate(async () => {
      const result = await api('/api/campaigns/orchestrator/tick', { method: 'POST' });
      const launched = Array.isArray(result?.launched_campaign_ids) ? result.launched_campaign_ids.length : 0;
      const updated = Array.isArray(result?.updated_campaign_ids) ? result.updated_campaign_ids.length : 0;
      return `Orchestrator tick: launched ${launched}, updated ${updated}.`;
    });
  }

  async function runCampaignCycle(campaignId) {
    if (!campaignId) return;
    await mutate(async () => {
      const result = await api(`/api/campaigns/${encodeURIComponent(campaignId)}/run`, { method: 'POST' });
      return `Campaign cycle complete: ${result?.campaign?.status || 'updated'}`;
    });
  }

  async function generateReport(campaignId) {
    if (!campaignId) return;
    await mutate(async () => {
      const result = await api(`/api/campaigns/${encodeURIComponent(campaignId)}/promotion-report`, { method: 'POST' });
      return `Final report: ${result?.report?.report_id || result?.report?.status || 'generated'}`;
    });
  }

  function startAutoRefresh() {
    if (state.timer) return;
    state.timer = window.setInterval(() => {
      if (active() && !state.busy) load({ quiet: true });
    }, REFRESH_MS);
  }

  function install() {
    const nav = $('nav');
    if (!nav) return;
    let button = nav.querySelector('[data-page="campaigns"]');
    if (!button) {
      button = document.createElement('button');
      button.type = 'button';
      button.dataset.page = PAGE;
      button.textContent = 'Кампании';
      const reports = nav.querySelector('[data-page="reports"]');
      nav.insertBefore(button, reports || null);
    }
    if (button.dataset.campaign36Installed === `v${VERSION}`) return;
    button.dataset.campaign36Installed = `v${VERSION}`;
    button.addEventListener('click', () => {
      nav.querySelectorAll('button[data-page]').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      history.replaceState(null, '', '#campaigns');
      render();
      load();
      startAutoRefresh();
    });
    if (location.hash === '#campaigns') button.click();
  }

  window.addEventListener('DOMContentLoaded', install);
  window.addEventListener('hashchange', () => {
    if (location.hash === '#campaigns') install();
  });
})();
