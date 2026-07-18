(() => {
  'use strict';
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = (v, digits=2) => Number.isFinite(Number(v)) ? Number(v).toFixed(digits) : '—';
  async function loadPhase9(campaignId) {
    if (!campaignId) return;
    const [reportResponse, planResponse] = await Promise.all([
      fetch(`/api/campaigns/phase9/report/${encodeURIComponent(campaignId)}`, {credentials:'same-origin'}),
      fetch('/api/campaigns/phase9/scaling-plans?limit=5', {credentials:'same-origin'})
    ]);
    if (!reportResponse.ok) return;
    const report = await reportResponse.json();
    const plans = planResponse.ok ? (await planResponse.json()).plans || [] : [];
    const host = document.querySelector('[data-phase9-scaling]');
    if (!host) return;
    const risk = report.risk_metrics || {};
    const latest = plans[0] || {};
    host.innerHTML = `<section class="phase9-grid">
      <article><small>Net PnL</small><b>${number((report.pnl||{}).net_realized_pnl_usdt,4)} USDT</b></article>
      <article><small>Profit factor</small><b>${esc(risk.profit_factor ?? '—')}</b></article>
      <article><small>Win rate</small><b>${number(Number(risk.win_rate||0)*100,1)}%</b></article>
      <article><small>Max drawdown</small><b>${number(risk.maximum_drawdown_bps,1)} bps</b></article>
      <article><small>Scaling status</small><b>${esc(latest.status || 'not prepared')}</b></article>
      <article><small>Proposed notional</small><b>${number(latest.proposed_next_notional_usdt,2)} USDT</b></article>
    </section>`;
  }
  window.SharipovAIPhase9 = {load: loadPhase9};
})();
