(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));

  const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT'];
  const INTERVALS = [['1', '1м'], ['5', '5м'], ['15', '15м'], ['60', '1ч'], ['240', '4ч'], ['D', '1д']];
  const TABS = [
    ['chart', 'График'],
    ['technical', 'Теханализ'],
    ['screener', 'Скринер'],
    ['heatmap', 'Тепловая карта'],
    ['overview', 'Обзор рынков'],
    ['calendar', 'Календарь'],
    ['news', 'Новости TradingView'],
  ];

  const WIDGETS = {
    chart: {
      src: 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js',
      height: 720,
      config: () => ({
        autosize: true,
        symbol: tvSymbol(),
        interval: state.interval,
        timezone: 'Etc/UTC',
        theme: 'dark',
        style: '1',
        locale: 'ru',
        backgroundColor: 'rgba(5, 18, 31, 1)',
        gridColor: 'rgba(31, 58, 82, 0.45)',
        enable_publishing: false,
        withdateranges: true,
        hide_side_toolbar: false,
        allow_symbol_change: true,
        save_image: false,
        details: true,
        hotlist: true,
        calendar: false,
        studies: ['STD;RSI', 'STD;MACD'],
        watchlist: SYMBOLS.map((symbol) => `BYBIT:${symbol}`),
        support_host: 'https://www.tradingview.com',
      }),
    },
    technical: {
      src: 'https://s3.tradingview.com/external-embedding/embed-widget-technical-analysis.js',
      height: 560,
      config: () => ({
        interval: technicalInterval(),
        width: '100%',
        height: '100%',
        isTransparent: true,
        symbol: tvSymbol(),
        showIntervalTabs: true,
        displayMode: 'multiple',
        locale: 'ru',
        colorTheme: 'dark',
      }),
    },
    screener: {
      src: 'https://s3.tradingview.com/external-embedding/embed-widget-screener.js',
      height: 680,
      config: () => ({
        width: '100%',
        height: '100%',
        defaultColumn: 'overview',
        screener_type: 'crypto_mkt',
        displayCurrency: 'USD',
        colorTheme: 'dark',
        locale: 'ru',
        isTransparent: true,
      }),
    },
    heatmap: {
      src: 'https://s3.tradingview.com/external-embedding/embed-widget-crypto-coins-heatmap.js',
      height: 650,
      config: () => ({
        dataSource: 'Crypto',
        blockSize: 'market_cap_calc',
        blockColor: 'change',
        locale: 'ru',
        symbolUrl: '',
        colorTheme: 'dark',
        hasTopBar: true,
        isDataSetEnabled: true,
        isZoomEnabled: true,
        hasSymbolTooltip: true,
        isMonoSize: false,
        width: '100%',
        height: '100%',
      }),
    },
    overview: {
      src: 'https://s3.tradingview.com/external-embedding/embed-widget-market-overview.js',
      height: 650,
      config: () => ({
        colorTheme: 'dark',
        dateRange: '12M',
        showChart: true,
        locale: 'ru',
        width: '100%',
        height: '100%',
        largeChartUrl: '',
        isTransparent: true,
        showSymbolLogo: true,
        showFloatingTooltip: false,
        plotLineColorGrowing: 'rgba(41, 189, 126, 1)',
        plotLineColorFalling: 'rgba(255, 82, 82, 1)',
        gridLineColor: 'rgba(42, 58, 73, 0.35)',
        scaleFontColor: 'rgba(170, 184, 197, 1)',
        belowLineFillColorGrowing: 'rgba(41, 189, 126, 0.12)',
        belowLineFillColorFalling: 'rgba(255, 82, 82, 0.12)',
        belowLineFillColorGrowingBottom: 'rgba(41, 189, 126, 0)',
        belowLineFillColorFallingBottom: 'rgba(255, 82, 82, 0)',
        symbolActiveColor: 'rgba(49, 215, 255, 0.12)',
        tabs: [
          {
            title: 'Криптовалюты',
            symbols: SYMBOLS.map((symbol) => ({ s: `BYBIT:${symbol}`, d: symbol.replace('USDT', '/USDT') })),
            originalTitle: 'Crypto',
          },
          {
            title: 'Индексы',
            symbols: [
              { s: 'FOREXCOM:SPXUSD', d: 'S&P 500' },
              { s: 'FOREXCOM:NSXUSD', d: 'Nasdaq 100' },
              { s: 'TVC:DXY', d: 'Индекс доллара' },
            ],
            originalTitle: 'Indices',
          },
          {
            title: 'Валюты и сырьё',
            symbols: [
              { s: 'FX:EURUSD', d: 'EUR/USD' },
              { s: 'FX:GBPUSD', d: 'GBP/USD' },
              { s: 'OANDA:XAUUSD', d: 'Золото' },
              { s: 'TVC:USOIL', d: 'Нефть WTI' },
            ],
            originalTitle: 'Forex and commodities',
          },
        ],
      }),
    },
    calendar: {
      src: 'https://s3.tradingview.com/external-embedding/embed-widget-events.js',
      height: 650,
      config: () => ({
        colorTheme: 'dark',
        isTransparent: true,
        width: '100%',
        height: '100%',
        locale: 'ru',
        importanceFilter: '-1,0,1',
        countryFilter: 'us,eu,gb,jp,cn,ru',
      }),
    },
    news: {
      src: 'https://s3.tradingview.com/external-embedding/embed-widget-timeline.js',
      height: 650,
      config: () => ({
        feedMode: 'market',
        market: 'crypto',
        isTransparent: true,
        displayMode: 'regular',
        width: '100%',
        height: '100%',
        colorTheme: 'dark',
        locale: 'ru',
      }),
    },
  };

  const state = {
    symbol: savedSymbol(),
    interval: localStorage.getItem('sharipovai-market-interval') || '15',
    tab: localStorage.getItem('sharipovai-market-tv-tab') || 'chart',
    quote: null,
    orderbook: null,
    trades: [],
    virtual: null,
    quoteError: '',
    updatedAt: 0,
    quoteBusy: false,
    bookBusy: false,
    contextBusy: false,
    quoteTimer: null,
    bookTimer: null,
    contextTimer: null,
    widgetSerial: 0,
  };

  if (!INTERVALS.some(([value]) => value === state.interval)) state.interval = '15';
  if (!WIDGETS[state.tab]) state.tab = 'chart';

  function savedSymbol() {
    const raw = String(localStorage.getItem('sharipovai-market-symbol') || 'BTCUSDT')
      .replace(/[^A-Za-z0-9]/g, '')
      .toUpperCase();
    return SYMBOLS.includes(raw) ? raw : 'BTCUSDT';
  }

  function activeMarket() {
    const coordinator = window.SharipovAIPageCoordinator;
    return coordinator?.activePage
      ? coordinator.activePage() === 'market'
      : document.querySelector('#nav button.active[data-page="market"]') !== null;
  }

  function tvSymbol() {
    return `BYBIT:${state.symbol}`;
  }

  function technicalInterval() {
    return ({ '1': '1m', '5': '5m', '15': '15m', '60': '1h', '240': '4h', D: '1D' })[state.interval] || '15m';
  }

  function price(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '—';
    const digits = Math.abs(number) >= 100 ? 1 : Math.abs(number) >= 10 ? 2 : 4;
    return number.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function amount(value, digits = 4) {
    const number = Number(value);
    return Number.isFinite(number)
      ? number.toLocaleString('ru-RU', { maximumFractionDigits: digits })
      : '—';
  }

  function percent(value) {
    const number = Number(value);
    return Number.isFinite(number)
      ? `${number >= 0 ? '+' : ''}${number.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`
      : '—';
  }

  async function get(url, timeoutMs = 7000) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        credentials: 'same-origin',
        cache: 'no-store',
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally {
      clearTimeout(timeout);
    }
  }

  function best(levels) {
    const first = Array.isArray(levels) ? levels[0] : null;
    return Array.isArray(first) ? Number(first[0]) : null;
  }

  function spread() {
    const bid = best(state.orderbook?.bids);
    const ask = best(state.orderbook?.asks);
    if (!Number.isFinite(bid) || !Number.isFinite(ask) || bid <= 0 || ask <= 0) return null;
    const midpoint = (bid + ask) / 2;
    return { value: ask - bid, percent: ((ask - bid) / midpoint) * 100 };
  }

  function virtualPayload() {
    const raw = state.virtual || {};
    const root = raw.state && typeof raw.state === 'object' ? raw.state : raw;
    return { summary: root.summary || raw.summary || {}, trades: root.trades || raw.trades || [] };
  }

  function toolbar() {
    return `<section class="tv32-toolbar" aria-label="Управление рынком">
      <label>Пара SharipovAI
        <select id="tv32Symbol">${SYMBOLS.map((symbol) => `<option value="${symbol}" ${symbol === state.symbol ? 'selected' : ''}>${symbol.replace('USDT', '/USDT')}</option>`).join('')}</select>
      </label>
      <div class="tv32-intervals" aria-label="Интервал">${INTERVALS.map(([value, label]) => `<button type="button" data-tv32-interval="${value}" class="${value === state.interval ? 'active' : ''}">${label}</button>`).join('')}</div>
      <button id="tv32Refresh" class="action" type="button">Обновить данные</button>
      <a class="action tv32-external" href="https://ru.tradingview.com/" target="_blank" rel="noopener noreferrer nofollow">Открыть TradingView ↗</a>
    </section>`;
  }

  function orderbookHtml() {
    const book = state.orderbook;
    if (!book) return '<div class="empty">Стакан Bybit ещё не получен.</div>';
    const asks = (book.asks || []).slice(0, 8).reverse();
    const bids = (book.bids || []).slice(0, 8);
    const rows = (values, side) => values.map((entry) => `<div class="tv32-book-row ${side}"><span>${esc(price(entry[0]))}</span><span>${esc(amount(entry[1]))}</span></div>`).join('');
    return `<div class="tv32-book-head"><span>Цена</span><span>Количество</span></div>
      ${rows(asks, 'ask')}
      <div class="tv32-book-mid">СПРЕД</div>
      ${rows(bids, 'bid')}`;
  }

  function tradesHtml() {
    if (!state.trades.length) return '<div class="empty">Лента Bybit ещё не получена.</div>';
    return `<div class="tv32-tape"><div class="tv32-tape-head"><span>Время</span><span>Цена</span><span>Объём</span></div>${state.trades.slice(0, 24).map((trade) => {
      const side = String(trade.side || '').toLowerCase() === 'buy' ? 'buy' : 'sell';
      const stamp = Number(trade.time || trade.timestamp || 0);
      return `<div class="tv32-tape-row ${side}"><span>${stamp ? new Date(stamp).toLocaleTimeString('ru-RU') : '—'}</span><b>${esc(price(trade.price))}</b><span>${esc(amount(trade.size || trade.qty))}</span></div>`;
    }).join('')}</div>`;
  }

  function contextHtml() {
    const payload = virtualPayload();
    const summary = payload.summary;
    const selected = payload.trades.filter((trade) => String(trade.symbol || trade.asset || '').replace('/', '') === state.symbol);
    const open = selected.filter((trade) => String(trade.status).toUpperCase() === 'OPEN');
    const latest = selected.slice().reverse()[0];
    const lastAction = latest
      ? `${String(latest.side || '').toUpperCase()} · ${latest.status || '—'} · Net PnL ${Number(latest.net_pnl || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} USDT`
      : 'Операций по выбранной паре ещё нет';
    return `<div class="tv32-context-row"><span>Открытые позиции по паре</span><b>${open.length}</b></div>
      <div class="tv32-context-row"><span>Последняя операция</span><b>${esc(lastAction)}</b></div>
      <div class="tv32-context-row"><span>Рыночный учёт PnL</span><b class="${summary.market_price_accounting === true ? 'positive' : 'negative'}">${summary.market_price_accounting === true ? 'ПОДТВЕРЖДЁН' : 'НЕ ПОДТВЕРЖДЁН'}</b></div>
      <div class="tv32-context-row"><span>Реальные ордера</span><b class="${summary.real_orders_blocked === false ? 'negative' : 'positive'}">${summary.real_orders_blocked === false ? 'РАЗРЕШЕНЫ' : 'ЗАБЛОКИРОВАНЫ'}</b></div>`;
  }

  function renderShell() {
    if (!activeMarket()) return;
    const content = $('content');
    if (!content) return;
    content.innerHTML = `<div class="title"><h1>Рынок</h1><p>TradingView для визуального анализа · Bybit и SharipovAI для проверенных данных и решений</p></div>
      <div class="tv32-safety"><b>Важно:</b> TradingView встроен как аналитический интерфейс. Он не передаёт ордера и не заменяет рыночные источники SharipovAI. Реальная торговля остаётся заблокированной.</div>
      ${toolbar()}
      <section class="metrics tv32-metrics">
        <article class="card"><span>Цена Bybit</span><strong id="tv32Price">—</strong><small id="tv32Source">Проверенный источник</small></article>
        <article class="card"><span>24 часа</span><strong id="tv32Change">—</strong><small>Изменение выбранной пары</small></article>
        <article class="card"><span>Лучшая покупка</span><strong id="tv32Bid">—</strong><small>Bid</small></article>
        <article class="card"><span>Лучшая продажа</span><strong id="tv32Ask">—</strong><small>Ask</small></article>
        <article class="card"><span>Спред</span><strong id="tv32Spread">—</strong><small>Цена и процент</small></article>
        <article class="card"><span>Свежесть данных</span><strong id="tv32Freshness">—</strong><small id="tv32Updated">Ожидание</small></article>
      </section>
      <article class="panel tv32-terminal-panel">
        <div class="tv32-terminal-head"><div><small>TRADINGVIEW</small><h2>Аналитический терминал</h2></div><span>Официальные встраиваемые виджеты</span></div>
        <div class="tv32-tabs" role="tablist">${TABS.map(([value, label]) => `<button type="button" role="tab" data-tv32-tab="${value}" aria-selected="${value === state.tab}" class="${value === state.tab ? 'active' : ''}">${label}</button>`).join('')}</div>
        <div id="tv32Widget" class="tv32-widget-host"><div class="tv32-widget-loading">Загрузка TradingView…</div></div>
      </article>
      <section class="tv32-native-grid">
        <article class="panel"><small>BYBIT</small><h2>Стакан</h2><div id="tv32Orderbook">${orderbookHtml()}</div></article>
        <article class="panel"><small>BYBIT</small><h2>Последние сделки рынка</h2><div id="tv32Trades">${tradesHtml()}</div></article>
        <article class="panel"><small>SHARIPOVAI</small><h2>Контекст выбранной пары</h2><div id="tv32Context">${contextHtml()}</div></article>
      </section>
      <div class="tv32-attribution">Графики и аналитические модули предоставлены TradingView. Котировки, стакан, виртуальные операции и контроль безопасности SharipovAI проверяются отдельно.</div>`;
    bindControls();
    mountWidget();
    renderLive();
  }

  function bindControls() {
    $('tv32Symbol')?.addEventListener('change', (event) => changeMarket(event.target.value, state.interval));
    document.querySelectorAll('[data-tv32-interval]').forEach((button) => button.addEventListener('click', () => changeMarket(state.symbol, button.dataset.tv32Interval)));
    document.querySelectorAll('[data-tv32-tab]').forEach((button) => button.addEventListener('click', () => {
      state.tab = WIDGETS[button.dataset.tv32Tab] ? button.dataset.tv32Tab : 'chart';
      localStorage.setItem('sharipovai-market-tv-tab', state.tab);
      document.querySelectorAll('[data-tv32-tab]').forEach((item) => {
        item.classList.toggle('active', item.dataset.tv32Tab === state.tab);
        item.setAttribute('aria-selected', String(item.dataset.tv32Tab === state.tab));
      });
      mountWidget();
    }));
    $('tv32Refresh')?.addEventListener('click', () => refreshAll(true));
  }

  function changeMarket(symbol, interval) {
    state.symbol = SYMBOLS.includes(symbol) ? symbol : 'BTCUSDT';
    state.interval = INTERVALS.some(([value]) => value === interval) ? interval : '15';
    localStorage.setItem('sharipovai-market-symbol', state.symbol);
    localStorage.setItem('sharipovai-market-interval', state.interval);
    state.quote = null;
    state.orderbook = null;
    state.trades = [];
    state.quoteError = '';
    renderShell();
    refreshAll(true);
  }

  function mountWidget() {
    if (!activeMarket()) return;
    const host = $('tv32Widget');
    const definition = WIDGETS[state.tab] || WIDGETS.chart;
    if (!host) return;
    const serial = ++state.widgetSerial;
    host.style.minHeight = `${definition.height}px`;
    host.replaceChildren();

    const container = document.createElement('div');
    container.className = 'tradingview-widget-container tv32-widget-container';
    container.style.height = `${definition.height}px`;
    container.style.width = '100%';
    const widget = document.createElement('div');
    widget.className = 'tradingview-widget-container__widget';
    widget.style.height = 'calc(100% - 28px)';
    widget.style.width = '100%';
    const copyright = document.createElement('div');
    copyright.className = 'tradingview-widget-copyright';
    copyright.innerHTML = '<a href="https://www.tradingview.com/" rel="noopener noreferrer nofollow" target="_blank"><span class="blue-text">Все рынки на TradingView</span></a>';
    const script = document.createElement('script');
    script.type = 'text/javascript';
    script.src = definition.src;
    script.async = true;
    script.textContent = JSON.stringify(definition.config());
    script.addEventListener('error', () => {
      if (serial !== state.widgetSerial) return;
      host.innerHTML = '<div class="tv32-widget-error"><b>TradingView не загрузился.</b><span>Проверь блокировщик рекламы или доступ к s3.tradingview.com. Данные Bybit и SharipovAI ниже продолжают работать.</span><button id="tv32RetryWidget" class="action" type="button">Повторить</button></div>';
      $('tv32RetryWidget')?.addEventListener('click', mountWidget);
    });
    container.append(widget, copyright, script);
    host.append(container);
  }

  function renderLive() {
    if (!activeMarket()) return;
    const quote = state.quote || {};
    const quotePrice = Number(quote.price);
    const change = Number(quote.change_24h_percent);
    const bid = best(state.orderbook?.bids);
    const ask = best(state.orderbook?.asks);
    const currentSpread = spread();
    const timestamp = Date.parse(quote.received_at || quote.timestamp || '') || Number(quote.received_at_ms || 0);
    const age = timestamp ? Math.max(0, (Date.now() - timestamp) / 1000) : null;

    if ($('tv32Price')) $('tv32Price').textContent = Number.isFinite(quotePrice) ? `${price(quotePrice)} USDT` : '—';
    if ($('tv32Source')) $('tv32Source').textContent = quote.source || state.quoteError || 'Bybit';
    if ($('tv32Change')) {
      $('tv32Change').textContent = percent(change);
      $('tv32Change').classList.toggle('positive', Number.isFinite(change) && change >= 0);
      $('tv32Change').classList.toggle('negative', Number.isFinite(change) && change < 0);
    }
    if ($('tv32Bid')) $('tv32Bid').textContent = Number.isFinite(bid) ? price(bid) : '—';
    if ($('tv32Ask')) $('tv32Ask').textContent = Number.isFinite(ask) ? price(ask) : '—';
    if ($('tv32Spread')) $('tv32Spread').textContent = currentSpread ? `${price(currentSpread.value)} · ${amount(currentSpread.percent, 4)}%` : '—';
    if ($('tv32Freshness')) {
      const status = age == null ? 'ОЖИДАНИЕ' : age <= 3 ? 'LIVE' : age <= 10 ? 'ЗАДЕРЖКА' : 'УСТАРЕЛО';
      $('tv32Freshness').textContent = status;
      $('tv32Freshness').classList.toggle('positive', status === 'LIVE');
      $('tv32Freshness').classList.toggle('negative', status === 'УСТАРЕЛО');
    }
    if ($('tv32Updated')) $('tv32Updated').textContent = age == null ? (state.quoteError || 'Ожидание котировки') : `${age.toFixed(1)} сек. назад`;

    const book = $('tv32Orderbook'); if (book) book.innerHTML = orderbookHtml();
    const tape = $('tv32Trades'); if (tape) tape.innerHTML = tradesHtml();
    const context = $('tv32Context'); if (context) context.innerHTML = contextHtml();
  }

  async function loadQuote() {
    if (!activeMarket() || document.hidden || state.quoteBusy) return;
    state.quoteBusy = true;
    const requested = state.symbol;
    try {
      let quote;
      try {
        quote = await get(`/api/market/bybit-websocket/quote/${requested}`, 2200);
      } catch {
        quote = await get(`/api/market/quote/${requested}`, 4500);
      }
      if (requested !== state.symbol) return;
      state.quote = quote;
      state.quoteError = '';
      state.updatedAt = Date.now();
    } catch (error) {
      if (requested === state.symbol) state.quoteError = error?.message || 'Котировка недоступна';
    } finally {
      state.quoteBusy = false;
      renderLive();
    }
  }

  async function loadBookAndTrades() {
    if (!activeMarket() || document.hidden || state.bookBusy) return;
    state.bookBusy = true;
    const requested = state.symbol;
    try {
      const [book, trades] = await Promise.allSettled([
        get(`/api/market/orderbook/${requested}?limit=30&category=spot`),
        get(`/api/market/trades/${requested}?limit=60&category=spot`),
      ]);
      if (requested !== state.symbol) return;
      if (book.status === 'fulfilled') state.orderbook = book.value;
      if (trades.status === 'fulfilled') state.trades = trades.value.trades || [];
    } finally {
      state.bookBusy = false;
      renderLive();
    }
  }

  async function loadContext() {
    if (!activeMarket() || document.hidden || state.contextBusy) return;
    state.contextBusy = true;
    try {
      state.virtual = await get('/api/virtual-account/state', 7000);
    } catch {
      // Keep the last confirmed virtual-account state visible.
    } finally {
      state.contextBusy = false;
      renderLive();
    }
  }

  function refreshAll(forceWidget = false) {
    loadQuote();
    loadBookAndTrades();
    loadContext();
    if (forceWidget) mountWidget();
  }

  function startTimers() {
    if (!state.quoteTimer) state.quoteTimer = setInterval(loadQuote, 2000);
    if (!state.bookTimer) state.bookTimer = setInterval(loadBookAndTrades, 5000);
    if (!state.contextTimer) state.contextTimer = setInterval(loadContext, 15000);
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('#nav button[data-page="market"]');
    if (!button) return;
    setTimeout(() => {
      renderShell();
      refreshAll();
      startTimers();
    }, 0);
  });

  $('refresh')?.addEventListener('click', () => {
    if (activeMarket()) refreshAll(true);
  });

  window.addEventListener('DOMContentLoaded', () => {
    startTimers();
    if (activeMarket()) {
      renderShell();
      refreshAll();
    }
  });
})();
