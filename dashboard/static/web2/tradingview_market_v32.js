(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
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

  const state = {
    symbol: savedSymbol(),
    interval: localStorage.getItem('sharipovai-market-interval') || '15',
    tab: localStorage.getItem('sharipovai-market-tv-tab') || 'chart',
    quote: null,
    orderbook: null,
    trades: [],
    truth: null,
    errors: {},
    updatedAt: null,
    widgetSerial: 0,
    busy: false,
  };
  if (!INTERVALS.some(([value]) => value === state.interval)) state.interval = '15';
  if (!TABS.some(([value]) => value === state.tab)) state.tab = 'chart';

  function savedSymbol() {
    const value = String(localStorage.getItem('sharipovai-market-symbol') || 'BTCUSDT')
      .replace(/[^A-Za-z0-9]/g, '')
      .toUpperCase();
    return SYMBOLS.includes(value) ? value : 'BTCUSDT';
  }
  function active() {
    return (window.SharipovAIPageCoordinator?.activePage?.()
      || document.querySelector('#nav button.active[data-page]')?.dataset.page) === 'market';
  }
  function tvSymbol() { return `BYBIT:${state.symbol}`; }
  function technicalInterval() {
    return ({ '1': '1m', '5': '5m', '15': '15m', '60': '1h', '240': '4h', D: '1D' })[state.interval] || '15m';
  }
  function number(value) { return Number.isFinite(Number(value)) ? Number(value) : null; }
  function price(value) {
    const parsed = number(value);
    if (parsed === null) return '—';
    const digits = Math.abs(parsed) >= 100 ? 1 : Math.abs(parsed) >= 10 ? 2 : 4;
    return parsed.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function amount(value, digits = 6) {
    const parsed = number(value);
    return parsed === null ? '—' : parsed.toLocaleString('ru-RU', { maximumFractionDigits: digits });
  }
  function percent(value) {
    const parsed = number(value);
    return parsed === null ? '—' : `${parsed >= 0 ? '+' : ''}${parsed.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
  }
  async function getJson(url, timeoutMs = 8000) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
      return response.json();
    } finally {
      clearTimeout(timeout);
    }
  }

  function widgetDefinition() {
    const base = { width: '100%', height: '100%', locale: 'ru', colorTheme: 'dark', isTransparent: true };
    const definitions = {
      chart: {
        src: 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js',
        height: 720,
        config: {
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
          studies: ['STD;RSI', 'STD;MACD'],
          watchlist: SYMBOLS.map((symbol) => `BYBIT:${symbol}`),
          support_host: 'https://www.tradingview.com',
        },
      },
      technical: {
        src: 'https://s3.tradingview.com/external-embedding/embed-widget-technical-analysis.js',
        height: 560,
        config: { ...base, interval: technicalInterval(), symbol: tvSymbol(), showIntervalTabs: true, displayMode: 'multiple' },
      },
      screener: {
        src: 'https://s3.tradingview.com/external-embedding/embed-widget-screener.js',
        height: 680,
        config: { ...base, defaultColumn: 'overview', screener_type: 'crypto_mkt', displayCurrency: 'USD' },
      },
      heatmap: {
        src: 'https://s3.tradingview.com/external-embedding/embed-widget-crypto-coins-heatmap.js',
        height: 650,
        config: { ...base, dataSource: 'Crypto', blockSize: 'market_cap_calc', blockColor: 'change', hasTopBar: true, isDataSetEnabled: true, isZoomEnabled: true, hasSymbolTooltip: true },
      },
      overview: {
        src: 'https://s3.tradingview.com/external-embedding/embed-widget-market-overview.js',
        height: 650,
        config: {
          ...base,
          dateRange: '12M',
          showChart: true,
          showSymbolLogo: true,
          tabs: [
            { title: 'Криптовалюты', symbols: SYMBOLS.map((symbol) => ({ s: `BYBIT:${symbol}`, d: symbol.replace('USDT', '/USDT') })), originalTitle: 'Crypto' },
            { title: 'Индексы', symbols: [{ s: 'FOREXCOM:SPXUSD', d: 'S&P 500' }, { s: 'FOREXCOM:NSXUSD', d: 'Nasdaq 100' }, { s: 'TVC:DXY', d: 'Индекс доллара' }], originalTitle: 'Indices' },
            { title: 'Валюты и сырьё', symbols: [{ s: 'FX:EURUSD', d: 'EUR/USD' }, { s: 'OANDA:XAUUSD', d: 'Золото' }, { s: 'TVC:USOIL', d: 'Нефть WTI' }], originalTitle: 'Forex and commodities' },
          ],
        },
      },
      calendar: {
        src: 'https://s3.tradingview.com/external-embedding/embed-widget-events.js',
        height: 650,
        config: { ...base, importanceFilter: '-1,0,1', countryFilter: 'us,eu,gb,jp,cn,ru' },
      },
      news: {
        src: 'https://s3.tradingview.com/external-embedding/embed-widget-timeline.js',
        height: 650,
        config: { ...base, feedMode: 'market', market: 'crypto', displayMode: 'regular' },
      },
    };
    return definitions[state.tab] || definitions.chart;
  }

  function best(levels) {
    const first = Array.isArray(levels) ? levels[0] : null;
    return Array.isArray(first) ? number(first[0]) : null;
  }
  function spread() {
    const bid = best(state.orderbook?.bids);
    const ask = best(state.orderbook?.asks);
    if (bid === null || ask === null || bid <= 0 || ask <= 0) return null;
    const midpoint = (bid + ask) / 2;
    return { value: ask - bid, percent: midpoint > 0 ? ((ask - bid) / midpoint) * 100 : null };
  }
  function toolbar() {
    return `<section class="tv32-toolbar" aria-label="Управление рынком">
      <label>Пара SharipovAI<select id="tv32Symbol">${SYMBOLS.map((symbol) => `<option value="${symbol}" ${symbol === state.symbol ? 'selected' : ''}>${symbol.replace('USDT', '/USDT')}</option>`).join('')}</select></label>
      <div class="tv32-intervals" aria-label="Интервал">${INTERVALS.map(([value, label]) => `<button type="button" data-tv32-interval="${value}" class="${value === state.interval ? 'active' : ''}">${label}</button>`).join('')}</div>
      <button id="tv32Refresh" class="action" type="button">Обновить данные</button>
      <a class="action tv32-external" href="https://ru.tradingview.com/" target="_blank" rel="noopener noreferrer nofollow">Все рынки на TradingView ↗</a>
    </section>`;
  }
  function tabs() {
    return `<div class="tv32-tabs" role="tablist">${TABS.map(([value, label]) => `<button type="button" role="tab" data-tv32-tab="${value}" aria-selected="${value === state.tab}" class="${value === state.tab ? 'active' : ''}">${label}</button>`).join('')}</div>`;
  }
  function orderbookHtml() {
    const asks = Array.isArray(state.orderbook?.asks) ? state.orderbook.asks.slice(0, 8).reverse() : [];
    const bids = Array.isArray(state.orderbook?.bids) ? state.orderbook.bids.slice(0, 8) : [];
    if (!asks.length && !bids.length) return '<div class="empty">Стакан биржи не получен.</div>';
    const rows = (items, side) => items.map((entry) => `<div class="tv32-book-row ${side}"><span>${esc(price(entry[0]))}</span><span>${esc(amount(entry[1]))}</span></div>`).join('');
    return `<div class="tv32-book-head"><span>Цена</span><span>Количество</span></div>${rows(asks, 'ask')}<div class="tv32-book-mid">СПРЕД</div>${rows(bids, 'bid')}`;
  }
  function tradesHtml() {
    if (!state.trades.length) return '<div class="empty">Лента сделок ещё не получена.</div>';
    return `<div class="tv32-tape"><div class="tv32-tape-head"><span>Время</span><span>Цена</span><span>Объём</span></div>${state.trades.slice(0, 24).map((trade) => {
      const side = String(trade.side || '').toLowerCase() === 'buy' ? 'buy' : 'sell';
      const stamp = Number(trade.time || trade.timestamp || trade.created_at_ms || 0);
      return `<div class="tv32-tape-row ${side}"><span>${stamp ? new Date(stamp < 1e12 ? stamp * 1000 : stamp).toLocaleTimeString('ru-RU') : '—'}</span><b>${esc(price(trade.price))}</b><span>${esc(amount(trade.size || trade.qty || trade.quantity))}</span></div>`;
    }).join('')}</div>`;
  }
  function canonicalContext() {
    const truth = state.truth || {};
    const paper = truth.paper || {};
    const summary = paper.summary || {};
    const safety = truth.safety || {};
    return `<div class="tv32-context-row"><span>Paper owner</span><b>${esc(truth.source_of_truth?.paper || 'не подтверждён')}</b></div>
      <div class="tv32-context-row"><span>Открытые позиции</span><b>${esc(String(summary.open_positions ?? 0))}</b></div>
      <div class="tv32-context-row"><span>Рыночный учёт PnL</span><b class="${summary.market_price_accounting === true ? 'positive' : 'negative'}">${summary.market_price_accounting === true ? 'ПОДТВЕРЖДЁН' : 'НЕ ПОДТВЕРЖДЁН'}</b></div>
      <div class="tv32-context-row"><span>Реальные ордера</span><b class="${safety.real_orders_blocked === true ? 'positive' : 'negative'}">${safety.real_orders_blocked === true ? 'ЗАБЛОКИРОВАНЫ' : 'UNSAFE'}</b></div>`;
  }

  function render() {
    if (!active()) return;
    const content = $('content');
    if (!content) return;
    const change = number(state.quote?.change_24h_percent);
    const spreadValue = spread();
    const errorCount = Object.keys(state.errors).length;
    content.innerHTML = `<div class="title"><h1>Рыночный терминал</h1><p>TradingView — визуальная аналитика; каноническая paper-истина приходит только из CouncilAuthorizedPaperLoop</p></div>
      ${toolbar()}
      <section class="metrics">
        <article class="card"><span>${esc(state.symbol.replace('USDT', '/USDT'))}</span><strong>${esc(price(state.quote?.price))} USDT</strong><small>${esc(state.quote?.source || 'источник не подтверждён')}</small></article>
        <article class="card"><span>24 часа</span><strong class="${change !== null && change >= 0 ? 'positive' : change !== null ? 'negative' : ''}">${esc(percent(change))}</strong><small>подтверждённая котировка</small></article>
        <article class="card"><span>Спред</span><strong>${spreadValue ? esc(price(spreadValue.value)) : '—'}</strong><small>${spreadValue?.percent == null ? '—' : esc(percent(spreadValue.percent))}</small></article>
        <article class="card"><span>Runtime truth</span><strong>${esc(String(state.truth?.status || 'unavailable').toUpperCase())}</strong><small>/api/system/runtime-truth</small></article>
        <article class="card"><span>Ошибки загрузки</span><strong class="${errorCount ? 'negative' : 'positive'}">${errorCount}</strong><small>${esc(state.updatedAt || 'не обновлено')}</small></article>
      </section>
      <section class="tv32-layout">
        <article class="panel wide tv32-main"><small>TRADINGVIEW</small><h2>Аналитические инструменты</h2>${tabs()}<div id="tv32Widget" class="tv32-widget-host"></div><p class="tv32-disclaimer">TradingView встроен как аналитический интерфейс. Он не передаёт ордера. Реальная торговля остаётся заблокированной.</p></article>
        <aside class="tv32-side"><article class="panel"><small>BYBIT PUBLIC DATA</small><h2>Стакан</h2>${orderbookHtml()}</article><article class="panel"><small>MARKET TAPE</small><h2>Последние сделки</h2>${tradesHtml()}</article><article class="panel"><small>CANONICAL CONTEXT</small><h2>Paper runtime</h2>${canonicalContext()}</article></aside>
      </section>`;
    bind();
    mountWidget();
  }

  function mountWidget() {
    const host = $('tv32Widget');
    if (!host) return;
    const definition = widgetDefinition();
    state.widgetSerial += 1;
    host.style.minHeight = `${definition.height}px`;
    host.innerHTML = '<div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div></div>';
    const script = document.createElement('script');
    script.async = true;
    script.src = definition.src;
    script.type = 'text/javascript';
    script.text = JSON.stringify(definition.config);
    script.dataset.serial = String(state.widgetSerial);
    host.querySelector('.tradingview-widget-container')?.appendChild(script);
  }

  function bind() {
    $('tv32Symbol')?.addEventListener('change', (event) => {
      state.symbol = SYMBOLS.includes(event.target.value) ? event.target.value : 'BTCUSDT';
      localStorage.setItem('sharipovai-market-symbol', state.symbol);
      load().catch(() => render());
    });
    document.querySelectorAll('[data-tv32-interval]').forEach((button) => button.addEventListener('click', () => {
      state.interval = button.dataset.tv32Interval || '15';
      localStorage.setItem('sharipovai-market-interval', state.interval);
      render();
    }));
    document.querySelectorAll('[data-tv32-tab]').forEach((button) => button.addEventListener('click', () => {
      state.tab = button.dataset.tv32Tab || 'chart';
      localStorage.setItem('sharipovai-market-tv-tab', state.tab);
      render();
    }));
    $('tv32Refresh')?.addEventListener('click', () => load().catch(() => render()));
  }

  async function load() {
    if (!active() || state.busy) return;
    state.busy = true;
    const specs = [
      ['quote', `/api/market/quote/${state.symbol}`],
      ['orderbook', `/api/market/orderbook/${state.symbol}`],
      ['trades', `/api/market/trades/${state.symbol}`],
      ['truth', '/api/system/runtime-truth'],
    ];
    const settled = await Promise.allSettled(specs.map(([, url]) => getJson(url)));
    state.errors = {};
    settled.forEach((result, index) => {
      const key = specs[index][0];
      if (result.status === 'fulfilled') {
        if (key === 'trades') state.trades = Array.isArray(result.value?.trades) ? result.value.trades : Array.isArray(result.value) ? result.value : [];
        else state[key] = result.value;
      } else {
        state.errors[key] = result.reason?.message || 'unavailable';
        if (key === 'trades') state.trades = [];
      }
    });
    state.updatedAt = new Date().toLocaleString('ru-RU');
    state.busy = false;
    render();
  }

  function install() {
    document.addEventListener('click', (event) => {
      if (event.target.closest('#nav button[data-page="market"]')) setTimeout(() => load().catch(() => render()), 0);
    });
    $('refresh')?.addEventListener('click', () => { if (active()) setTimeout(() => load().catch(() => render()), 0); });
    if (active()) load().catch(() => render());
  }

  window.SharipovAICanonicalMarket = Object.freeze({ load, render, symbols: [...SYMBOLS], tabs: [...TABS] });
  window.addEventListener('DOMContentLoaded', install, { once: true });
  setInterval(() => { if (active() && !document.hidden) load().catch(() => {}); }, 10000);
})();
