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
      profitability_gate_wait: 'нет преимущества — вход пропущен',
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

  function appendLine(container, text) {
    if (container.childNodes.length) container.appendChild(document.createElement('br'));
    container.appendChild(document.createTextNode(text));
  }

  function createStat(label, id, value) {
    const item = document.createElement('div');
    item.className = 'mini-stat';
    const small = document.createElement('small');
    small.textContent = label;
    const strong = document.createElement('b');
    strong.id = id;
    strong.textContent = value;
    item.append(small, strong);
    return item;
  }

  function renderAllTrades(state) {
    const table = document.querySelector('.mini-table tbody');
    const section = document.getElementById('trades-section');
    if (!table || !section) return;

    const trades = Array.isArray(state.trades) ? state.trades : [];
    const summary = state.summary || {};
    const profitGate = summary.last_profitability_gate || {};
    ensureTradeSummary(section);
    setText('#all-trades-count', String(trades.length));
    setText('#all-trades-open', String(summary.open_positions || trades.filter((t) => t.status === 'OPEN').length));
    setText('#all-trades-closed', String(summary.closed_positions || trades.filter((t) => t.status === 'CLOSED').length));
    setText('#all-trades-skipped', String(summary.skipped_count || 0));
    setText('#all-trades-profitable', `${summary.profitable_closed || 0}/${summary.closed_positions || 0}`);
    setText('#all-trades-pnl', `${summary.net_pnl >= 0 ? '+' : ''}${fmt(summary.net_pnl)} USDT`);
    setText('#all-trades-reason', reasonRu(summary.last_reason, summary.last_reason_ru));
    setText('#all-trades-profit-gate', profitGate.reason_ru || 'ожидаю следующий сигнал');
    setText('#all-trades-last-tick', summary.last_tick_at ? `${fmtTime(summary.last_tick_at)} · ${ageText(summary.last_tick_at)}` : '—');

    table.replaceChildren();
    if (!trades.length) {
      const tr = document.createElement('tr');
      const message = document.createElement('td');
      const pnl = document.createElement('td');
      message.textContent = 'Сделок пока нет. Это может быть правильно, если Profitability Gate не видит преимущества.';
      pnl.textContent = '0.00';
      tr.append(message, pnl);
      table.appendChild(tr);
      return;
    }

    trades.slice().reverse().forEach((trade, index) => {
      const pnl = Number(trade.net_pnl ?? trade.pnl_usdt ?? 0);
      const fee = Number(trade.fee || 0);
      const opened = fmtTime(trade.opened_at);
      const closed = trade.closed_at ? fmtTime(trade.closed_at) : 'ещё открыта';
      const age = ageText(trade.opened_at);
      const duration = durationText(trade.opened_at, trade.closed_at);
      const expected = Number(trade.expected_net_usdt || 0);
      const edgeRatio = Number(trade.edge_to_fee_ratio || 0);
      const tr = document.createElement('tr');
      tr.className = 'trade-clickable all-trade-row';
      tr.dataset.tradeId = String(trade.id || '');

      const details = document.createElement('td');
      const title = document.createElement('b');
      title.textContent = `#${trades.length - index} · ${String(trade.asset || trade.symbol || 'UNKNOWN')} ${String(trade.side || '')}`;
      const small = document.createElement('small');
      appendLine(small, `${statusRu(trade.status)} · комиссия ${fmt(fee)} USDT · ${sourceRu(trade.source, trade.source_ru)}`);
      appendLine(small, `ожидание: ${expected >= 0 ? '+' : ''}${fmt(expected)} USDT · edge/fee ${edgeRatio.toFixed(2)}x`);
      appendLine(small, `🕒 открыта: ${opened} · ${age}`);
      appendLine(small, `⏱ длительность: ${duration}`);
      appendLine(small, `🏁 закрыта: ${closed}`);
      details.append(title, document.createElement('br'), small);

      const pnlCell = document.createElement('td');
      pnlCell.className = pnl >= 0 ? 'positive' : 'negative';
      pnlCell.textContent = `${pnl >= 0 ? '+' : ''}${fmt(pnl)}`;

      tr.append(details, pnlCell);
      table.appendChild(tr);
    });
  }

  function ensureTradeSummary(section) {
    if (document.getElementById('all-trades-summary')) return;
    const box = document.createElement('div');
    box.id = 'all-trades-summary';
    box.className = 'mini-grid';
    box.append(
      createStat('Всего сделок', 'all-trades-count', '0'),
      createStat('Открыты', 'all-trades-open', '0'),
      createStat('Закрыты', 'all-trades-closed', '0'),
      createStat('Пропущено плохих входов', 'all-trades-skipped', '0'),
      createStat('Прибыльных закрытий', 'all-trades-profitable', '0/0'),
      createStat('Net PnL', 'all-trades-pnl', '0.00 USDT'),
      createStat('Последний цикл', 'all-trades-last-tick', '—'),
      createStat('Причина', 'all-trades-reason', '—'),
      createStat('Profitability Gate', 'all-trades-profit-gate', '—'),
    );
    const title = section.querySelector('h2');
    if (title) title.insertAdjacentElement('afterend', box);

    const hint = section.querySelector('.info-box');
    if (hint) {
      const strong = document.createElement('b');
      strong.textContent = 'Новая логика:';
      const link = document.createElement('a');
      link.href = '/api/paper-activity/state';
      link.textContent = '/api/paper-activity/state';
      hint.replaceChildren(
        strong,
        document.createTextNode(' сделка открывается только если ожидаемое преимущество больше комиссии и риска. Если преимущества нет — вход пропускается, чтобы не делать минус ради количества. Полный JSON: '),
        link,
        document.createTextNode('.'),
      );
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