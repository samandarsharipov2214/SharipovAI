(() => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const fmt = (value) => Number(value || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtRate = (value) => `${(Number(value || 0) * 100).toFixed(4)}%`;
  const RISK_STORAGE_KEY = 'sharipovaiRiskSettingsV2';

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

  function setText(selector, value) {
    const el = $(selector);
    if (el) el.textContent = value;
  }

  function rangeInputs() {
    return $$('[data-range-output]').filter((input) => input.closest('.mini-app-shell'));
  }

  function updateRangeOutput(input) {
    const output = input.parentElement?.querySelector('output');
    if (output) output.textContent = `${input.value}%`;
  }

  function installMiniStyles() {
    if ($('#mini-real-tabs-style')) return;
    const style = document.createElement('style');
    style.id = 'mini-real-tabs-style';
    style.textContent = `
      .mini-app-shell .mini-section{display:none!important;}
      .mini-app-shell .mini-section.active-panel{display:block!important;}
      .mini-tabs{display:flex!important;gap:8px;overflow-x:auto;padding:8px 0 14px;margin:4px 0 10px;scrollbar-width:none;position:sticky;top:0;z-index:5;background:#00111d;}
      .mini-tabs::-webkit-scrollbar{display:none;}
      .mini-tabs button{white-space:nowrap;min-width:max-content;border:1px solid #1e90ff55;background:#06182a;color:#bfe7ff;border-radius:999px;padding:10px 14px;font-weight:900;font-size:14px;}
      .mini-tabs button.active{background:linear-gradient(135deg,#1188ff,#19d3ff);color:white;box-shadow:0 0 18px #10bfff44;}
      .mini-subgrid{display:grid;grid-template-columns:1fr;gap:10px;margin-top:12px;}
      .mini-note{color:#9fb2c8;font-size:14px;line-height:1.45;}
    `;
    document.head.appendChild(style);
  }

  function localizeMiniApp() {
    const replacements = new Map([
      ['Preview', 'Предпросмотр'],
      ['Live', 'Реальные сделки'],
      ['Cost AI', 'Расчёт условий'],
      ['Break-even move', 'Движение до безубытка'],
      ['sandbox', 'Песочница'],
      ['Sandbox', 'Песочница'],
      ['Demo Trading', 'Демо-торговля']
    ]);
    $$('.mini-app-shell small,.mini-app-shell b,.mini-app-shell button,.mini-app-shell p,.mini-app-shell h2').forEach((el) => {
      const text = el.textContent?.trim();
      if (text && replacements.has(text)) el.textContent = replacements.get(text);
    });
    setText('#exchange-mode', 'Песочница');
    setText('#exchange-live', 'Выкл.');
  }

  function loadRiskSettings() {
    const inputs = rangeInputs();
    try {
      const saved = JSON.parse(localStorage.getItem(RISK_STORAGE_KEY) || localStorage.getItem('riskSettings') || 'null');
      if (Array.isArray(saved)) {
        inputs.forEach((input, index) => {
          if (saved[index] !== undefined) input.value = saved[index];
          updateRangeOutput(input);
        });
        const status = $('#save-status');
        if (status) status.textContent = '✓ Загружены сохранённые настройки.';
      }
    } catch (_) {}
  }

  function saveRiskSettings() {
    const values = rangeInputs().map((input) => input.value);
    localStorage.setItem(RISK_STORAGE_KEY, JSON.stringify(values));
    localStorage.setItem('riskSettings', JSON.stringify(values));
    const status = $('#save-status');
    if (status) status.textContent = '✓ Изменения сохранены. При повторном входе они загрузятся автоматически.';
  }

  function installRiskPersistence() {
    const inputs = rangeInputs();
    loadRiskSettings();
    inputs.forEach((input) => {
      updateRangeOutput(input);
      input.addEventListener('input', () => updateRangeOutput(input));
    });
    $('#save-settings')?.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      saveRiskSettings();
    }, true);
  }

  function ensureTab(label, targetId) {
    const tabs = $('.mini-tabs');
    if (!tabs || tabs.querySelector(`[data-mini-tab="${targetId}"]`)) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.miniTab = targetId;
    button.textContent = label;
    tabs.appendChild(button);
  }

  function makePanel(id, title, bodyHtml) {
    if (document.getElementById(id)) return;
    const shell = $('.mini-app-shell');
    const safe = $('.bottom-safe');
    if (!shell) return;
    const article = document.createElement('article');
    article.className = 'mini-card mini-section';
    article.id = id;
    article.innerHTML = `<h2>${title}</h2>${bodyHtml}`;
    shell.insertBefore(article, safe || null);
  }

  function ensureAllSiteFunctions() {
    ensureTab('Обзор', 'overview-section');
    ensureTab('AI чат', 'chat-section');
    ensureTab('AI-боты', 'bots-section');
    ensureTab('Риск', 'risk-section');
    ensureTab('Сделки', 'trades-section');
    ensureTab('Биржа', 'exchange-section');
    ensureTab('Стресс', 'stress-section');
    ensureTab('Обучение', 'learning-section');
    ensureTab('Отчёты', 'reports-section');
    ensureTab('Настройки', 'settings-section');

    makePanel('stress-section', 'Стресс-тест', '<div class="mini-grid"><div class="mini-stat"><small>Сценарий</small><b id="mini-stress-scenario">BTC -20%</b></div><div class="mini-stat"><small>Потеря</small><b id="mini-stress-loss">0.00 USDT</b></div><div class="mini-stat"><small>Реакция AI</small><b id="mini-stress-action">Защитный режим</b></div></div><p class="info-box">AI проверяет просадку, блокировку BUY и защитные меры без реальных ордеров.</p>');
    makePanel('learning-section', 'Обучение AI', '<div class="mini-grid"><div class="mini-stat"><small>Сделок</small><b id="mini-learning-trades">0</b></div><div class="mini-stat"><small>Win rate</small><b id="mini-learning-winrate">0%</b></div><div class="mini-stat"><small>Рекомендация</small><b id="mini-learning-tip">Собирать историю</b></div></div><p class="info-box">AI учитывает ошибки, комиссии, риск и качество сигналов.</p>');
    makePanel('reports-section', 'Отчёты', '<div class="mini-grid"><div class="mini-stat"><small>Портфель</small><b id="mini-report-equity">0.00 USDT</b></div><div class="mini-stat"><small>Чистый PnL</small><b id="mini-report-pnl">0.00 USDT</b></div><div class="mini-stat"><small>Комиссии</small><b id="mini-report-fees">0.00 USDT</b></div></div><p class="info-box">Отчёт показывает результат после комиссий, а не грязную прибыль.</p>');
    makePanel('settings-section', 'Настройки Mini App', '<div class="mini-subgrid"><button class="save-button" type="button" data-mini-tab="risk-section">Настройки риска</button><button class="save-button" type="button" data-mini-tab="exchange-section">Биржа и комиссии</button><button class="save-button" type="button" data-mini-tab="bots-section">Мониторинг AI-ботов</button></div><p class="info-box">Все основные функции сайта доступны внутри Mini App.</p>');
  }

  function renderTrades(trades) {
    const table = document.querySelector('.mini-table tbody');
    if (!table) return;
    const rows = (trades || []).slice(-6).reverse();
    table.innerHTML = '';
    if (!rows.length) {
      table.innerHTML = '<tr><td>Сделок пока нет</td><td>0.00</td></tr>';
      return;
    }
    rows.forEach((trade) => {
      const pnl = Number(trade.net_pnl ?? trade.pnl_usdt ?? 0);
      const fee = Number(trade.fee || 0);
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${trade.asset || trade.symbol || 'BTC/USDT'} ${trade.side || ''}<br><small>комиссия ${fmt(fee)}</small></td><td class="${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${fmt(pnl)}</td>`;
      table.appendChild(tr);
    });
  }

  function injectCostFields() {
    if ($('#cost-best-venue')) return;
    const exchangeSection = $('#exchange-section');
    const grid = exchangeSection?.querySelector('.mini-grid');
    if (!grid) return;
    const fields = [
      ['Расчёт условий', 'exchange-cost-ai', '...'],
      ['Лучшие условия', 'cost-best-venue', '...'],
      ['Круговая комиссия', 'cost-roundtrip', '0.00 USDT'],
      ['Движение до безубытка', 'cost-breakeven-move', '0.0000%'],
      ['Экономия', 'cost-saving', '0.00 USDT'],
      ['Дешёвый заём', 'cost-cheapest-borrow', '...']
    ];
    fields.forEach(([label, id, value]) => {
      const item = document.createElement('div');
      item.className = 'mini-stat';
      item.innerHTML = `<small>${label}</small><b id="${id}">${value}</b>`;
      grid.appendChild(item);
    });
  }

  function renderCostIntelligence(state) {
    injectCostFields();
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
    injectCostFields();
    const exchange = state.exchange_status || {};
    const monitor = state.online_monitoring || {};
    const mode = String(exchange.mode || monitor.mode || 'sandbox');
    setText('#exchange-mode', mode === 'sandbox' ? 'Песочница' : mode === 'disabled' ? 'Отключено' : 'Live');
    setText('#exchange-preview', monitor.order_preview_online ? 'Онлайн' : 'Ограничен');
    setText('#exchange-cost-ai', monitor.cost_intelligence_online ? 'Онлайн' : 'Нет');
    setText('#exchange-live', monitor.live_execution_enabled ? 'Включено' : 'Выкл.');
    setText('#exchange-fees', `${fmt(state.total_fees)} USDT`);
    setText('#exchange-drag', `${fmt(state.commission_drag)} USDT`);
    setText('#exchange-breakeven', `${fmt(state.break_even_price)} USDT`);
    setText('#exchange-message', monitor.real_orders_blocked ? 'Реальные ордера заблокированы. AI считает комиссии, ставки займов, VIP и чистый PnL через расчёт условий Bybit.' : 'Live открыт. Нужна ручная проверка риска перед каждым ордером.');
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
    setText('#hero-risk', String(state.risk_level || 'LOW'));
    setText('#hero-decision', String(state.decision || 'WATCH'));
    renderTrades(state.trades || []);
    renderExchangeMonitor(state);
    renderReports(state);
    localizeMiniApp();
  }

  async function loadDemoState() {
    try {
      const response = await fetch('/api/demo/state', { cache: 'no-store' });
      if (!response.ok) return;
      const payload = await response.json();
      renderState(payload.state);
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
      (payload.bots || []).slice(0, 8).forEach((bot) => {
        const status = String(bot.status || 'Неизвестно');
        const stateClass = status.includes('вним') || status.includes('Требует') ? 'warn' : status.includes('Выключ') ? 'off' : '';
        const row = document.createElement('div');
        row.className = 'bot-row';
        row.innerHTML = `<div><b>${bot.name || 'AI-бот'}</b><small>${bot.short || bot.responsibility || 'Модуль SharipovAI'}</small></div><span class="bot-state ${stateClass}">${bot.health_score || 0}%</span>`;
        list.appendChild(row);
      });
    } catch (_) {
      if (list) list.innerHTML = '<div class="bot-row"><div><b>AI-боты недоступны</b><small>Сервер ещё деплоится или API временно недоступен</small></div><span class="bot-state warn">!</span></div>';
    }
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
      addMessage('ai', 'Напиши команду: «найди выгодные условия», «купи BTC», «поставь баланс 20000», «мониторинг онлайн» или «анализ рынка».');
      return;
    }
    addMessage('user', value);
    if (input) input.value = '';
    try {
      const payload = await runDemoCommand(value);
      renderState(payload.state);
      addMessage('ai', payload.reply || 'Команда выполнена в демо-счёте.');
    } catch (_) {
      addMessage('ai', 'Команда не выполнена. Нужен свежий деплой backend или проверка Render logs.');
    }
  }

  function showPanel(targetId) {
    $$('.mini-app-shell .mini-section').forEach((panel) => panel.classList.toggle('active-panel', panel.id === targetId));
    $$('.mini-tabs button').forEach((item) => item.classList.toggle('active', item.dataset.miniTab === targetId));
  }

  function installTabs() {
    $$('[data-mini-tab]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        const targetId = button.dataset.miniTab || 'overview-section';
        if (!document.getElementById(targetId)) return;
        showPanel(targetId);
      });
    });
    showPanel('overview-section');
  }

  function installLiveHandlers() {
    installMiniStyles();
    ensureAllSiteFunctions();
    injectCostFields();
    localizeMiniApp();
    installTabs();
    installRiskPersistence();
    const form = $('#ai-command-form');
    if (form) {
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        submitCommand();
      }, true);
    }
    $$('[data-prompt]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        submitCommand(button.dataset.prompt || button.textContent || 'портфель');
      }, true);
    });

    const riskCard = $('.risk-panel');
    if (riskCard && !$('#demo-balance-input')) {
      const box = document.createElement('div');
      box.className = 'info-box';
      box.innerHTML = '<b>Демо-баланс</b><br><input id="demo-balance-input" type="number" min="1" value="10000" style="width:100%;margin-top:10px;border-radius:14px;padding:12px;background:#06111f;color:white;border:1px solid #1e90ff44"><button class="save-button" type="button" id="set-demo-balance">Установить демо-баланс</button>';
      riskCard.appendChild(box);
      $('#set-demo-balance')?.addEventListener('click', () => {
        const amount = $('#demo-balance-input')?.value || '10000';
        submitCommand(`поставь баланс ${amount}`);
      });
    }
  }

  window.addEventListener('DOMContentLoaded', () => {
    installLiveHandlers();
    loadDemoState();
    loadStressLab();
    loadBots();
    setInterval(loadDemoState, 15000);
    setInterval(loadBots, 30000);
  });
})();
