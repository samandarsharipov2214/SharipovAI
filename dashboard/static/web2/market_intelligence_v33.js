(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
  const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT'];
  const INTERVALS = [['1', '1м'], ['5', '5м'], ['15', '15м'], ['60', '1ч'], ['240', '4ч'], ['D', '1д']];
  const state = {
    tab: localStorage.getItem('sharipovai-mi-tab') || 'screener',
    snapshot: null,
    replay: null,
    replayCursor: 0,
    replayTimer: null,
    snapshotBusy: false,
    replayBusy: false,
    refreshTimer: null,
    observer: null,
    error: '',
  };

  function activeMarket() {
    const coordinator = window.SharipovAIPageCoordinator;
    return coordinator?.activePage
      ? coordinator.activePage() === 'market'
      : document.querySelector('#nav button.active[data-page="market"]') !== null;
  }

  async function get(url, timeoutMs = 15000) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally {
      clearTimeout(timeout);
    }
  }

  function number(value, digits = 2) {
    const parsed = Number(value);
    return Number.isFinite(parsed)
      ? parsed.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits })
      : '—';
  }

  function signed(value, digits = 2) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return '—';
    return `${parsed > 0 ? '+' : ''}${number(parsed, digits)}`;
  }

  function currentSymbol() {
    const selected = $('tv32Symbol')?.value;
    const saved = localStorage.getItem('sharipovai-market-symbol');
    const symbol = String(selected || saved || 'BTCUSDT').replace(/[^A-Za-z0-9]/g, '').toUpperCase();
    return SYMBOLS.includes(symbol) ? symbol : 'BTCUSDT';
  }

  function shell() {
    return `<section id="mi33" class="mi33-shell">
      <div class="mi33-head">
        <div><small>SHARIPOVAI MARKET INTELLIGENCE</small><h2>Отбор возможностей, предупреждения и проверка истории</h2><p>Система объясняет расчёты. Никакой модуль ниже не отправляет реальные ордера.</p></div>
        <div class="mi33-head-actions"><span id="mi33Status" class="mi33-status waiting">ЗАГРУЗКА</span><button id="mi33Refresh" class="action" type="button">Пересчитать</button></div>
      </div>
      <div class="mi33-tabs" role="tablist">
        <button type="button" data-mi-tab="screener" class="${state.tab === 'screener' ? 'active' : ''}">Умный скринер</button>
        <button type="button" data-mi-tab="alerts" class="${state.tab === 'alerts' ? 'active' : ''}">Оповещения <b id="mi33AlertCount">0</b></button>
        <button type="button" data-mi-tab="replay" class="${state.tab === 'replay' ? 'active' : ''}">Replay Lab</button>
      </div>
      <div id="mi33Body" class="mi33-body"></div>
    </section>`;
  }

  function ensureMounted() {
    if (!activeMarket()) return;
    if ($('mi33')) return;
    const anchor = document.querySelector('.tv32-terminal-panel');
    if (!anchor) return;
    anchor.insertAdjacentHTML('afterend', shell());
    bindShell();
    render();
    loadSnapshot();
  }

  function bindShell() {
    document.querySelectorAll('[data-mi-tab]').forEach((button) => button.addEventListener('click', () => {
      state.tab = ['screener', 'alerts', 'replay'].includes(button.dataset.miTab) ? button.dataset.miTab : 'screener';
      localStorage.setItem('sharipovai-mi-tab', state.tab);
      document.querySelectorAll('[data-mi-tab]').forEach((item) => item.classList.toggle('active', item.dataset.miTab === state.tab));
      render();
    }));
    $('mi33Refresh')?.addEventListener('click', () => loadSnapshot(true));
  }

  async function loadSnapshot(force = false) {
    if (!activeMarket() || state.snapshotBusy) return;
    state.snapshotBusy = true;
    state.error = '';
    setStatus('waiting', force ? 'ПЕРЕСЧЁТ' : 'ЗАГРУЗКА');
    try {
      const payload = await get(`/api/market-intelligence/snapshot${force ? `?t=${Date.now()}` : ''}`, 20000);
      state.snapshot = payload;
      if (payload.status === 'ok') setStatus('good', 'ГОТОВО');
      else setStatus('warn', 'ЧАСТИЧНО');
      rememberNewAlerts(payload.alerts || []);
    } catch (error) {
      state.error = error?.message || 'Скринер недоступен';
      setStatus('bad', 'ОШИБКА');
    } finally {
      state.snapshotBusy = false;
      render();
    }
  }

  function setStatus(className, text) {
    const status = $('mi33Status');
    if (!status) return;
    status.className = `mi33-status ${className}`;
    status.textContent = text;
  }

  function rememberNewAlerts(alerts) {
    let previous = [];
    try { previous = JSON.parse(localStorage.getItem('sharipovai-mi-seen-alerts') || '[]'); } catch {}
    const previousSet = new Set(Array.isArray(previous) ? previous : []);
    const important = alerts.filter((item) => ['critical', 'warning'].includes(item.severity));
    const newCount = important.filter((item) => !previousSet.has(item.id)).length;
    const badge = $('mi33AlertCount');
    if (badge) {
      badge.textContent = String(important.length);
      badge.classList.toggle('new', newCount > 0);
      badge.title = newCount ? `Новых: ${newCount}` : 'Новых предупреждений нет';
    }
    localStorage.setItem('sharipovai-mi-seen-alerts', JSON.stringify(important.map((item) => item.id).slice(0, 100)));
  }

  function render() {
    const body = $('mi33Body');
    if (!body) return;
    if (state.error && !state.snapshot) {
      body.innerHTML = `<div class="mi33-empty"><b>Данные не получены</b><span>${esc(state.error)}</span><button id="mi33Retry" class="action" type="button">Повторить</button></div>`;
      $('mi33Retry')?.addEventListener('click', () => loadSnapshot(true));
      return;
    }
    if (state.tab === 'alerts') renderAlerts(body);
    else if (state.tab === 'replay') renderReplay(body);
    else renderScreener(body);
  }

  function renderScreener(body) {
    const payload = state.snapshot;
    if (!payload) {
      body.innerHTML = '<div class="mi33-empty">Получение котировок и 15-минутных свечей по шести активам…</div>';
      return;
    }
    const summary = payload.summary || {};
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    body.innerHTML = `<div class="mi33-summary">
      ${metric('Проверено', `${summary.symbols_ready ?? 0}/${summary.symbols_total ?? 0}`, 'активов с полными данными')}
      ${metric('Сигналы', summary.signals ?? 0, 'BUY или SELL для анализа')}
      ${metric('Высокий риск', summary.high_risk ?? 0, 'не входить без дополнительной проверки', Number(summary.high_risk) ? 'negative' : '')}
      ${metric('Оповещения', summary.alerts ?? 0, 'важные изменения и позиции')}
    </div>
    <div class="mi33-note"><b>Как читать:</b> оценка ранжирует интересные рынки. Сигнал не открывает сделку автоматически. Причина каждого результата показана в последнем столбце.</div>
    <div class="mi33-table-wrap"><table class="mi33-table"><thead><tr><th>#</th><th>Пара</th><th>Цена</th><th>24ч</th><th>Тренд</th><th>RSI</th><th>Объём</th><th>Волатильность</th><th>Спред</th><th>Риск</th><th>Решение</th><th>Оценка</th><th>Почему</th></tr></thead><tbody>${rows.map((row, index) => screenerRow(row, index)).join('')}</tbody></table></div>
    <div class="mi33-foot">Источник: ${esc(payload.source || 'Bybit')} · метод: прозрачные правила · обновлено ${esc(formatTime(payload.generated_at))}</div>`;
    document.querySelectorAll('[data-mi-symbol]').forEach((row) => row.addEventListener('click', () => selectMarket(row.dataset.miSymbol)));
  }

  function screenerRow(row, index) {
    const statusReady = row.status === 'ready';
    const signal = String(row.signal || 'WAIT').toLowerCase();
    const risk = String(row.risk || 'HIGH').toLowerCase();
    return `<tr data-mi-symbol="${esc(row.symbol)}" class="${statusReady ? '' : 'unavailable'}" title="Нажми, чтобы открыть эту пару в терминале">
      <td>${index + 1}</td><td><b>${esc(String(row.symbol || '—').replace('USDT', '/USDT'))}</b></td>
      <td>${statusReady ? esc(number(row.price, Number(row.price) >= 100 ? 1 : 4)) : '—'}</td>
      <td class="${Number(row.change_24h_percent) >= 0 ? 'positive' : 'negative'}">${statusReady ? esc(`${signed(row.change_24h_percent)}%`) : '—'}</td>
      <td>${esc(row.trend_ru || '—')}</td><td>${statusReady ? esc(number(row.rsi14, 1)) : '—'}</td>
      <td>${statusReady ? `x${esc(number(row.volume_ratio, 2))}` : '—'}</td><td>${statusReady ? `${esc(number(row.volatility_percent, 3))}%` : '—'}</td>
      <td>${statusReady ? `${esc(number(row.spread_percent, 4))}%` : '—'}</td><td><span class="mi33-chip risk-${risk}">${esc(row.risk_ru || '—')}</span></td>
      <td><span class="mi33-chip signal-${signal}">${esc(row.signal_ru || '—')}</span></td><td><b>${esc(number(row.score, 1))}</b></td>
      <td class="mi33-reason">${esc(row.reason_ru || 'Причина не получена')}</td>
    </tr>`;
  }

  function selectMarket(symbol) {
    if (!SYMBOLS.includes(symbol)) return;
    const select = $('tv32Symbol');
    if (select) {
      select.value = symbol;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
    localStorage.setItem('sharipovai-market-symbol', symbol);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function renderAlerts(body) {
    const alerts = Array.isArray(state.snapshot?.alerts) ? state.snapshot.alerts : [];
    const critical = alerts.filter((item) => item.severity === 'critical').length;
    const warning = alerts.filter((item) => item.severity === 'warning').length;
    const info = alerts.filter((item) => item.severity === 'info').length;
    body.innerHTML = `<div class="mi33-summary">
      ${metric('Критические', critical, 'данные или позиция требуют внимания', critical ? 'negative' : '')}
      ${metric('Предупреждения', warning, 'повышенный рыночный риск', warning ? 'warning' : '')}
      ${metric('Информация', info, 'интересные сигналы и объёмы')}
      ${metric('Реальные ордера', 'ЗАБЛОКИРОВАНЫ', 'оповещения ничего не исполняют', 'positive')}
    </div>
    <div class="mi33-alert-list">${alerts.length ? alerts.map(alertCard).join('') : '<div class="mi33-empty">Сейчас важных оповещений нет.</div>'}</div>
    <div class="mi33-note">Оповещения формируются по спреду, волатильности, объёму, сильному движению и расстоянию открытых виртуальных позиций до стопа или цели.</div>`;
  }

  function alertCard(item) {
    const severity = ['critical', 'warning', 'info'].includes(item.severity) ? item.severity : 'info';
    const label = { critical: 'КРИТИЧНО', warning: 'ВНИМАНИЕ', info: 'ИНФОРМАЦИЯ' }[severity];
    return `<article class="mi33-alert ${severity}"><div><span>${label}</span><b>${esc(item.title || 'Оповещение')}</b></div><p>${esc(item.message || '')}</p><small>${esc(item.symbol || 'SYSTEM')} · ${esc(formatTime(item.created_at))}</small></article>`;
  }

  function renderReplay(body) {
    const symbol = state.replay?.symbol || currentSymbol();
    const interval = state.replay?.interval || '15';
    body.innerHTML = `<div class="mi33-replay-controls">
      <label>Пара<select id="mi33ReplaySymbol">${SYMBOLS.map((item) => `<option value="${item}" ${item === symbol ? 'selected' : ''}>${item.replace('USDT', '/USDT')}</option>`).join('')}</select></label>
      <label>Интервал<select id="mi33ReplayInterval">${INTERVALS.map(([value, label]) => `<option value="${value}" ${value === interval ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
      <label>Свечей<select id="mi33ReplayLimit"><option value="300">300</option><option value="500" selected>500</option><option value="800">800</option><option value="1000">1000</option></select></label>
      <button id="mi33RunReplay" class="action primary" type="button">Запустить проверку</button>
      <span id="mi33ReplayStatus" class="mi33-status ${state.replayBusy ? 'waiting' : 'good'}">${state.replayBusy ? 'РАСЧЁТ' : state.replay ? 'ГОТОВО' : 'НЕ ЗАПУЩЕНО'}</span>
    </div>
    <div class="mi33-note"><b>Replay Lab:</b> стратегия проходит по прошлым свечам без знания будущего. При одновременном касании цели и стопа первым считается стоп — это консервативное правило. Виртуальный счёт не изменяется.</div>
    <div id="mi33ReplayResult">${replayResultHtml()}</div>`;
    $('mi33RunReplay')?.addEventListener('click', runReplay);
    bindReplayPlayback();
    requestAnimationFrame(drawReplay);
  }

  async function runReplay() {
    if (state.replayBusy) return;
    stopReplay();
    state.replayBusy = true;
    const symbol = $('mi33ReplaySymbol')?.value || currentSymbol();
    const interval = $('mi33ReplayInterval')?.value || '15';
    const limit = $('mi33ReplayLimit')?.value || '500';
    render();
    try {
      const payload = await get(`/api/market-intelligence/replay?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&limit=${encodeURIComponent(limit)}`, 30000);
      if (payload.status !== 'ok') throw new Error(payload.error || 'Replay недоступен');
      state.replay = payload;
      state.replayCursor = Math.min(payload.candles?.length || 0, Math.max(40, Number(payload.strategy?.momentum_lookback_bars || 40)));
    } catch (error) {
      state.replay = { status: 'unavailable', error: error?.message || 'Replay недоступен', candles: [], trades: [], summary: {} };
      state.replayCursor = 0;
    } finally {
      state.replayBusy = false;
      render();
    }
  }

  function replayResultHtml() {
    const replay = state.replay;
    if (!replay) return '<div class="mi33-empty"><b>Историческая проверка ещё не запускалась.</b><span>Выбери пару, интервал и количество свечей.</span></div>';
    if (replay.status !== 'ok') return `<div class="mi33-empty"><b>Replay не выполнен</b><span>${esc(replay.error || 'Исторические данные недоступны')}</span></div>`;
    const summary = replay.summary || {};
    return `<div class="mi33-summary replay">
      ${metric('Сделок', summary.trade_count ?? 0, `${summary.wins ?? 0} побед · ${summary.losses ?? 0} убытков`)}
      ${metric('Win rate', `${number(summary.win_rate_percent, 1)}%`, 'доля прибыльных сделок')}
      ${metric('Net PnL', `${signed(summary.net_pnl, 2)} USDT`, `комиссии ${number(summary.total_fees, 2)} USDT`, Number(summary.net_pnl) >= 0 ? 'positive' : 'negative')}
      ${metric('Доходность', `${signed(summary.return_percent, 3)}%`, 'от стартовых 10 000 USDT', Number(summary.return_percent) >= 0 ? 'positive' : 'negative')}
      ${metric('Просадка', `${number(summary.max_drawdown_percent, 3)}%`, 'максимум по закрытым сделкам', Number(summary.max_drawdown_percent) > 3 ? 'negative' : '')}
      ${metric('Profit factor', number(summary.profit_factor, 2), 'прибыль / абсолютный убыток')}
    </div>
    <div class="mi33-playback">
      <button id="mi33ReplayReset" class="action" type="button">Сначала</button>
      <button id="mi33ReplayStep" class="action" type="button">Следующий шаг</button>
      <button id="mi33ReplayPlay" class="action primary" type="button">Воспроизвести</button>
      <button id="mi33ReplayPause" class="action" type="button">Пауза</button>
      <span id="mi33ReplayProgress">Свеча ${state.replayCursor} из ${replay.candles?.length || 0}</span>
    </div>
    <canvas id="mi33ReplayChart" height="420" aria-label="Историческое воспроизведение свечей"></canvas>
    <div class="mi33-replay-grid">
      <div><h3>Параметры стратегии</h3>${strategyRows(replay.strategy || {})}</div>
      <div><h3>Сделки до текущего шага</h3><div id="mi33ReplayTrades">${replayTradesHtml()}</div></div>
    </div>
    <div class="mi33-foot">Источник: ${esc(replay.source || 'Bybit')} · ${esc(replay.warning_ru || '')}</div>`;
  }

  function strategyRows(strategy) {
    return `<div class="mi33-kv"><span>Порог входа</span><b>${number(strategy.entry_threshold_percent, 2)}%</b></div>
      <div class="mi33-kv"><span>Take Profit</span><b>${number(strategy.take_profit_percent, 2)}%</b></div>
      <div class="mi33-kv"><span>Stop Loss</span><b>${number(strategy.stop_loss_percent, 2)}%</b></div>
      <div class="mi33-kv"><span>Максимум удержания</span><b>${strategy.max_hold_bars ?? '—'} свечей</b></div>
      <div class="mi33-kv"><span>Размер сделки</span><b>${number(strategy.notional_per_trade, 1)} USDT</b></div>
      <div class="mi33-kv"><span>Комиссия каждой стороны</span><b>${number(Number(strategy.fee_rate_each_side || 0) * 100, 2)}%</b></div>`;
  }

  function bindReplayPlayback() {
    $('mi33ReplayReset')?.addEventListener('click', () => { stopReplay(); state.replayCursor = Math.min(40, state.replay?.candles?.length || 0); updateReplayFrame(); });
    $('mi33ReplayStep')?.addEventListener('click', () => { stopReplay(); stepReplay(); });
    $('mi33ReplayPlay')?.addEventListener('click', playReplay);
    $('mi33ReplayPause')?.addEventListener('click', stopReplay);
  }

  function playReplay() {
    if (!state.replay?.candles?.length || state.replayTimer) return;
    state.replayTimer = setInterval(() => {
      if (!stepReplay()) stopReplay();
    }, 180);
  }

  function stopReplay() {
    if (state.replayTimer) clearInterval(state.replayTimer);
    state.replayTimer = null;
  }

  function stepReplay() {
    const total = state.replay?.candles?.length || 0;
    if (!total || state.replayCursor >= total) return false;
    state.replayCursor += 1;
    updateReplayFrame();
    return state.replayCursor < total;
  }

  function updateReplayFrame() {
    const progress = $('mi33ReplayProgress');
    if (progress) progress.textContent = `Свеча ${state.replayCursor} из ${state.replay?.candles?.length || 0}`;
    const trades = $('mi33ReplayTrades');
    if (trades) trades.innerHTML = replayTradesHtml();
    requestAnimationFrame(drawReplay);
  }

  function replayTradesHtml() {
    const replay = state.replay;
    if (!replay?.trades) return '<div class="mi33-empty">Нет сделок.</div>';
    const visible = replay.trades.filter((trade) => Number(trade.exit_index) < state.replayCursor).slice(-8).reverse();
    if (!visible.length) return '<div class="mi33-empty">До этого шага закрытых сделок нет.</div>';
    return visible.map((trade) => `<div class="mi33-replay-trade"><span>${esc(trade.side)} · ${esc(trade.close_reason_ru)}</span><b class="${Number(trade.net_pnl) >= 0 ? 'positive' : 'negative'}">${signed(trade.net_pnl, 2)} USDT</b><small>${number(trade.entry_price, 4)} → ${number(trade.exit_price, 4)} · комиссии ${number(trade.fees, 2)}</small></div>`).join('');
  }

  function drawReplay() {
    const canvas = $('mi33ReplayChart');
    const replay = state.replay;
    if (!canvas || replay?.status !== 'ok') return;
    const all = replay.candles || [];
    const cursor = Math.max(1, Math.min(state.replayCursor || all.length, all.length));
    const start = Math.max(0, cursor - 140);
    const candles = all.slice(start, cursor);
    const width = canvas.clientWidth || 900;
    const height = Number(canvas.getAttribute('height')) || 420;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const context = canvas.getContext('2d');
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);
    context.fillStyle = '#06131f';
    context.fillRect(0, 0, width, height);
    if (!candles.length) return;
    const padding = { left: 12, right: 76, top: 20, bottom: 28 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const low = Math.min(...candles.map((item) => Number(item.low)));
    const high = Math.max(...candles.map((item) => Number(item.high)));
    const range = high - low || 1;
    const y = (value) => padding.top + (high - value) / range * plotHeight;
    const step = plotWidth / candles.length;
    const bodyWidth = Math.max(2, step * 0.62);
    context.strokeStyle = '#173957';
    context.fillStyle = '#7891a7';
    context.font = '11px sans-serif';
    for (let line = 0; line < 6; line += 1) {
      const yy = padding.top + line * plotHeight / 5;
      context.beginPath(); context.moveTo(padding.left, yy); context.lineTo(width - padding.right, yy); context.stroke();
      context.fillText(number(high - line * range / 5, high >= 100 ? 1 : 4), width - padding.right + 7, yy + 4);
    }
    candles.forEach((item, localIndex) => {
      const x = padding.left + localIndex * step + step / 2;
      const up = Number(item.close) >= Number(item.open);
      context.strokeStyle = up ? '#3be08f' : '#ff7180';
      context.fillStyle = context.strokeStyle;
      context.beginPath(); context.moveTo(x, y(Number(item.high))); context.lineTo(x, y(Number(item.low))); context.stroke();
      const top = Math.min(y(Number(item.open)), y(Number(item.close)));
      context.fillRect(x - bodyWidth / 2, top, bodyWidth, Math.max(1, Math.abs(y(Number(item.open)) - y(Number(item.close)))));
    });
    const visibleTrades = (replay.trades || []).filter((trade) => Number(trade.entry_index) < cursor && Number(trade.exit_index) >= start);
    visibleTrades.forEach((trade) => {
      for (const [indexName, priceName, mark, color] of [['entry_index', 'entry_price', trade.side === 'BUY' ? 'B' : 'S', '#31d7ff'], ['exit_index', 'exit_price', 'X', '#f3c969']]) {
        const globalIndex = Number(trade[indexName]);
        if (globalIndex < start || globalIndex >= cursor) continue;
        const x = padding.left + (globalIndex - start) * step + step / 2;
        const yy = y(Number(trade[priceName]));
        context.fillStyle = color;
        context.beginPath(); context.arc(x, yy, 5, 0, Math.PI * 2); context.fill();
        context.fillStyle = '#06131f'; context.font = 'bold 8px sans-serif'; context.fillText(mark, x - 2.7, yy + 2.8);
      }
    });
  }

  function metric(label, value, note, tone = '') {
    return `<article class="card"><span>${esc(label)}</span><strong class="${esc(tone)}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
  }

  function formatTime(value) {
    const timestamp = Date.parse(value || '');
    return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString('ru-RU') : 'время не указано';
  }

  function start() {
    const content = $('content');
    if (content && !state.observer) {
      state.observer = new MutationObserver(() => setTimeout(ensureMounted, 0));
      state.observer.observe(content, { childList: true, subtree: false });
    }
    if (!state.refreshTimer) state.refreshTimer = setInterval(() => {
      if (activeMarket() && !document.hidden) loadSnapshot();
    }, 30000);
    ensureMounted();
  }

  document.addEventListener('click', (event) => {
    if (event.target.closest('#nav button[data-page="market"]')) setTimeout(start, 0);
  });
  window.addEventListener('resize', () => requestAnimationFrame(drawReplay));
  window.addEventListener('DOMContentLoaded', start);
})();
