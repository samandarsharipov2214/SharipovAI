(() => {
  const START_BALANCE = 10000;
  const fmt = (value) => Number(value || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const $ = (selector) => document.querySelector(selector);
  let lastEquity = START_BALANCE;
  let refreshInFlight = false;

  function setText(selector, value) {
    const element = $(selector);
    if (element) element.textContent = value;
  }

  function classByNumber(selector, value) {
    const element = $(selector);
    if (!element) return;
    element.classList.toggle('positive', Number(value) >= 0);
    element.classList.toggle('negative', Number(value) < 0);
  }

  function clock() {
    return new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function renderTrades(trades) {
    const table = document.querySelector('.mini-table tbody');
    if (!table) return;
    const rows = (trades || []).slice(-15).reverse();
    if (!rows.length) {
      table.innerHTML = '<tr><td>Виртуальных сделок пока нет</td><td>0.00</td></tr>';
      return;
    }
    table.innerHTML = rows.map((trade) => {
      const pnl = Number(trade.net_pnl ?? trade.pnl_usdt ?? 0);
      const fee = Number(trade.fee || 0);
      const opened = trade.opened_at ? new Date(Number(trade.opened_at) * 1000).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';
      const source = trade.source_ru || 'виртуальный счёт';
      return `<tr class="trade-clickable"><td><b>${trade.asset || trade.symbol || '—'} ${trade.side || ''}</b><br><small>${trade.status || 'OPEN'} · ${opened} · комиссия ${fmt(fee)} USDT · ${source}</small></td><td class="${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${fmt(pnl)}</td></tr>`;
    }).join('');
  }

  function equityFrom(state, summary) {
    const stateEquity = Number(state.equity);
    const summaryEquity = Number(summary.equity);
    const netPnl = Number(summary.net_pnl ?? 0);
    if (Number.isFinite(summaryEquity) && summaryEquity > 0) return summaryEquity;
    if (Number.isFinite(stateEquity) && stateEquity > 0) return stateEquity;
    return START_BALANCE + netPnl;
  }

  function protectEquityText() {
    const element = $('#portfolio-equity');
    if (!element || !Number.isFinite(lastEquity) || lastEquity <= 0) return;
    const current = Number(String(element.textContent || '').replace(/[^0-9,.-]/g, '').replace(',', '.'));
    if (!Number.isFinite(current) || current <= 0) {
      element.textContent = `${fmt(lastEquity)} USDT`;
    }
  }

  async function refreshVirtualAccount() {
    if (refreshInFlight) return;
    refreshInFlight = true;
    try {
      const response = await fetch('/api/virtual-account/state', { cache: 'no-store' });
      if (!response.ok) return;
      const payload = await response.json();
      const state = payload.state || {};
      const summary = state.summary || {};
      const netPnl = Number(summary.net_pnl ?? 0);
      const totalFees = Number(summary.total_fees ?? 0);
      const expectedOpen = Number(summary.expected_open_net_pnl ?? 0);
      const equity = equityFrom(state, summary);
      lastEquity = equity;

      setText('#portfolio-equity', `${fmt(equity)} USDT`);
      setText('#portfolio-pnl', `${netPnl >= 0 ? '+' : ''}${fmt(netPnl)} USDT`);
      classByNumber('#portfolio-pnl', netPnl);
      setText('#exchange-fees', `${fmt(totalFees)} USDT`);
      setText('#exchange-drag', `${fmt(totalFees)} USDT`);
      setText('#mini-report-day', `${netPnl >= 0 ? '+' : ''}${fmt(netPnl)} USDT`);
      setText('#mini-report-fees', `${fmt(totalFees)} USDT`);
      setText('#overview-exchange', 'Виртуальный счёт');
      setText('#exchange-mode', 'Virtual Account');
      setText('#exchange-live', 'Заблокировано');
      setText('#hero-decision-mini', summary.last_tick_status === 'blocked' ? 'WAIT/BLOCK' : 'VIRTUAL');
      setText('#mini-paper-last-refresh', `${clock()} · ${summary.last_reason_ru || summary.last_reason || 'virtual account updated'} · trades ${summary.trade_count || 0}`);
      setText('#exchange-preview', `Ожидаемая открытая позиция: ${expectedOpen >= 0 ? '+' : ''}${fmt(expectedOpen)} USDT`);
      renderTrades(state.trades || []);
    } catch (_) {
      protectEquityText();
    } finally {
      refreshInFlight = false;
    }
  }

  window.addEventListener('DOMContentLoaded', () => {
    refreshVirtualAccount();
    const equityNode = $('#portfolio-equity');
    if (equityNode && window.MutationObserver) {
      new MutationObserver(protectEquityText).observe(equityNode, { childList: true, characterData: true, subtree: true });
    }
    setInterval(refreshVirtualAccount, 5000);
  });
})();
