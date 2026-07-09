(() => {
  const fmt = (value) => Number(value || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const $ = (selector) => document.querySelector(selector);

  function setText(selector, value) {
    const el = $(selector);
    if (el) el.textContent = value;
  }

  function fmtTime(seconds) {
    if (!seconds) return '—';
    return new Date(Number(seconds) * 1000).toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  }

  function ageText(seconds) {
    if (!seconds) return '—';
    const diff = Math.max(0, Math.round((Date.now() - Number(seconds) * 1000) / 1000));
    if (diff < 60) return `${diff} сек назад`;
    if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
    return `${Math.floor(diff / 86400)} дн назад`;
  }

  function durationText(openedAt, closedAt) {
    if (!openedAt) return '—';
    const end = closedAt ? Number(closedAt) : Math.floor(Date.now() / 1000);
    const diff = Math.max(0, end - Number(openedAt));
    if (diff < 60) return `${diff} сек`;
    if (diff < 3600) return `${Math.floor(diff / 60)} мин`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} ч ${Math.floor((diff % 3600) / 60)} мин`;
    return `${Math.floor(diff / 86400)} дн ${Math.floor((diff % 86400) / 3600)} ч`;
  }

  function reasonRu(reason, fallback) {
    if (fallback) return fallback;
    const raw = String(reason || 'ok');
    if (raw.startsWith('catch_up_completed:')) return `догнал пропущенные циклы: ${raw.split(':')[1].replace('_ticks', '')}`;
    if (raw.startsWith('bootstrap_completed:')) return `восстановлена история после пустого состояния: ${raw.split(':')[1].replace('_ticks', '')} виртуальных циклов`;
    if (raw.startsWith('waiting_interval:')) return `ждёт следующий цикл: ${raw.split(':')[1].replace('s_left', '')} сек`;
    const map = {
      opened_virtual_trade: 'открыта виртуальная сделка',
      opened_paper_trade: 'открыта виртуальная сделка',
      max_open_reached_closed_oldest: 'достигнут лимит открытых сделок — закрыта самая старая',
      trade_gate_blocked_virtual_execution: 'Trade Gate заблокировал виртуальную сделку',
      not_started: 'ещё не запускался',
      ok: 'работает',
    };
    return map[raw] || raw;
  }

  function sourceRu(source, fallback) {
    if (fallback) return fallback;
    const map = {
      virtual_account_execution_engine: 'виртуальный счёт',
      paper_activity_engine: 'виртуальный счёт',
      paper: 'виртуальный счёт',
    };
    return map[String(source || 'paper')] || String(source || 'виртуальный счёт');
  }

  function statusRu(status) {
    const map = { OPEN: 'открыта', CLOSED: 'закрыта' };
    return map[String(status || 'OPEN').toUpperCase()] || String(status || 'открыта');
  }

  function renderAllTrades(state) {
    const table = document.querySelector('.mini-table tbody');
    const section = document.getElementById('trades-section');
    if (!table || !section) return;

    const trades = Array.isArray(state.trades) ? state.trades : [];
    const summary = state.summary || {};
    ensureTradeSummary(section);
    setText('#all-trades-count', String(trades.length));
    setText('#all-trades-open', String(summary.open_positions || trades.filter((t) => t.status === 'OPEN').length));
    setText('#all-trades-closed', String(summary.closed_positions || trades.filter((t) => t.status === 'CLOSED').length));
    setText('#all-trades-pnl', `${summary.net_pnl >= 0 ? '+' : ''}${fmt(summary.net_pnl)} USDT`);
    setText('#all-trades-reason', reasonRu(summary.last_reason, summary.last_reason_ru));
    setText('#all-trades-last-tick', summary.last_tick_at ? `${fmtTime(summary.last_tick_at)} · ${ageText(summary.last_tick_at)}` : '—');

    table.innerHTML = '';
    if (!trades.length) {
      table.innerHTML = '<tr><td>Сделок пока нет</td><td>0.00</td></tr>';
      return;
    }

    trades.slice().reverse().forEach((trade, index) => {
      const pnl = Number(trade.net_pnl ?? trade.pnl_usdt ?? 0);
      const fee = Number(trade.fee || 0);
      const opened = fmtTime(trade.opened_at);
      const closed = trade.closed_at ? fmtTime(trade.closed_at) : 'ещё открыта';
      const age = ageText(trade.opened_at);
      const duration = durationText(trade.opened_at, trade.closed_at);
      const tr = document.createElement('tr');
      tr.className = 'trade-clickable all-trade-row';
      tr.dataset.tradeId = trade.id || '';
      tr.innerHTML = `<td><b>#${trades.length - index} · ${trade.asset || trade.symbol || 'UNKNOWN'} ${trade.side || ''}</b><br><small>${statusRu(trade.status)} · комиссия ${fmt(fee)} USDT · ${sourceRu(trade.source, trade.source_ru)}<br>🕒 открыта: ${opened} · ${age}<br>⏱ длительность: ${duration}<br>🏁 закрыта: ${closed}</small></td><td class="${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${fmt(pnl)}</td>`;
      table.appendChild(tr);
    });
  }

  function ensureTradeSummary(section) {
    if (document.getElementById('all-trades-summary')) return;
    const box = document.createElement('div');
    box.id = 'all-trades-summary';
    box.className = 'mini-grid';
    box.innerHTML = `<div class="mini-stat"><small>Всего сделок</small><b id="all-trades-count">0</b></div><div class="mini-stat"><small>Открыты</small><b id="all-trades-open">0</b></div><div class="mini-stat"><small>Закрыты</small><b id="all-trades-closed">0</b></div><div class="mini-stat"><small>Net PnL</small><b id="all-trades-pnl">0.00 USDT</b></div><div class="mini-stat"><small>Последний цикл</small><b id="all-trades-last-tick">—</b></div><div class="mini-stat"><small>Причина</small><b id="all-trades-reason">—</b></div>`;
    const title = section.querySelector('h2');
    if (title) title.insertAdjacentElement('afterend', box);

    const hint = section.querySelector('.info-box');
    if (hint) {
      hint.innerHTML = 'Показаны <b>все виртуальные сделки</b> с временем открытия, закрытия и длительностью. Полный JSON: <a href="/api/paper-activity/state">/api/paper-activity/state</a>. Нажми на сделку, чтобы открыть отчёт.';
    }
  }

  async function loadAllTrades() {
    try {
      const response = await fetch('/api/paper-activity/state', { cache: 'no-store' });
      if (!response.ok) return;
      const payload = await response.json();
      renderAllTrades(payload.state || {});
    } catch (_) {}
  }

  window.addEventListener('DOMContentLoaded', () => {
    loadAllTrades();
    setInterval(loadAllTrades, 15000);
  });
})();
