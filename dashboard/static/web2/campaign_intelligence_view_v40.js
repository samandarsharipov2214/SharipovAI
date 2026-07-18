(() => {
  'use strict';
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = (value, digits = 3) => Number.isFinite(Number(value)) ? Number(value).toLocaleString('ru-RU', {maximumFractionDigits: digits}) : '—';
  const active = () => document.querySelector('#nav button.active[data-page="campaigns"]');
  let latest = {};

  function host() {
    const shell = document.querySelector('#content .campaign36-shell');
    if (!shell) return null;
    let node = document.getElementById('phase8IntelligencePanel');
    if (!node) {
      node = document.createElement('section');
      node.id = 'phase8IntelligencePanel';
      node.className = 'p8-shell';
      shell.append(node);
    }
    return node;
  }

  function render() {
    if (!active()) return;
    const node = host();
    if (!node) return;
    const monitor = latest.monitor || {};
    const analysis = latest.analysis || {};
    const execution = analysis.execution || {};
    const divergence = analysis.divergence || {};
    const drawdown = analysis.drawdown || latest.drawdown || {};
    const recommendation = analysis.recommendation || latest.recommendation || {};
    const gates = Object.entries(analysis.gates || {}).map(([name, passed]) => `<span class="p8-gate ${passed ? 'ok' : 'bad'}">${passed ? 'PASS' : 'FAIL'} · ${esc(name)}</span>`).join('');
    const alerts = [
      ...(latest.alerts || []),
      ...(latest.critical_alerts?.open_alerts || []).map((row) => row.code || row.title),
      ...(latest.phase8_risk_alerts?.open_alerts || []).map((row) => row.code || row.title),
    ];
    node.innerHTML = `<article class="p8-hero"><div><small>PHASE 8 LIVE</small><h2>${esc(latest.campaign_id || 'Campaign control plane')}</h2><p>sequence ${Number(latest.sequence || 0)} · ${esc(latest.status || 'idle')}</p></div><b>${esc(recommendation.action || 'PENDING')}</b></article><section class="p8-metrics"><article><span>Actual fills</span><b>${Number(execution.actual_private_fill_count ?? monitor.actual_fill_count ?? 0)}</b></article><article><span>Notional</span><b>${num(execution.executed_notional_usdt)} USDT</b></article><article><span>Fees</span><b>${num(execution.actual_fee_total ?? monitor.actual_fee_total, 8)}</b></article><article class="${drawdown.breached ? 'danger' : ''}"><span>Drawdown</span><b>${num(drawdown.observed_drawdown_percent ?? drawdown.percent, 4)}%</b></article><article><span>P95 slippage</span><b>${num(divergence.p95_slippage_divergence_bps)} bps</b></article><article><span>Heartbeat</span><b>${monitor.heartbeat_stale ? 'STALE' : 'LIVE'}</b></article></section><article class="p8-card"><h3>Recommendation</h3><b>${esc(recommendation.action || 'PENDING')}</b><p>${esc(recommendation.reason || 'Waiting for terminal evidence.')}</p><small>Manual review remains required.</small></article><article class="p8-card"><h3>Quality gates</h3><div class="p8-gates">${gates || 'Pending'}</div></article><article class="p8-card"><h3>Alerts</h3>${alerts.length ? alerts.map((value) => `<div class="p8-alert">${esc(value)}</div>`).join('') : '<div class="p8-good">No active alerts.</div>'}</article>`;
  }

  window.addEventListener('phase8data', (event) => {
    latest = event.detail || {};
    render();
  });
  document.addEventListener('click', (event) => {
    if (event.target?.closest?.('#nav button[data-page="campaigns"]')) setTimeout(() => window.SharipovAIPhase8Client?.refresh(), 120);
  });
  new MutationObserver(() => {
    if (active() && latest.campaign_id && !document.getElementById('phase8IntelligencePanel')) render();
  }).observe(document.documentElement, {childList: true, subtree: true});
})();
