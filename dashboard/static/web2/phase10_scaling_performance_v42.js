(() => {
  const ROOT = '[data-phase10-scaling-performance]';
  const money = value => Number(value || 0).toFixed(2);
  const number = value => Number(value || 0).toFixed(2);
  const render = async () => {
    const root = document.querySelector(ROOT);
    if (!root || document.hidden) return;
    try {
      const [activationResponse, performanceResponse] = await Promise.all([
        fetch('/api/campaigns/phase10/activations?limit=20', { credentials: 'same-origin' }),
        fetch('/api/performance/phase10/overview', { credentials: 'same-origin' })
      ]);
      if (!activationResponse.ok || !performanceResponse.ok) throw new Error('Phase 10 API unavailable');
      const activationPayload = await activationResponse.json();
      const performancePayload = await performanceResponse.json();
      const activations = activationPayload.activations || [];
      const monthly = performancePayload.monthly_reports || [];
      const active = activations.find(item => item.status === 'active');
      const latest = monthly[0] || {};
      root.innerHTML = `
        <section class="phase10-panel">
          <header><div><small>PHASE 10</small><h2>Scaling & Performance</h2></div><span class="phase10-badge ${active ? 'active' : 'locked'}">${active ? 'ACTIVE TESTNET SCALE' : 'SCALING LOCKED'}</span></header>
          <div class="phase10-grid">
            <article><small>Authorized notional</small><strong>${money(active && active.authorized_notional_usdt)} USDT</strong><span>${active ? active.scope : 'No active authority'}</span></article>
            <article><small>Monthly net PnL</small><strong>${money(latest.net_pnl_usdt)} USDT</strong><span>${latest.month || 'No report'}</span></article>
            <article><small>Monthly fees</small><strong>${money(latest.fees_usdt)} USDT</strong><span>${latest.matched_fill_count || 0} matched fills</span></article>
            <article><small>Maximum drawdown</small><strong>${number(latest.maximum_drawdown_bps)} bps</strong><span>${latest.drawdown_alert ? 'ALERT' : 'Within policy'}</span></article>
          </div>
          <div class="phase10-truth">Mainnet remains unavailable. Scaling authority is expiring, Testnet-only and cannot bypass the kill switch.</div>
        </section>`;
    } catch (error) {
      root.innerHTML = `<section class="phase10-panel error"><h2>Scaling & Performance</h2><p>${String(error.message || error)}</p></section>`;
    }
  };
  document.addEventListener('DOMContentLoaded', render);
  document.addEventListener('visibilitychange', render);
  setInterval(render, 10000);
})();
