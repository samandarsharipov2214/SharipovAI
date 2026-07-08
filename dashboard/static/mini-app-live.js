(() => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const fmt = (value) => Number(value || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtRate = (value) => `${(Number(value || 0) * 100).toFixed(4)}%`;
  const RISK_STORAGE_KEY = 'sharipovaiRiskSettingsV3';

  function setText(selector, value) {
    const el = $(selector);
    if (el) el.textContent = value;
  }

  function translateRisk(value) {
    const key = String(value || '').toUpperCase();
    return { LOW: 'НИЗКИЙ', MEDIUM: 'СРЕДНИЙ', HIGH: 'ВЫСОКИЙ', CRITICAL: 'КРИТИЧЕСКИЙ' }[key] || value || 'НИЗКИЙ';
  }

  function translateDecision(value) {
    const key = String(value || '').toUpperCase();
    return { BUY: 'КУПИТЬ', SELL: 'ПРОДАТЬ', WATCH: 'НАБЛЮДАТЬ', IGNORE: 'ПРОПУСТИТЬ', NO_DECISION: 'НЕТ РЕШЕНИЯ', BLOCK_BUY: 'БЛОК BUY' }[key] || value || 'НАБЛЮДАТЬ';
  }

  function translateImpact(value) {
    return { bullish: 'позитивно', bearish: 'негативно', neutral: 'нейтрально' }[String(value || '').toLowerCase()] || 'нейтрально';
  }

  function addMessage(role, text) {
    const log = $('#ai-chat-log');
    if (!log) return;
    const item = document.createElement('div');
    item.className = `mini-message ${role === 'user' ? 'user-message' : 'assistant-message'}`;
    item.innerHTML = `<div class="mini-avatar">${role === 'user' ? 'Вы' : 'SA'}</div><div class="mini-bubble"><b>${role === 'user' ? 'Самандар' : 'SharipovAI'}</b><p></p></div>`;
    item.querySelector('p').textContent = text;
    log.appendChild(item);
    log.scrollTop = log.scrollHeight;
  }

  function ensureNewsPanel() {
    const tabs = $('.mini-tabs');
    if (tabs && !tabs.querySelector('[data-mini-tab="news-section"]')) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.miniTab = 'news-section';
      button.textContent = 'Новости';
      tabs.appendChild(button);
      button.addEventListener('click', (event) => {
        event.preventDefault();
        showPanel('news-section');
      });
    }
    if ($('#news-section')) return;
    const shell = $('.mini-app-shell');
    const safe = $('.bottom-safe');
    if (!shell) return;
    const article = document.createElement('article');
    article.className = 'mini-card mini-section';
    article.id = 'news-section';
    article.innerHTML = `
      <h2>Новости и соцсети</h2>
      <div class="mini-grid">
        <div class="mini-stat"><small>Источников</small><b id="news-sources-total">0</b></div>
        <div class="mini-stat"><small>Срочные</small><b id="news-high-urgency">0</b></div>
        <div class="mini-stat"><small>Нужно подтвердить</small><b id="news-confirmations">0</b></div>
        <div class="mini-stat"><small>Действие AI</small><b id="news-ai-action">НАБЛЮДАТЬ</b></div>
      </div>
      <div class="bot-grid" id="news-list"><div class="bot-row"><div><b>Загрузка новостей...</b><small>RSS/official/demo analysis</small></div><span class="bot-state">...</span></div></div>
      <p class="info-box">Telegram и X будут читаться только после безопасного подключения API/доступов. Одна публикация из соцсетей не даёт право на сделку без подтверждения.</p>`;
    shell.insertBefore(article, safe || null);
  }

  function showPanel(targetId) {
    const fallback = document.getElementById(targetId) ? targetId : 'overview-section';
    $$('.mini-app-shell .mini-section').forEach((panel) => panel.classList.toggle('active-panel', panel.id === fallback));
    $$('.mini-tabs button,[data-mini-tab]').forEach((button) => {
      if (button.closest('.mini-tabs')) button.classList.toggle('active', button.dataset.miniTab === fallback);
    });
  }

  function installTabs() {
    ensureNewsPanel();
    $$('[data-mini-tab]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        showPanel(button.dataset.miniTab || 'overview-section');
      });
    });
    showPanel('overview-section');
  }

  function rangeInputs() {
    return $$('[data-range-output]').filter((input) => input.closest('.mini-app-shell'));
  }

  function updateRangeOutput(input) {
    const output = input.parentElement?.querySelector('output');
    if (output) output.textContent = `${input.value}%`;
  }

  function installRiskPersistence() {
    const inputs = rangeInputs();
    try {
      const saved = JSON.parse(localStorage.getItem(RISK_STORAGE_KEY) || 'null');
      if (Array.isArray(saved)) inputs.forEach((input, index) => { if (saved[index] !== undefined) input.value = saved[index]; });
    } catch (_) {}
    inputs.forEach((input) => {
      updateRangeOutput(input);
      input.addEventListener('input', () => updateRangeOutput(input));
    });
    $('#save-settings')?.addEventListener('click', () => {
      localStorage.setItem(RISK_STORAGE_KEY, JSON.stringify(inputs.map((input) => input.value)));
      setText('#save-status', '✓ Изменения сохранены для демо-режима.');
    });
  }

  function renderTrades(trades) {
    const table = document.querySelector('.mini-table tbody');
    if (!table) return;
    const rows = (trades || []).slice(-8).reverse();
    table.innerHTML = '';
    if (!rows.length) {
      table.innerHTML = '<tr><td>Сделок пока нет</td><td>0.00</td></tr>';
      return;
    }
    rows.forEach((trade) => {
      const pnl = Number(trade.net_pnl ?? trade.pnl_usdt ?? 0);
      const fee = Number(trade.fee || 0);
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${trade.asset || trade.symbol || 'BTC/USDT'} ${trade.side || ''}<br><small>комиссия ${fmt(fee)} USDT</small></td><td class="${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${fmt(pnl)}</td>`;
      table.appendChild(tr);
    });
  }

  function renderCostIntelligence(state) {
    const costs = state.bybit_costs || {};
    const venue = costs.best_trade_venue || {};
    const best = venue.best || {};
    const borrows = costs.cheapest_borrows || [];
    const topBorrow = borrows[0] || {};
    const productMap = { spot: 'Спот', futures: 'Фьючерсы', options: 'Опционы', fiat_spot: 'Фиатный спот' };
    const liquidityMap = { maker: 'мейкер', taker: 'тейкер' };
    setText('#cost-best-venue', `${productMap[best.product] || 'Спот'} / ${liquidityMap[best.liquidity] || 'мейкер'}`);
    setText('#cost-roundtrip', `${fmt(best.round_trip_fee)} USDT`);
    setText('#cost-breakeven-move', `${Number(best.break_even_move_percent || 0).toFixed(4)}%`);
    setText('#cost-saving', `${fmt(venue.estimated_saving_vs_worst)} USDT`);
    setText('#cost-cheapest-borrow', `${topBorrow.symbol || 'BTC'} · ${fmtRate(topBorrow.hourly_rate)}/ч`);
  }

  function renderExchangeMonitor(state) {
    const exchange = state.exchange_status || {};
    const monitor = state.online_monitoring || {};
    const mode = String(exchange.mode || monitor.mode || 'sandbox');
    setText('#exchange-mode', mode === 'sandbox' ? 'Песочница' : mode === 'disabled' ? 'Отключено' : 'Live');
    setText('#overview-exchange', mode === 'sandbox' ? 'Песочница' : mode === 'disabled' ? 'Отключено' : 'Live');
    setText('#exchange-preview', monitor.order_preview_online ? 'Онлайн' : 'Ограничен');
    setText('#exchange-cost-ai', monitor.cost_intelligence_online ? 'Онлайн' : 'Нет');
    setText('#exchange-live', monitor.live_execution_enabled ? 'Включено' : 'Выкл.');
    setText('#exchange-fees', `${fmt(state.total_fees)} USDT`);
    setText('#exchange-drag', `${fmt(state.commission_drag)} USDT`);
    setText('#exchange-breakeven', `${fmt(state.break_even_price)} USDT`);
    setText('#exchange-message', monitor.real_orders_blocked ? 'Реальные ордера заблокированы. AI считает комиссии, займы, VIP и чистый PnL.' : 'Live открыт. Нужна ручная проверка риска перед каждым ордером.');
    renderCostIntelligence(state);
  }

  function renderReports(state) {
    setText('#mini-report-equity', `${fmt(state.equity)} USDT`);
    setText('#mini-report-pnl', `${fmt(state.pnl || state.net_pnl)} USDT`);
    setText('#mini-report-fees', `${fmt(state.total_fees)} USDT`);
    const trades = state.trades || [];
    setText('#mini-learning-trades', String(trades.length));
    setText('#mini-learning-winrate', trades.length ? 'собирается' : '0%');
  }

  function renderState(state) {
    if (!state) return;
    const pnl = Number(state.pnl || state.net_pnl || 0);
    setText('#portfolio-equity', `${fmt(state.equity)} USDT`);
    setText('#portfolio-pnl', `${fmt(pnl)} USDT`);
    setText('#hero-risk', translateRisk(state.risk_level));
    setText('#hero-decision-mini', translateDecision(state.decision));
    renderTrades(state.trades || []);
    renderExchangeMonitor(state);
    renderReports(state);
  }

  function renderNews(payload) {
    ensureNewsPanel();
    const summary = payload.news?.summary || payload.summary || {};
    const sources = payload.sources || {};
    setText('#news-sources-total', String(sources.total || 0));
    setText('#news-high-urgency', String(summary.high_urgency || 0));
    setText('#news-confirmations', String(summary.needs_confirmation || 0));
    setText('#news-ai-action', summary.block_buy ? 'БЛОК BUY' : 'НАБЛЮДАТЬ');
    const list = $('#news-list');
    if (!list) return;
    const items = payload.news?.items || payload.items || [];
    list.innerHTML = '';
    if (!items.length) {
      list.innerHTML = '<div class="bot-row"><div><b>Новостей пока нет</b><small>Жду обновления источников</small></div><span class="bot-state">0</span></div>';
      return;
    }
    items.slice(0, 8).forEach((item) => {
      const row = document.createElement('div');
      row.className = 'bot-row';
      row.innerHTML = `<div><b>${item.title || 'Новость'}</b><small>${item.source_name || 'Источник'} · ${translateImpact(item.impact)} · ${item.needs_confirmation ? 'нужно подтверждение' : 'подтверждено'}</small></div><span class="bot-state">${item.trust_score || 0}%</span>`;
      list.appendChild(row);
    });
  }

  async function loadDemoState() {
    try {
      const response = await fetch('/api/demo/state', { cache: 'no-store' });
      if (!response.ok) return;
      const payload = await response.json();
      renderState(payload.state || {});
    } catch (_) {}
  }

  async function loadStressLab() {
    try {
      const response = await fetch('/api/stress-lab/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({ scenario: 'btc_drop_20' })
      });
      if (!response.ok) return;
      const payload = await response.json();
      setText('#mini-stress-scenario', 'BTC -20%');
      setText('#mini-stress-loss', `${fmt(payload.after?.loss_amount)} USDT`);
      setText('#mini-stress-action', String(payload.classification || 'Защитный режим'));
    } catch (_) {}
  }

  async function loadBots() {
    const list = $('#bot-list');
    try {
      const response = await fetch('/api/ai-bots', { cache: 'no-store' });
      if (!response.ok) throw new Error('bots failed');
      const payload = await response.json();
      const summary = payload.summary || {};
      setText('#bots-total', String(summary.total_bots || 0));
      setText('#bots-active', String(summary.active || 0));
      setText('#bots-warnings', String(summary.warnings || 0));
      if (!list) return;
      list.innerHTML = '';
      (payload.bots || []).slice(0, 10).forEach((bot) => {
        const row = document.createElement('div');
        row.className = 'bot-row';
        row.innerHTML = `<div><b>${bot.name || 'AI-бот'}</b><small>${bot.short || bot.responsibility || 'Модуль SharipovAI'}</small></div><span class="bot-state">${bot.health_score || 0}%</span>`;
        list.appendChild(row);
      });
    } catch (_) {
      if (list) list.innerHTML = '<div class="bot-row"><div><b>AI-боты недоступны</b><small>Проверь Render deploy или логи сервера</small></div><span class="bot-state">!</span></div>';
    }
  }

  async function loadNews() {
    try {
      const response = await fetch('/api/social-news', { cache: 'no-store' });
      if (!response.ok) return;
      renderNews(await response.json());
    } catch (_) {}
  }

  async function runDemoCommand(command) {
    const response = await fetch('/api/demo/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({ message: command })
    });
    if (!response.ok) throw new Error('demo chat failed');
    return response.json();
  }

  async function submitCommand(command) {
    const input = $('#ai-command-input');
    const value = String(command || input?.value || '').trim();
    if (!value) {
      addMessage('ai', 'Напиши команду: «найди выгодные условия», «купи BTC», «поставь баланс 20000», «мониторинг онлайн».');
      return;
    }
    addMessage('user', value);
    if (input) input.value = '';
    try {
      const payload = await runDemoCommand(value);
      renderState(payload.state || {});
      addMessage('ai', payload.reply || 'Команда выполнена в демо-счёте.');
    } catch (_) {
      addMessage('ai', 'Команда не выполнена. Нужен свежий деплой backend или проверка Render logs.');
    }
  }

  function installChat() {
    $('#ai-command-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      submitCommand();
    });
    $$('[data-prompt]').forEach((button) => button.addEventListener('click', () => submitCommand(button.dataset.prompt || button.textContent || 'портфель')));
  }

  window.addEventListener('DOMContentLoaded', () => {
    installTabs();
    installRiskPersistence();
    installChat();
    loadDemoState();
    loadStressLab();
    loadBots();
    loadNews();
    setInterval(loadDemoState, 15000);
    setInterval(loadBots, 30000);
    setInterval(loadNews, 60000);
  });
})();
