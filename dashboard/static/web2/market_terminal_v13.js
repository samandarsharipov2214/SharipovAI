(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const num = (value, digits = 8) => Number.isFinite(Number(value))
    ? Number(value).toLocaleString('ru-RU', { maximumFractionDigits: digits })
    : '—';

  const QUOTE_REFRESH_MS = 1000;
  const BOOK_REFRESH_MS = 3000;
  const CANDLE_REFRESH_MS = 10000;
  const CONTEXT_REFRESH_MS = 30000;
  const symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT'];
  const intervals = [['1', '1м'], ['5', '5м'], ['15', '15м'], ['60', '1ч'], ['240', '4ч'], ['D', '1д']];

  function savedSymbol() {
    let candidate = localStorage.getItem('sharipovai-market-symbol') || '';
    try {
      const settings = JSON.parse(localStorage.getItem('sharipovai-settings') || '{}');
      candidate ||= settings.defaultSymbol || '';
    } catch {}
    candidate = String(candidate).replace(/[^A-Za-z0-9]/g, '').toUpperCase();
    return symbols.includes(candidate) ? candidate : 'BTCUSDT';
  }

  const state = {
    symbol: savedSymbol(), interval: '15', quote: null, candles: [], orderbook: null,
    trades: [], news: [], run: null, quoteError: '', quoteTransport: '',
    quoteBusy: false, bookBusy: false, candleBusy: false, contextBusy: false,
    quoteTimer: null, bookTimer: null, candleTimer: null, contextTimer: null,
    displayedPrice: null, showSma7: true, showSma25: true,
  };

  function activeMarket() {
    const coordinator = window.SharipovAIPageCoordinator;
    return coordinator?.activePage ? coordinator.activePage() === 'market'
      : document.querySelector('#nav button.active[data-page="market"]') !== null;
  }

  async function get(url, timeoutMs = 8000) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally {
      clearTimeout(timeout);
    }
  }

  function tone(side) {
    return String(side).toLowerCase() === 'buy' ? 'buy' : 'sell';
  }

  function sma(data, period) {
    const output = [];
    for (let index = 0; index < data.length; index += 1) {
      if (index + 1 < period) { output.push(null); continue; }
      let sum = 0;
      for (let cursor = index - period + 1; cursor <= index; cursor += 1) sum += Number(data[cursor].close);
      output.push(sum / period);
    }
    return output;
  }

  function rsi(data, period = 14) {
    if (data.length <= period) return null;
    let gains = 0;
    let losses = 0;
    for (let index = data.length - period; index < data.length; index += 1) {
      const difference = Number(data[index].close) - Number(data[index - 1].close);
      if (difference >= 0) gains += difference;
      else losses -= difference;
    }
    if (losses === 0) return 100;
    const relativeStrength = (gains / period) / (losses / period);
    return 100 - (100 / (1 + relativeStrength));
  }

  function calcSpread() {
    const bid = Number(state.orderbook?.bids?.[0]?.[0]);
    const ask = Number(state.orderbook?.asks?.[0]?.[0]);
    if (!bid || !ask) return null;
    return { value: ask - bid, percent: (ask - bid) / ((ask + bid) / 2) * 100 };
  }

  function quoteTimestamp(quote = state.quote) {
    if (!quote) return 0;
    for (const value of [quote.received_at_ms, quote.exchange_timestamp_ms]) {
      const parsed = Number(value);
      if (Number.isFinite(parsed) && parsed > 0) return parsed;
    }
    const parsed = Date.parse(quote.received_at || quote.timestamp || '');
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function relevantNews() {
    return (state.news || []).filter((item) => {
      const assets = [
        ...(Array.isArray(item.assets) ? item.assets : []),
        ...(Array.isArray(item.symbols) ? item.symbols : []),
      ].map(String);
      return assets.some((asset) => state.symbol.startsWith(asset.replace('/USDT', '').replace('USDT', '')));
    }).slice(0, 8);
  }

  function toolbar() {
    return `<div class="mt-toolbar">
      <select id="mtSymbol" aria-label="Торговая пара">${symbols.map((symbol) => `<option ${symbol === state.symbol ? 'selected' : ''}>${symbol}</option>`).join('')}</select>
      <div class="mt-intervals" aria-label="Интервал свечей">${intervals.map(([value, label]) => `<button type="button" data-mt-interval="${value}" class="${value === state.interval ? 'active' : ''}">${label}</button>`).join('')}</div>
      <label><input id="mtSma7" type="checkbox" ${state.showSma7 ? 'checked' : ''}> SMA 7</label>
      <label><input id="mtSma25" type="checkbox" ${state.showSma25 ? 'checked' : ''}> SMA 25</label>
      <button id="mtReload" class="action" type="button">Обновить всё</button>
      <div class="mt-live-wrap"><span id="mtLiveBadge" class="mt-live waiting">ПОДКЛЮЧЕНИЕ</span><small id="mtUpdated">Ожидание котировки</small></div>
    </div>`;
  }

  function orderbookHtml() {
    const orderbook = state.orderbook;
    if (!orderbook) return '<div class="empty">Стакан пока не получен.</div>';
    const asks = (orderbook.asks || []).slice(0, 12).reverse();
    const bids = (orderbook.bids || []).slice(0, 12);
    const row = (value, cls) => `<div class="mt-book-row ${cls}"><span>${num(value[0])}</span><span>${num(value[1])}</span></div>`;
    return `<div class="mt-book-head"><span>Цена</span><span>Количество</span></div>${asks.map((value) => row(value, 'ask')).join('')}<div class="mt-mid">Спред</div>${bids.map((value) => row(value, 'bid')).join('')}`;
  }

  function tradesHtml() {
    if (!state.trades.length) return '<div class="empty">Лента сделок пока не получена.</div>';
    return `<div class="mt-trades"><div class="mt-trade-head"><span>Время</span><span>Цена</span><span>Объём</span></div>${state.trades.slice(0, 40).map((trade) => `<div class="mt-trade ${tone(trade.side)}"><span>${new Date(Number(trade.time)).toLocaleTimeString('ru-RU')}</span><b>${num(trade.price)}</b><span>${num(trade.size)}</span></div>`).join('')}</div>`;
  }

  function markersHtml() {
    const rows = [];
    const run = state.run || {};
    if (run.decision) rows.push(`<div class="mt-marker decision"><b>Решение ИИ: ${esc(run.decision)}</b><span>${esc(run.reason || 'Причина не передана')}</span></div>`);
    relevantNews().forEach((item) => rows.push(`<div class="mt-marker news"><b>${esc(item.title || item.headline || 'Новость')}</b><span>${esc(item.source || item.publisher || 'Источник не указан')}</span></div>`));
    return rows.length ? rows.join('') : '<div class="empty">Подтверждённых меток для выбранного актива пока нет.</div>';
  }

  function renderShell() {
    if (!activeMarket()) return;
    const content = $('content');
    if (!content) return;
    content.innerHTML = `<div class="title"><h1>Рыночный терминал</h1><p>Котировка обновляется каждую секунду из публичного потока Bybit</p></div>
      ${toolbar()}
      <section class="metrics">
        <article class="card"><span>Цена</span><strong id="mtPrice">—</strong><small id="mtPriceSource">Bybit</small></article>
        <article class="card"><span>24 часа</span><strong id="mtChange">—</strong><small>Изменение</small></article>
        <article class="card"><span>Спред</span><strong id="mtSpread">—</strong><small>Лучшая покупка/продажа</small></article>
        <article class="card"><span>RSI 14</span><strong id="mtRsi">—</strong><small>По реальным свечам</small></article>
        <article class="card"><span>Последняя свеча</span><strong id="mtLastCandle">—</strong><small id="mtCandleInterval">${esc(state.interval)}</small></article>
      </section>
      <section class="mt-layout">
        <article class="panel mt-chart-panel"><small>SHARIPOVAI</small><h2>${esc(state.symbol)} · свечной график</h2><canvas id="mtChart" height="520"></canvas><div id="mtSource" class="mt-source">Источник: Bybit · ожидание данных</div></article>
        <article class="panel mt-side"><small>BYBIT</small><h2>Стакан</h2><div id="mtOrderbook">${orderbookHtml()}</div></article>
        <article class="panel mt-side"><small>BYBIT</small><h2>Последние сделки</h2><div id="mtTrades">${tradesHtml()}</div></article>
        <article class="panel mt-markers"><small>SHARIPOVAI</small><h2>Новости и решения ИИ</h2><div id="mtMarkers">${markersHtml()}</div></article>
      </section>`;
    bind();
    updateLiveFields();
    requestAnimationFrame(draw);
  }

  function setText(id, value) {
    const element = $(id);
    if (element) element.textContent = value;
  }

  function flashPrice(element, direction) {
    if (!element || !direction) return;
    element.classList.remove('mt-tick-up', 'mt-tick-down');
    void element.offsetWidth;
    element.classList.add(direction > 0 ? 'mt-tick-up' : 'mt-tick-down');
  }

  function updateLiveFields() {
    if (!activeMarket()) return;
    const quote = state.quote || {};
    const price = Number(quote.price);
    const priceElement = $('mtPrice');
    if (Number.isFinite(price)) {
      const direction = state.displayedPrice == null ? 0 : Math.sign(price - state.displayedPrice);
      setText('mtPrice', `${num(price)} USDT`);
      flashPrice(priceElement, direction);
      state.displayedPrice = price;
    }

    const change = Number(quote.change_24h_percent);
    const changeElement = $('mtChange');
    if (changeElement) {
      changeElement.textContent = Number.isFinite(change) ? `${num(change, 2)}%` : '—';
      changeElement.classList.toggle('positive', Number.isFinite(change) && change >= 0);
      changeElement.classList.toggle('negative', Number.isFinite(change) && change < 0);
    }

    const spread = calcSpread();
    setText('mtSpread', spread ? `${num(spread.value)} / ${num(spread.percent, 4)}%` : '—');
    const currentRsi = rsi(state.candles);
    setText('mtRsi', currentRsi == null ? '—' : num(currentRsi, 2));
    const last = state.candles[state.candles.length - 1] || {};
    setText('mtLastCandle', last.close == null ? '—' : num(last.close));
    setText('mtCandleInterval', state.interval);

    const timestamp = quoteTimestamp();
    const ageSeconds = timestamp ? Math.max(0, (Date.now() - timestamp) / 1000) : Infinity;
    const badge = $('mtLiveBadge');
    if (badge) {
      badge.classList.remove('good', 'warn', 'bad', 'waiting');
      if (!state.quote && !state.quoteError) {
        badge.classList.add('waiting'); badge.textContent = 'ПОДКЛЮЧЕНИЕ';
      } else if (!state.quoteError && ageSeconds <= 2.5) {
        badge.classList.add('good'); badge.textContent = 'LIVE · 1 СЕК';
      } else if (state.quote && ageSeconds <= 8) {
        badge.classList.add('warn'); badge.textContent = 'ЗАДЕРЖКА';
      } else {
        badge.classList.add('bad'); badge.textContent = 'НЕТ ПОТОКА';
      }
    }

    const updated = timestamp ? `${new Date(timestamp).toLocaleTimeString('ru-RU')} · ${ageSeconds.toFixed(1)} сек. назад` : (state.quoteError || 'Ожидание котировки');
    setText('mtUpdated', updated);
    const source = quote.source || 'Bybit';
    setText('mtPriceSource', state.quoteTransport ? `${source} · ${state.quoteTransport}` : source);
    setText('mtSource', timestamp ? `Источник: ${source} · ${state.quoteTransport || 'проверенная котировка'} · ${new Date(timestamp).toLocaleString('ru-RU')}` : `Источник: Bybit · ${state.quoteError || 'ожидание данных'}`);
  }

  function renderDynamicPanels() {
    if (!activeMarket()) return;
    const book = $('mtOrderbook'); if (book) book.innerHTML = orderbookHtml();
    const trades = $('mtTrades'); if (trades) trades.innerHTML = tradesHtml();
    const markers = $('mtMarkers'); if (markers) markers.innerHTML = markersHtml();
    updateLiveFields();
    requestAnimationFrame(draw);
  }

  function bind() {
    $('mtSymbol')?.addEventListener('change', (event) => changeMarket(event.target.value, state.interval));
    document.querySelectorAll('[data-mt-interval]').forEach((button) => button.addEventListener('click', () => changeMarket(state.symbol, button.dataset.mtInterval)));
    $('mtReload')?.addEventListener('click', () => loadAll(true));
    $('mtSma7')?.addEventListener('change', (event) => { state.showSma7 = event.target.checked; draw(); });
    $('mtSma25')?.addEventListener('change', (event) => { state.showSma25 = event.target.checked; draw(); });
  }

  function changeMarket(symbol, interval) {
    state.symbol = symbols.includes(symbol) ? symbol : 'BTCUSDT';
    state.interval = intervals.some(([value]) => value === interval) ? interval : '15';
    localStorage.setItem('sharipovai-market-symbol', state.symbol);
    state.quote = null; state.candles = []; state.orderbook = null; state.trades = [];
    state.quoteError = ''; state.displayedPrice = null;
    renderShell();
    loadAll(true);
  }

  function prep(canvas) {
    if (!canvas) return null;
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 900;
    const height = Number(canvas.getAttribute('height')) || 520;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const context = canvas.getContext('2d');
    context.scale(dpr, dpr);
    return { context, width, height };
  }

  function draw() {
    const canvas = $('mtChart');
    const prepared = prep(canvas);
    if (!prepared) return;
    const { context, width, height } = prepared;
    context.clearRect(0, 0, width, height);
    if (!state.candles.length) {
      context.fillStyle = '#7f93a8';
      context.font = '14px sans-serif';
      context.fillText('Загрузка свечей…', 20, 32);
      return;
    }

    const data = state.candles.slice(-140);
    const padding = { left: 12, right: 82, top: 20, bottom: 30 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const low = Math.min(...data.map((item) => item.low));
    const high = Math.max(...data.map((item) => item.high));
    const range = high - low || 1;
    const y = (value) => padding.top + (high - value) / range * plotHeight;
    const step = plotWidth / data.length;
    const body = Math.max(2, step * 0.62);

    context.strokeStyle = '#173957';
    context.fillStyle = '#7f93a8';
    context.font = '11px sans-serif';
    for (let index = 0; index < 6; index += 1) {
      const yy = padding.top + index * plotHeight / 5;
      context.beginPath(); context.moveTo(padding.left, yy); context.lineTo(width - padding.right, yy); context.stroke();
      context.fillText(num(high - index * range / 5), width - padding.right + 8, yy + 4);
    }

    data.forEach((item, index) => {
      const xx = padding.left + index * step + step / 2;
      const up = item.close >= item.open;
      const color = up ? '#3be08f' : '#ff6f7d';
      context.strokeStyle = color; context.fillStyle = color;
      context.beginPath(); context.moveTo(xx, y(item.high)); context.lineTo(xx, y(item.low)); context.stroke();
      const top = Math.min(y(item.open), y(item.close));
      const candleHeight = Math.max(1, Math.abs(y(item.open) - y(item.close)));
      context.fillRect(xx - body / 2, top, body, candleHeight);
    });

    [[7, '#31d7ff', state.showSma7], [25, '#f3c969', state.showSma25]].forEach(([period, color, enabled]) => {
      if (!enabled) return;
      const values = sma(data, period);
      context.strokeStyle = color; context.lineWidth = 1.5; context.beginPath();
      let started = false;
      values.forEach((value, index) => {
        if (value == null) return;
        const xx = padding.left + index * step + step / 2;
        const yy = y(value);
        if (!started) { context.moveTo(xx, yy); started = true; }
        else context.lineTo(xx, yy);
      });
      context.stroke();
    });
  }

  async function loadQuote() {
    if (!activeMarket() || document.hidden || state.quoteBusy) { updateLiveFields(); return; }
    state.quoteBusy = true;
    const requestedSymbol = state.symbol;
    try {
      let quote;
      let transport;
      try {
        quote = await get(`/api/market/bybit-websocket/quote/${requestedSymbol}`, 1800);
        transport = 'WebSocket';
      } catch {
        quote = await get(`/api/market/quote/${requestedSymbol}`, 3500);
        transport = 'REST fallback';
      }
      if (requestedSymbol !== state.symbol) return;
      state.quote = quote;
      state.quoteTransport = transport;
      state.quoteError = '';
    } catch (error) {
      if (requestedSymbol === state.symbol) state.quoteError = error?.message || 'Котировка недоступна';
    } finally {
      state.quoteBusy = false;
      updateLiveFields();
    }
  }

  async function loadBookAndTrades() {
    if (!activeMarket() || document.hidden || state.bookBusy) return;
    state.bookBusy = true;
    const requestedSymbol = state.symbol;
    try {
      const [book, trades] = await Promise.allSettled([
        get(`/api/market/orderbook/${requestedSymbol}?limit=50&category=spot`),
        get(`/api/market/trades/${requestedSymbol}?limit=100&category=spot`),
      ]);
      if (requestedSymbol !== state.symbol) return;
      if (book.status === 'fulfilled') state.orderbook = book.value;
      if (trades.status === 'fulfilled') state.trades = trades.value.trades || [];
      renderDynamicPanels();
    } finally {
      state.bookBusy = false;
    }
  }

  async function loadCandles() {
    if (!activeMarket() || document.hidden || state.candleBusy) return;
    state.candleBusy = true;
    const requestedSymbol = state.symbol;
    const requestedInterval = state.interval;
    try {
      const payload = await get(`/api/market/candles/${requestedSymbol}?interval=${requestedInterval}&limit=220&category=spot`);
      if (requestedSymbol !== state.symbol || requestedInterval !== state.interval) return;
      state.candles = payload.candles || [];
      updateLiveFields();
      requestAnimationFrame(draw);
    } catch {
      // Keep the last verified candle set visible instead of replacing it with invented data.
    } finally {
      state.candleBusy = false;
    }
  }

  async function loadContext() {
    if (!activeMarket() || document.hidden || state.contextBusy) return;
    state.contextBusy = true;
    try {
      const [news, run] = await Promise.allSettled([get('/api/social-news'), get('/api/run')]);
      if (news.status === 'fulfilled') state.news = news.value?.news?.items || news.value?.news || news.value?.items || [];
      if (run.status === 'fulfilled') state.run = run.value;
      renderDynamicPanels();
    } finally {
      state.contextBusy = false;
    }
  }

  async function loadAll(force = false) {
    if (!activeMarket()) return;
    if (force && !$('mtChart')) renderShell();
    await Promise.allSettled([loadQuote(), loadBookAndTrades(), loadCandles(), loadContext()]);
  }

  function restartTimers() {
    [state.quoteTimer, state.bookTimer, state.candleTimer, state.contextTimer].forEach(clearInterval);
    state.quoteTimer = setInterval(loadQuote, QUOTE_REFRESH_MS);
    state.bookTimer = setInterval(loadBookAndTrades, BOOK_REFRESH_MS);
    state.candleTimer = setInterval(loadCandles, CANDLE_REFRESH_MS);
    state.contextTimer = setInterval(loadContext, CONTEXT_REFRESH_MS);
  }

  function install() {
    document.querySelector('#nav button[data-page="market"]')?.addEventListener('click', () => setTimeout(() => {
      const externalSymbol = savedSymbol();
      if (externalSymbol !== state.symbol) state.symbol = externalSymbol;
      renderShell();
      loadAll(true);
    }, 0));
    if (activeMarket()) { renderShell(); loadAll(true); }
    restartTimers();
    window.addEventListener('resize', () => { if (activeMarket()) draw(); });
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && activeMarket()) loadAll(false);
    });
    window.addEventListener('online', () => { if (activeMarket()) loadAll(false); });
    window.addEventListener('offline', updateLiveFields);
  }

  window.addEventListener('DOMContentLoaded', install);
})();
