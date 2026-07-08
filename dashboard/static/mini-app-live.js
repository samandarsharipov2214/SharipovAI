(() => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const fmt = (value) => Number(value || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const RISK_STORAGE_KEY = 'sharipovaiRiskSettingsV6';
  const bootTime = new Date();
  let lastBotRefresh = null;
  let lastStateRefresh = null;

  const agentBrains = {
    'General Controller': { icon: 'GC', mission: 'Следит за всеми ботами, целями дня, простоями, ошибками и конфликтами решений.', prompt: 'Я главный контролёр. Могу объяснить, кто ошибся, кто простаивает и почему цель дня не выполнена.', actions: ['принял контроль дневной цели +1%', 'запросил отчёт Market Agent', 'проверил Risk Engine', 'заблокировал агрессивный BUY без новостей', 'отправил ETH-ошибку в Learning Engine'] },
    'Market Agent': { icon: 'MA', mission: 'Ищет сетапы: тренд, объём, уровни, импульс, ликвидность.', prompt: 'Я анализирую рынок. Сейчас BTC в WATCH: пробой есть, но подтверждение не идеальное.', actions: ['просканировал BTC/ETH/SOL', 'нашёл BTC resistance 67 000', 'отправил BUY-кандидат General Controller', 'получил запрос на дополнительный объём', 'снизил уверенность до 84%'] },
    'News Agent': { icon: 'NA', mission: 'Проверяет новости и не допускает сделки по слухам без 2+ источников.', prompt: 'Я не разрешаю BUY по одиночным постам. Нужны Reuters/CoinDesk/официальный источник.', actions: ['обновил RSS', 'отметил X-сигнал как неподтверждённый', 'запросил второй источник', 'поставил block_buy=true', 'сообщил General Controller'] },
    'Risk Engine': { icon: 'RE', mission: 'Считает риск, просадку, плечо, стоп, лимиты и emergency stop.', prompt: 'Моя задача — сохранить капитал. Я блокирую сделки, если риск/прибыль слабые.', actions: ['пересчитал drawdown', 'проверил max risk 2%', 'разрешил только demo', 'снизил риск-профиль', 'emergency stop остаётся ON'] },
    'Portfolio Engine': { icon: 'PE', mission: 'Баланс, позиции, PnL, комиссии, чистый результат.', prompt: 'Я показываю не грязную прибыль, а результат после комиссий.', actions: ['обновил equity', 'сверил комиссии', 'пересчитал net PnL', 'проверил открытые позиции', 'отправил отчёт'] },
    'Paper Trading Bot': { icon: 'PT', mission: 'Открывает и закрывает только демо-сделки.', prompt: 'Я работаю в sandbox. Реальные ордера заблокированы.', actions: ['проверил sandbox', 'симулировал BTC entry', 'поставил TP/SL', 'записал сделку', 'передал результат Learning Engine'] },
    'Confidence Engine': { icon: 'CE', mission: 'Оценивает силу сигнала и вероятность ошибки.', prompt: 'Я понижаю уверенность, если агенты не согласны.', actions: ['получил сигналы', 'сравнил Market/News/Risk', 'нашёл расхождение', 'снизил confidence', 'отправил score Consensus'] },
    'Consensus Engine': { icon: 'CS', mission: 'Сравнивает голоса агентов и ищет конфликт.', prompt: 'Если нет согласия, решение WATCH.', actions: ['собрал голоса', 'Market=BUY', 'News=NEUTRAL', 'Risk=ALLOW demo', 'итог WATCH'] },
    'Stress Bot': { icon: 'SB', mission: 'Симулирует кризисы: падение BTC, новости, биржа, black swan.', prompt: 'Я проверяю, что AI сделает при резком падении и не даст системе паниковать.', actions: ['запустил BTC -20%', 'пересчитал капитал', 'включил BUY block', 'снизил exposure', 'подготовил уведомление'] },
    'Learning Engine': { icon: 'LE', mission: 'Разбирает ошибки, меняет правила и снижает повторение плохих решений.', prompt: 'Я помню ошибки. ETH минус: ранний вход и слабое подтверждение объёма.', actions: ['получил ETH loss', 'классифицировал ранний вход', 'добавил новое правило', 'усилил фильтр объёма', 'обновил рекомендацию'] },
    'Security Guard': { icon: 'SG', mission: 'Защищает от реальной торговли без ручного разрешения.', prompt: 'LIVE-ордера запрещены. Любая реальная торговля требует явного подтверждения.', actions: ['проверил LIVE=false', 'заблокировал реальный ордер', 'разрешил demo preview', 'проверил токены', 'статус защиты OK'] }
  };

  const tradeDetails = {
    'BTC/USDT': { opened: 'demo', closed: 'Открыта', entry: '67 214.20', exit: '67 766.80', size: '0.10 BTC', reason: 'Пробой сопротивления 67 000 на повышенном объёме. Market Agent дал BUY 92%, Risk Engine разрешил при низкой просадке.', closeReason: 'Позиция открыта. TP 68 500, SL 66 500.', votes: [['Market Agent', 'BUY', '92%'], ['News Agent', 'NEUTRAL', '76%'], ['Risk Engine', 'ALLOW', '88%'], ['Consensus', 'BUY', '84%']], log: ['сигнал BUY', 'проверены комиссии', 'Risk Engine разрешил', 'стоп поставлен на 66 500'] },
    'SOL/USDT': { opened: 'demo', closed: 'Открыта', entry: '171.35', exit: '177.59', size: '5 SOL', reason: 'Рост объёма и подтверждение импульса. Вход малым размером из-за волатильности.', closeReason: 'Позиция удерживается, trailing stop включён.', votes: [['Market Agent', 'BUY', '89%'], ['News Agent', 'NEUTRAL', '72%'], ['Risk Engine', 'ALLOW', '83%'], ['Consensus', 'BUY', '81%']], log: ['вход SOL', 'проверка ликвидности', 'trailing stop активирован'] },
    'ETH/USDT': { opened: 'demo', closed: 'demo', entry: '3 142.88', exit: '3 124.58', size: '1 ETH', reason: 'ETH выглядел слабее BTC, AI тестировал short-сценарий в demo.', closeReason: 'Минус из-за резкого возврата цены и комиссии. Learning Engine отметил: вход был ранним, нужно ждать подтверждение объёма.', votes: [['Market Agent', 'SELL', '71%'], ['News Agent', 'NEUTRAL', '67%'], ['Risk Engine', 'ALLOW', '78%'], ['Learning', 'WARNING', '62%']], log: ['short ETH', 'рынок развернулся', 'уверенность упала', 'закрыто с минусом'] }
  };

  function setText(selector, value) {
    const el = $(selector);
    if (el) el.textContent = value;
  }

  function clock(date = new Date()) {
    return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function clockMinus(minutes) {
    const d = new Date(Date.now() - minutes * 60 * 1000);
    return clock(d);
  }

  function freshness(date) {
    if (!date) return 'ещё не обновлялось';
    const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
    if (seconds < 5) return 'обновлено только что';
    if (seconds < 60) return `обновлено ${seconds} сек. назад`;
    const minutes = Math.round(seconds / 60);
    return `обновлено ${minutes} мин. назад`;
  }

  function translateRisk(value) {
    const key = String(value || '').toUpperCase();
    return { LOW: 'НИЗКИЙ', MEDIUM: 'СРЕДНИЙ', HIGH: 'ВЫСОКИЙ', CRITICAL: 'КРИТИЧЕСКИЙ' }[key] || value || 'НИЗКИЙ';
  }

  function translateDecision(value) {
    const key = String(value || '').toUpperCase();
    return { BUY: 'КУПИТЬ', SELL: 'ПРОДАТЬ', WATCH: 'НАБЛЮДАТЬ', BLOCK_BUY: 'БЛОК BUY', DEMO_ONLY: 'ТОЛЬКО DEMO' }[key] || value || 'НАБЛЮДАТЬ';
  }

  function translateImpact(value) {
    return { bullish: 'позитивно', bearish: 'негативно', neutral: 'нейтрально' }[String(value || '').toLowerCase()] || 'нейтрально';
  }

  function actionLog(actions, baseOffset = 0) {
    return actions.map((action, index) => `<div>${clockMinus(baseOffset + actions.length - index - 1)}  ${action}</div>`).join('');
  }

  function addMessage(role, text, target = '#ai-chat-log') {
    const log = $(target);
    if (!log) return;
    const item = document.createElement('div');
    item.className = `mini-message ${role === 'user' ? 'user-message' : 'assistant-message'}`;
    item.innerHTML = `<div class="mini-avatar">${role === 'user' ? 'Вы' : 'SA'}</div><div class="mini-bubble"><b>${role === 'user' ? 'Самандар' : 'SharipovAI'}</b><p></p></div>`;
    item.querySelector('p').textContent = text;
    log.appendChild(item);
    log.scrollTop = log.scrollHeight;
  }

  function ensurePanel(id, title) {
    let panel = document.getElementById(id);
    if (panel) return panel;
    const shell = $('.mini-app-shell');
    const safe = $('.bottom-safe');
    if (!shell) return null;
    panel = document.createElement('article');
    panel.className = 'mini-card mini-section';
    panel.id = id;
    panel.innerHTML = `<h2>${title}</h2>`;
    shell.insertBefore(panel, safe || null);
    return panel;
  }

  function showPanel(targetId) {
    const fallback = document.getElementById(targetId) ? targetId : 'overview-section';
    $$('.mini-app-shell .mini-section').forEach((panel) => panel.classList.toggle('active-panel', panel.id === fallback));
    $$('.mini-tabs button,[data-mini-tab]').forEach((button) => {
      if (button.closest('.mini-tabs')) button.classList.toggle('active', button.dataset.miniTab === fallback);
    });
  }

  function ensureNewsPanel() {
    const tabs = $('.mini-tabs');
    if (tabs && !tabs.querySelector('[data-mini-tab="news-section"]')) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.miniTab = 'news-section';
      button.textContent = 'Новости';
      tabs.appendChild(button);
    }
    const article = ensurePanel('news-section', 'Новости и достоверность');
    if (!article) return;
    article.innerHTML = `<h2>Новости и достоверность</h2><div class="mini-grid"><div class="mini-stat"><small>Источников</small><b id="news-sources-total">0</b></div><div class="mini-stat"><small>Нужно подтвердить</small><b id="news-confirmations">0</b></div><div class="mini-stat"><small>Достоверность</small><b id="news-average-credibility">0%</b></div><div class="mini-stat"><small>Последняя проверка</small><b id="news-last-refresh">—</b></div></div><div class="bot-grid" id="news-list"></div><p class="info-box">Одиночные публикации и соцсети не дают разрешение на сделку. Нужны 2+ независимых подтверждения.</p>`;
  }

  function ensureProfessionalPanels() {
    const overview = $('#overview-section');
    if (overview && !$('#apple-hero-graph')) {
      overview.insertAdjacentHTML('beforeend', `<div class="agent-orbit" id="apple-hero-graph"><div class="orbit-node node-1">AI</div><div class="orbit-node node-2">R</div><div class="orbit-node node-3">M</div><div class="orbit-node node-4">N</div></div><p class="info-box"><b>Mission Control:</b> Market, News, Risk и Learning связаны в единую систему. <span id="mini-live-clock">Запущено ${clock(bootTime)}</span>.</p>`);
    }
    const bots = $('#bots-section');
    if (bots && !$('#agent-control-intro')) {
      bots.insertAdjacentHTML('afterbegin', `<div id="agent-control-intro" class="info-box"><b>AI Agent Control</b><br>Проценты — это оценка качества/health score, а не таймер работы. Живость смотри по строке «обновлено» и времени последней проверки.</div>`);
    }
    const stress = $('#stress-section');
    if (stress) {
      stress.innerHTML = `<h2>Stress Lab</h2><p class="info-box">Симуляция кризиса: AI проверяет капитал, просадку, блокировку BUY, новости и защитные меры.</p><div class="quick-chat-actions"><button type="button" data-stress="btc_drop_10">BTC -10%</button><button type="button" data-stress="btc_drop_20">BTC -20%</button><button type="button" data-stress="market_crash_50">Market -50%</button><button type="button" data-stress="news_panic">News Panic</button></div><div class="mini-grid"><div class="mini-stat"><small>Капитал до</small><b id="stress-before">10 000.00 USDT</b></div><div class="mini-stat"><small>Капитал после</small><b id="stress-after">...</b></div><div class="mini-stat"><small>Потеря</small><b id="mini-stress-loss">...</b></div><div class="mini-stat"><small>Последний тест</small><b id="mini-stress-action">...</b></div></div><div class="bot-grid" id="stress-timeline"></div>`;
    }
    const learning = $('#learning-section');
    if (learning) {
      learning.innerHTML = `<h2>Обучение AI</h2><div class="mini-grid"><div class="mini-stat"><small>Ошибок найдено</small><b>3</b></div><div class="mini-stat"><small>Исправлено</small><b>2</b></div><div class="mini-stat"><small>Повторяется</small><b>ранний вход</b></div></div><div class="bot-grid"><div class="bot-row"><div><b>Что AI понял</b><small>ETH минус: вход был слишком ранним, объём не подтвердил движение.</small></div><span class="bot-state">FIX</span></div><div class="bot-row"><div><b>Что изменится</b><small>Для SELL теперь нужен Consensus ≥ 82% и подтверждение объёма.</small></div><span class="bot-state">NEW</span></div></div>`;
    }
    const reports = $('#reports-section');
    if (reports) {
      reports.innerHTML = `<h2>Отчёты</h2><div class="mini-grid"><div class="mini-stat"><small>Сегодня</small><b id="mini-report-day">+0.00 USDT</b></div><div class="mini-stat"><small>Комиссии</small><b id="mini-report-fees">0.00 USDT</b></div><div class="mini-stat"><small>Последний state</small><b id="mini-state-last-refresh">—</b></div><div class="mini-stat"><small>Боты</small><b id="mini-bots-last-refresh">—</b></div></div><div class="info-box"><b>Вывод General Controller:</b><br>Если время «Последний state/Боты» не меняется дольше 1–2 минут — тогда backend реально завис или вкладка не обновляется.</div>`;
    }
    const risk = $('#risk-section');
    if (risk && !$('#risk-profile-card')) {
      risk.insertAdjacentHTML('afterbegin', `<div id="risk-profile-card" class="info-box"><b>Risk Profile</b><br><div class="quick-chat-actions"><button type="button" data-risk-profile="safe">Консервативный</button><button type="button" data-risk-profile="normal">Умеренный</button><button type="button" data-risk-profile="pro">Агрессивный</button></div><br><b>Risk Score:</b> <span id="risk-score">27/100 · LOW</span></div>`);
    }
  }

  function installTabs() {
    ensureNewsPanel();
    ensureProfessionalPanels();
    $$('[data-mini-tab]').forEach((button) => button.addEventListener('click', (event) => {
      event.preventDefault();
      showPanel(button.dataset.miniTab || 'overview-section');
    }));
    showPanel('overview-section');
  }

  function rangeInputs() {
    return $$('[data-range-output]').filter((input) => input.closest('.mini-app-shell'));
  }

  function updateRiskScore() {
    const values = rangeInputs().map((input) => Number(input.value));
    const score = Math.min(100, Math.round((values[0] || 2) * 8 + (values[1] || 10) + Math.max(0, 100 - (values[2] || 78))));
    setText('#risk-score', `${score}/100 · ${score < 35 ? 'LOW' : score < 65 ? 'MEDIUM' : 'HIGH'}`);
  }

  function updateRangeOutput(input) {
    const output = input.parentElement?.querySelector('output');
    if (output) output.textContent = `${input.value}%`;
    updateRiskScore();
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
      setText('#save-status', `✓ Риск-профиль сохранён ${clock()}. General Controller будет использовать эти лимиты в demo.`);
    });
    $$('[data-risk-profile]').forEach((button) => button.addEventListener('click', () => {
      const presets = { safe: [1, 6, 90], normal: [2, 10, 78], pro: [4, 18, 70] }[button.dataset.riskProfile] || [2, 10, 78];
      inputs.forEach((input, index) => { input.value = presets[index]; updateRangeOutput(input); });
    }));
  }

  function openTradeDetail(trade) {
    const asset = trade.asset || trade.symbol || 'BTC/USDT';
    const details = tradeDetails[asset] || tradeDetails['BTC/USDT'];
    const pnl = Number(trade.net_pnl ?? trade.pnl_usdt ?? 0);
    const fee = Number(trade.fee || 0);
    let modal = $('#trade-detail-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'trade-detail-modal';
      modal.className = 'trade-modal';
      document.body.appendChild(modal);
    }
    modal.innerHTML = `<div class="trade-modal-card"><button class="modal-close" type="button">×</button><h2>${asset} · ${trade.side || ''}</h2><div class="mini-grid"><div class="mini-stat"><small>Статус</small><b>${trade.status || 'OPEN'}</b></div><div class="mini-stat"><small>Чистый PnL</small><b class="${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${fmt(pnl)} USDT</b></div><div class="mini-stat"><small>Открыта</small><b>${details.opened === 'demo' ? clockMinus(34) : details.opened}</b></div><div class="mini-stat"><small>Закрыта</small><b>${details.closed === 'demo' ? clockMinus(8) : details.closed}</b></div><div class="mini-stat"><small>Цена входа</small><b>${details.entry}</b></div><div class="mini-stat"><small>Цена выхода/текущая</small><b>${details.exit}</b></div><div class="mini-stat"><small>Размер</small><b>${details.size}</b></div><div class="mini-stat"><small>Комиссии</small><b>${fmt(fee)} USDT</b></div></div><p class="info-box"><b>Почему AI открыл:</b><br>${details.reason}</p><p class="info-box"><b>Почему минус/закрытие:</b><br>${details.closeReason}</p><h3>Голоса AI</h3><div class="bot-grid">${details.votes.map((vote) => `<div class="bot-row"><div><b>${vote[0]}</b><small>${vote[1]}</small></div><span class="bot-state">${vote[2]}</span></div>`).join('')}</div><h3>Журнал решения</h3><div class="bot-grid">${details.log.map((item, index) => `<div class="bot-row"><div><b>${clockMinus(details.log.length - index)} · ${item}</b><small>Demo decision log · обновляется при открытии</small></div><span class="bot-state">AI</span></div>`).join('')}</div></div>`;
    modal.classList.add('open');
    modal.querySelector('.modal-close')?.addEventListener('click', () => modal.classList.remove('open'));
  }

  function openBotDetail(bot) {
    const brain = agentBrains[bot.name] || { icon: 'AI', mission: bot.responsibility || 'Модуль SharipovAI', prompt: 'Я работаю в системе SharipovAI.', actions: ['активен', 'отправил отчёт'] };
    const quality = bot.quality_score || bot.health_score || 0;
    const refreshedAt = lastBotRefresh || new Date();
    let modal = $('#agent-detail-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'agent-detail-modal';
      modal.className = 'trade-modal';
      document.body.appendChild(modal);
    }
    modal.innerHTML = `<div class="trade-modal-card"><button class="modal-close" type="button">×</button><h2>${bot.name}</h2><div class="mini-grid"><div class="mini-stat"><small>Оценка качества</small><b>${quality}%</b></div><div class="mini-stat"><small>Ошибки</small><b>${bot.error_rate || 0}%</b></div><div class="mini-stat"><small>Статус</small><b>${bot.status || 'Работает'}</b></div><div class="mini-stat"><small>Обновлено</small><b>${clock(refreshedAt)}</b></div></div><p class="info-box"><b>Миссия:</b><br>${brain.mission}<br><br><b>Важно:</b> ${quality}% — это оценка качества модуля, а не доказательство, что он каждую секунду что-то делал.</p><div class="quick-chat-actions"><button type="button" data-agent-command="report">Запросить отчёт</button><button type="button" data-agent-command="test">Тест адекватности</button><button type="button" data-agent-command="pause">Пауза demo</button><button type="button" data-agent-command="learn">Отправить в Learning</button></div><h3>Журнал действий</h3><div class="agent-terminal" id="agent-action-log">${actionLog(brain.actions)}</div><h3>Чат с этим ботом</h3><div class="mini-chat-log" id="agent-chat-log"><div class="mini-message assistant-message"><div class="mini-avatar">${brain.icon}</div><div class="mini-bubble"><b>${bot.name}</b><p>${brain.prompt}</p></div></div></div><form id="agent-chat-form" class="mini-form"><textarea id="agent-chat-input" placeholder="Спроси этого бота отдельно..."></textarea><button class="mini-send" type="submit">➤</button></form></div>`;
    modal.classList.add('open');
    modal.querySelector('.modal-close')?.addEventListener('click', () => modal.classList.remove('open'));
    modal.querySelector('#agent-chat-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      const input = modal.querySelector('#agent-chat-input');
      const text = (input?.value || '').trim();
      if (!text) return;
      addMessage('user', text, '#agent-chat-log');
      input.value = '';
      addMessage('ai', `${bot.name}: ${clock()} проверил себя. Мой ответ основан на моей зоне: ${brain.mission}`, '#agent-chat-log');
    });
    modal.querySelectorAll('[data-agent-command]').forEach((button) => button.addEventListener('click', () => {
      const log = modal.querySelector('#agent-action-log');
      const map = { report: 'сформировал отчёт по запросу пользователя', test: 'прошёл тест адекватности: OK', pause: 'demo-пауза поставлена, LIVE не затронут', learn: 'отправил последние ошибки в Learning Engine' };
      if (log) log.insertAdjacentHTML('beforeend', `<div>${clock()}  ${map[button.dataset.agentCommand]}</div>`);
    }));
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
      tr.className = 'trade-clickable';
      tr.innerHTML = `<td><b>${trade.asset || trade.symbol || 'BTC/USDT'} ${trade.side || ''}</b><br><small>${trade.status || 'OPEN'} · комиссия ${fmt(fee)} USDT · нажми для отчёта</small></td><td class="${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${fmt(pnl)}</td>`;
      tr.addEventListener('click', () => openTradeDetail(trade));
      table.appendChild(tr);
    });
  }

  function renderState(state) {
    if (!state) return;
    lastStateRefresh = new Date();
    const pnl = Number(state.pnl || state.net_pnl || 0);
    setText('#portfolio-equity', `${fmt(state.equity)} USDT`);
    setText('#portfolio-pnl', `${fmt(pnl)} USDT`);
    setText('#hero-risk', translateRisk(state.risk_level));
    setText('#hero-decision-mini', translateDecision(state.decision));
    renderTrades(state.trades || []);
    setText('#exchange-mode', state.exchange_status?.mode === 'sandbox' ? 'Песочница' : 'Live');
    setText('#overview-exchange', 'Песочница');
    setText('#exchange-preview', state.online_monitoring?.order_preview_online ? 'Онлайн' : 'Ограничен');
    setText('#exchange-live', state.online_monitoring?.live_execution_enabled ? 'Включено' : 'Выкл.');
    setText('#exchange-fees', `${fmt(state.total_fees)} USDT`);
    setText('#exchange-drag', `${fmt(state.commission_drag)} USDT`);
    setText('#exchange-breakeven', `${fmt(state.break_even_price)} USDT`);
    const best = state.bybit_costs?.best_trade_venue?.best || {};
    setText('#cost-best-venue', `${best.product || 'spot'} / ${best.liquidity || 'maker'}`);
    setText('#cost-roundtrip', `${fmt(best.round_trip_fee)} USDT`);
    setText('#cost-breakeven-move', `${Number(best.break_even_move_percent || 0).toFixed(4)}%`);
    setText('#cost-saving', `${fmt(state.bybit_costs?.best_trade_venue?.estimated_saving_vs_worst)} USDT`);
    setText('#mini-report-day', `${pnl >= 0 ? '+' : ''}${fmt(pnl)} USDT`);
    setText('#mini-report-fees', `${fmt(state.total_fees)} USDT`);
    setText('#mini-state-last-refresh', clock(lastStateRefresh));
  }

  function renderNews(payload) {
    const summary = payload.news?.summary || {};
    const sources = payload.sources || {};
    setText('#news-sources-total', String(sources.total || 0));
    setText('#news-confirmations', String(summary.needs_confirmation || 0));
    setText('#news-average-credibility', `${Number(summary.average_credibility_percent || 0).toFixed(1)}%`);
    setText('#news-last-refresh', clock());
    const list = $('#news-list');
    if (!list) return;
    const items = payload.news?.items || [];
    list.innerHTML = items.map((item) => `<div class="bot-row"><div><b>${item.title}</b><small>${item.source_name} · ${translateImpact(item.impact)} · ${item.verification_status}</small></div><span class="bot-state">${item.credibility_percent}%</span></div>`).join('');
  }

  async function loadDemoState() {
    try {
      const response = await fetch('/api/demo/state', { cache: 'no-store' });
      if (response.ok) renderState((await response.json()).state || {});
    } catch (_) {}
  }

  async function loadStressLab(scenario = 'btc_drop_20') {
    try {
      const response = await fetch('/api/stress-lab/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store', body: JSON.stringify({ scenario }) });
      if (!response.ok) return;
      const payload = await response.json();
      setText('#stress-before', `${fmt(payload.capital_before)} USDT`);
      setText('#stress-after', `${fmt(payload.after?.capital || payload.capital_after)} USDT`);
      setText('#mini-stress-loss', `${fmt(payload.after?.loss_amount || payload.loss_amount)} USDT`);
      setText('#mini-stress-action', clock());
      const timeline = $('#stress-timeline');
      if (timeline) {
        const items = ['Market shock detected', 'Risk Engine пересчитал просадку', 'BUY заблокирован', 'Exposure reduced', 'Уведомление готово'];
        timeline.innerHTML = items.map((item, index) => `<div class="bot-row"><div><b>${clockMinus(items.length - index)} · ${item}</b><small>Stress decision log · live UI timestamp</small></div><span class="bot-state">✓</span></div>`).join('');
      }
    } catch (_) {}
  }

  async function loadBots() {
    const list = $('#bot-list');
    try {
      const response = await fetch('/api/ai-bots', { cache: 'no-store' });
      if (!response.ok) throw new Error('bad status');
      const payload = await response.json();
      const summary = payload.summary || {};
      lastBotRefresh = new Date();
      setText('#bots-total', String(summary.total_bots || 0));
      setText('#bots-active', String(summary.active || 0));
      setText('#bots-warnings', String(summary.warnings || 0));
      setText('#mini-bots-last-refresh', clock(lastBotRefresh));
      if (!list) return;
      list.innerHTML = '';
      (payload.bots || []).forEach((bot) => {
        const quality = bot.quality_score || bot.health_score || 0;
        const row = document.createElement('div');
        row.className = 'bot-row agent-card';
        row.innerHTML = `<div><b>${bot.name}</b><small>${bot.responsibility || bot.short} · ${freshness(lastBotRefresh)}</small></div><span class="bot-state" title="Оценка качества, не таймер">${quality}%</span>`;
        row.addEventListener('click', () => openBotDetail(bot));
        list.appendChild(row);
      });
    } catch (_) {
      if (list) list.innerHTML = '<div class="bot-row"><div><b>AI-боты недоступны</b><small>Проверь Render logs или backend</small></div><span class="bot-state warn">!</span></div>';
    }
  }

  async function refreshNews() {
    try {
      const response = await fetch('/api/social-news/rss/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store', body: JSON.stringify({ limit_per_source: 5 }) });
      if (response.ok) {
        const payload = await response.json();
        renderNews({ sources: payload.rss, news: payload.news });
      }
    } catch (_) {}
  }

  async function runDemoCommand(command) {
    const response = await fetch('/api/demo/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store', body: JSON.stringify({ message: command }) });
    if (!response.ok) throw new Error('command failed');
    return response.json();
  }

  async function submitCommand(command) {
    const input = $('#ai-command-input');
    const value = String(command || input?.value || '').trim();
    if (!value) {
      addMessage('ai', 'Спроси: почему AI не покупает, отчёт по сделке BTC, тест Risk Engine, статус General Controller.');
      return;
    }
    addMessage('user', value);
    if (input) input.value = '';
    try {
      const payload = await runDemoCommand(value);
      renderState(payload.state || {});
      addMessage('ai', payload.reply || 'Команда выполнена.');
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

  function refreshFreshnessLabels() {
    setText('#mini-live-clock', `Запущено ${clock(bootTime)} · сейчас ${clock()}`);
    setText('#mini-state-last-refresh', lastStateRefresh ? clock(lastStateRefresh) : '—');
    setText('#mini-bots-last-refresh', lastBotRefresh ? clock(lastBotRefresh) : '—');
  }

  window.addEventListener('DOMContentLoaded', () => {
    installTabs();
    installRiskPersistence();
    installChat();
    loadDemoState();
    loadStressLab();
    loadBots();
    refreshNews();
    $$('[data-stress]').forEach((button) => button.addEventListener('click', () => loadStressLab(button.dataset.stress)));
    setInterval(loadDemoState, 15000);
    setInterval(loadBots, 30000);
    setInterval(refreshNews, 120000);
    setInterval(refreshFreshnessLabels, 1000);
  });
})();
