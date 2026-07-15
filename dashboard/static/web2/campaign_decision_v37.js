(() => {
  'use strict';

  const VERSION = 37;
  const PAGE = 'campaigns';
  const state = { campaignId: '', payload: null, busy: false, error: '', success: '' };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

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
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload?.detail?.message || payload?.detail || payload?.message || `HTTP ${response.status}`;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return payload;
  }

  function statusClass(value) {
    const clean = String(value || 'report_pending').toLowerCase();
    return ['approved', 'rejected', 'blocked', 'awaiting_manual_decision'].includes(clean)
      ? clean
      : '';
  }

  function panelHost() {
    const shell = document.querySelector('#content .campaign36-shell');
    if (!shell) return null;
    let panel = document.getElementById('campaign37Panel');
    if (!panel) {
      panel = document.createElement('section');
      panel.id = 'campaign37Panel';
      panel.className = 'campaign37-panel';
      shell.append(panel);
    }
    return panel;
  }

  function render() {
    if (!active()) return;
    const panel = panelHost();
    if (!panel) return;
    const payload = state.payload || {};
    const decision = payload.decision || {};
    const decided = Boolean(decision.decision_id);
    const eligible = Boolean(payload.eligible_for_approval);
    const status = decided ? decision.status : payload.status || 'report_pending';
    const disabled = state.busy || decided || !payload.report_id;

    panel.innerHTML = `
      <div class="campaign37-head">
        <div>
          <div class="campaign37-kicker">IMMUTABLE PROMOTION DECISION · V${VERSION}</div>
          <h3>Ручное решение по final report</h3>
          <p>Решение фиксирует evidence и владельца. Оно не включает Testnet/Mainnet, не меняет капитал и не развёртывает стратегию.</p>
        </div>
        <span class="campaign37-state ${statusClass(status)}">${esc(String(status).toUpperCase())}</span>
      </div>
      <div class="campaign37-grid">
        <div class="campaign37-fact"><span>Campaign</span><b>${esc(payload.campaign_id || state.campaignId || '—')}</b></div>
        <div class="campaign37-fact"><span>Final report</span><b>${esc(payload.report_id || 'PENDING')}</b></div>
        <div class="campaign37-fact"><span>Approval eligibility</span><b>${eligible ? 'AUTOMATED GATES PASSED' : 'BLOCKED / PENDING'}</b></div>
      </div>
      ${decided ? `
        <div class="${decision.approved ? 'campaign37-ok' : 'campaign37-alert'}">
          <b>${decision.approved ? 'APPROVED' : 'REJECTED'}</b> · ${esc(decision.actor || '—')} · ${esc(decision.reason || '—')}
          <br><small>Evidence SHA-256: ${esc(decision.evidence_sha256 || '—')}</small>
        </div>` : `
        <form id="campaign37Form" class="campaign37-form">
          <label>Причина решения<textarea id="campaign37Reason" rows="3" required placeholder="Укажи, какие actual fills, fees и identity gates проверены."></textarea></label>
          <label>Exact approval/rejection token<input id="campaign37Token" required autocomplete="off" placeholder="Вставь точный token из панели ниже"></label>
          <div class="campaign37-actions">
            <button type="button" class="campaign37-approve" data-campaign37-action="approve" ${disabled || !eligible ? 'disabled' : ''}>Подтвердить report</button>
            <button type="button" class="campaign37-reject" data-campaign37-action="reject" ${disabled ? 'disabled' : ''}>Отклонить report</button>
          </div>
        </form>
        <div class="campaign37-note">
          Approve token: <code>${esc(payload.approval_token || 'report pending')}</code><br>
          Reject token: <code>${esc(payload.rejection_token || 'report pending')}</code>
        </div>`}
      ${state.success ? `<div class="campaign37-ok">${esc(state.success)}</div>` : ''}
      ${state.error ? `<div class="campaign37-alert">${esc(state.error)}</div>` : ''}`;

    panel.querySelectorAll('[data-campaign37-action]').forEach((button) => {
      button.addEventListener('click', () => submit(button.dataset.campaign37Action === 'approve'));
    });
  }

  async function load() {
    if (!active()) return;
    state.error = '';
    try {
      const operations = await api('/api/campaigns/operations');
      const campaign = operations.active_campaign?.campaign_id
        ? operations.active_campaign
        : operations.latest_campaign;
      state.campaignId = String(campaign?.campaign_id || '');
      if (!state.campaignId) {
        state.payload = {
          status: 'report_pending', campaign_id: '', report_id: '',
          eligible_for_approval: false, decision: {}, approval_token: '', rejection_token: '',
        };
      } else {
        state.payload = await api(`/api/campaigns/${encodeURIComponent(state.campaignId)}/decision`);
      }
    } catch (error) {
      state.error = error?.message || 'Manual decision API unavailable';
    }
    render();
  }

  async function submit(approve) {
    if (state.busy || !state.campaignId) return;
    const reason = document.getElementById('campaign37Reason')?.value?.trim() || '';
    const approvalToken = document.getElementById('campaign37Token')?.value || '';
    if (!reason || !approvalToken) {
      state.error = 'Причина и exact token обязательны.';
      render();
      return;
    }
    state.busy = true;
    state.error = '';
    state.success = '';
    render();
    try {
      const result = await api(`/api/campaigns/${encodeURIComponent(state.campaignId)}/decision`, {
        method: 'POST',
        body: JSON.stringify({ approve, reason, approval_token: approvalToken }),
      });
      state.success = `Immutable decision saved: ${result?.decision?.status || 'decided'}`;
      state.payload = await api(`/api/campaigns/${encodeURIComponent(state.campaignId)}/decision`);
    } catch (error) {
      state.error = error?.message || 'Решение заблокировано';
    } finally {
      state.busy = false;
      render();
    }
  }

  let scheduled = false;
  function scheduleLoad() {
    if (scheduled || !active()) return;
    scheduled = true;
    setTimeout(() => {
      scheduled = false;
      load();
    }, 50);
  }

  document.addEventListener('click', (event) => {
    if (event.target.closest('#nav button[data-page="campaigns"]')) scheduleLoad();
  });
  window.addEventListener('hashchange', scheduleLoad);
  window.addEventListener('DOMContentLoaded', scheduleLoad);

  const observer = new MutationObserver(() => {
    if (active() && document.querySelector('#content .campaign36-shell') && !document.getElementById('campaign37Panel')) {
      scheduleLoad();
    }
  });
  window.addEventListener('DOMContentLoaded', () => {
    const content = document.getElementById('content');
    if (content) observer.observe(content, { childList: true, subtree: true });
  });
})();
