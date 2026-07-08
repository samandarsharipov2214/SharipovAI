(() => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const fmt = (value) => Number(value || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtRate = (value) => `${(Number(value || 0) * 100).toFixed(4)}%`;
  const RISK_STORAGE_KEY = 'sharipovaiRiskSettingsV4';
  let lastState = null;

  function setText(selector, value) { const el = $(selector); if (el) el.textContent = value; }
  function translateRisk(value) { const key = String(value || '').toUpperCase(); return { LOW: 'НИЗКИЙ', MEDIUM: 'СРЕДНИЙ', HIGH: 'ВЫСОКИЙ', CRITICAL: 'КРИТИЧЕСКИЙ' }[key] || value || 'НИЗКИЙ'; }
  function translateDecision(value) { const key = String(value || '').toUpperCase(); return { BUY: 'КУПИТЬ', SELL: 'ПРОДАТЬ', WATCH: 'НАБЛЮДАТЬ', IGNORE: 'ПРОПУСТИТЬ', NO_DECISION: 'НЕТ РЕШЕНИЯ', BLOCK_BUY: 'БЛОК BUY' }[key] || value || 'НАБЛЮДАТЬ'; }
  function translateImpact(value) { return { bullish: 'позитивно', bearish: 'негативно', neutral: 'нейтрально' }[String(value || '').toLowerCase()] || 'нейтрально'; }

  const tradeDetails = {
    'BTC/USDT': { opened: '09.07.2026 · 12:48', closed: 'Открыта', duration: '2ч 18м', entry: '67 214.20', exit: '67 766.80', size: '0.10 BTC', leverage: 'x1 demo', roi: '+0.66%', reason: 'Пробой сопротивления 67 000 на повышенном объёме. Market Agent дал BUY 92%, Risk Engine разрешил при низкой просадке.', closeReason: 'Позиция открыта. TP 68 500, SL 66 500.', votes: [['Market Agent','BUY','92%'], ['News Agent','NEUTRAL','76%'], ['Risk Engine','ALLOW','88%'], ['Consensus','BUY','84%']], log: ['12:48 сигнал BUY','12:49 проверены комиссии','12:50 Risk Engine разрешил','13:05 стоп поставлен на 66 500'] },
    'SOL/USDT': { opened: '09.07.2026 · 13:20', closed: 'Открыта', duration: '1ч 42м', entry: '171.35', exit: '177.59', size: '5 SOL', leverage: 'x1 demo', roi: '+3.39%', reason: 'Рост объёма и подтверждение импульса. Вход малым размером из-за волатильности.', closeReason: 'Позиция удерживается, trailing stop включён.', votes: [['Market Agent','BUY','89%'], ['News Agent','NEUTRAL','72%'], ['Risk Engine','ALLOW','83%'], ['Consensus','BUY','81%']], log: ['13:20 вход SOL','13:22 проверка ликвидности','13:30 trailing stop активирован'] },
    'ETH/USDT': { opened: '09.07.2026 · 10:15', closed: '09.07.2026 · 11:04', duration: '49м', entry: '3 142.88', exit: '3 124.58', size: '1 ETH', leverage: 'x1 demo', roi: '-0.69%', reason: 'ETH выглядел слабее BTC, AI тестировал short-сценарий в demo.', closeReason: 'Минус из-за резкого возврата цены и комиссии. Learning Engine отметил: вход был ранним, нужно ждать подтверждение объёма.', votes: [['Market Agent','SELL','71%'], ['News Agent','NEUTRAL','67%'], ['Risk Engine','ALLOW','78%'], ['Learning','WARNING','62%']], log: ['10:15 short ETH','10:21 рынок развернулся','10:47 уверенность упала','11:04 закрыто с минусом'] }
  };

  function addMessage(role, text) {
    const log = $('#ai-chat-log'); if (!log) return;
    const item = document.createElement('div');
    item.className = `mini-message ${role === 'user' ? 'user-message' : 'assistant-message'}`;
    item.innerHTML = `<div class="mini-avatar">${role === 'user' ? 'Вы' : 'SA'}</div><div class="mini-bubble"><b>${role === 'user' ? 'Самандар' : 'SharipovAI'}</b><p></p></div>`;
    item.querySelector('p').textContent = text; log.appendChild(item); log.scrollTop = log.scrollHeight;
  }

  function ensurePanel(id, title) {
    let panel = document.getElementById(id);
    if (panel) return panel;
    const shell = $('.mini-app-shell'); const safe = $('.bottom-safe'); if (!shell) return null;
    panel = document.createElement('article'); panel.className = 'mini-card mini-section'; panel.id = id; panel.innerHTML = `<h2>${title}</h2>`;
    shell.insertBefore(panel, safe || null); return panel;
  }

  function ensureProfessionalPanels() {
    const stress = $('#stress-section');
    if (stress) stress.innerHTML = `<h2>Stress Lab</h2><p class="info-box">Это не “просто тест”. Это симуляция кризиса: AI проверяет, что будет с капиталом, если рынок резко упадёт, новости вызовут панику или биржа даст сбой.</p><div class="quick-chat-actions"><button type="button" data-stress="btc_drop_10">BTC -10%</button><button type="button" data-stress="btc_drop_20">BTC -20%</button><button type="button" data-stress="market_crash_50">Market -50%</button><button type="button" data-stress="news_panic">News Panic</button></div><div class="mini-grid"><div class="mini-stat"><small>Капитал до</small><b id="stress-before">10 000.00 USDT</b></div><div class="mini-stat"><small>Капитал после</small><b id="stress-after">...</b></div><div class="mini-stat"><small>Потеря</small><b id="mini-stress-loss">...</b></div><div class="mini-stat"><small>Статус</small><b id="mini-stress-action">...</b></div></div><div class="bot-grid" id="stress-timeline"></div>`;

    const learning = $('#learning-section');
    if (learning) learning.innerHTML = `<h2>Обучение AI</h2><div class="mini-grid"><div class="mini-stat"><small>Ошибок найдено</small><b>3</b></div><div class="mini-stat"><small>Исправлено</small><b>2</b></div><div class="mini-stat"><small>Повторяется</small><b>ранний вход</b></div></div><div class="bot-grid"><div class="bot-row"><div><b>Что AI понял</b><small>ETH минус: вход был слишком ранним, объём не подтвердил движение.</small></div><span class="bot-state">FIX</span></div><div class="bot-row"><div><b>Что изменится</b><small>Для SELL теперь нужен Consensus ≥ 82% и подтверждение объёма.</small></div><span class="bot-state">NEW</span></div><div class="bot-row"><div><b>Комиссии</b><small>Learning Engine учитывает чистый PnL после комиссии, не грязную прибыль.</small></div><span class="bot-state">OK</span></div></div>`;

    const reports = $('#reports-section');
    if (reports) reports.innerHTML = `<h2>Отчёты</h2><div class="mini-grid"><div class="mini-stat"><small>Сегодня</small><b id="mini-report-day">+51.63 USDT</b></div><div class="mini-stat"><small>Неделя</small><b>+143.20 USDT</b></div><div class="mini-stat"><small>Win Rate</small><b>66%</b></div><div class="mini-stat"><small>Profit Factor</small><b>2.41</b></div><div class="mini-stat"><small>Max Drawdown</small><b>4.2%</b></div><div class="mini-stat"><small>Комиссии</small><b id="mini-report-fees">13.67 USDT</b></div></div><div class="info-box"><b>Вывод General Controller:</b><br>День пока не достиг цели +1%, потому что Risk Engine не разрешил повышать риск без подтверждения News + Market + Consensus. Это правильное защитное поведение.</div><div class="bot-grid"><div class="bot-row"><div><b>Лучший вклад</b><small>Market Agent + SOL/BTC демо-сделки</small></div><span class="bot-state">+73.38</span></div><div class="bot-row"><div><b>Главная ошибка</b><small>ETH вход ранний, отправлен в Learning Engine</small></div><span class="bot-state warn">-21.75</span></div></div>`;

    const risk = $('#risk-section');
    if (risk && !$('#risk-profile-card')) {
      risk.insertAdjacentHTML('afterbegin', `<div id="risk-profile-card" class="info-box"><b>Risk Profile</b><br><div class="quick-chat-actions"><button type="button" data-risk-profile="safe">Консервативный</button><button type="button" data-risk-profile="normal">Умеренный</button><button type="button" data-risk-profile="pro">Агрессивный</button></div><br><b>Risk Score:</b> <span id="risk-score">27/100 · LOW</span><br><small>Цель: защищать капитал, а не гнаться за прибылью любой ценой.</small></div>`);
      risk.insertAdjacentHTML('beforeend', `<div class="bot-grid"><div class="bot-row"><div><b>Обязательно подтверждение новостей</b><small>News Agent должен иметь 2+ источника</small></div><span class="bot-state">ON</span></div><div class="bot-row"><div><b>Нужен Consensus</b><small>Минимум 82% согласия агентов</small></div><span class="bot-state">ON</span></div><div class="bot-row"><div><b>Emergency Stop</b><small>Блокирует LIVE при критическом риске</small></div><span class="bot-state">ON</span></div></div>`);
    }
  }

  function showPanel(targetId) {
    const fallback = document.getElementById(targetId) ? targetId : 'overview-section';
    $$('.mini-app-shell .mini-section').forEach((panel) => panel.classList.toggle('active-panel', panel.id === fallback));
    $$('.mini-tabs button,[data-mini-tab]').forEach((button) => { if (button.closest('.mini-tabs')) button.classList.toggle('active', button.dataset.miniTab === fallback); });
  }

  function installTabs() {
    ensureNewsPanel(); ensureProfessionalPanels();
    $$('[data-mini-tab]').forEach((button) => button.addEventListener('click', (event) => { event.preventDefault(); showPanel(button.dataset.miniTab || 'overview-section'); }));
    showPanel('overview-section');
  }

  function ensureNewsPanel() {
    const tabs = $('.mini-tabs');
    if (tabs && !tabs.querySelector('[data-mini-tab="news-section"]')) {
      const button = document.createElement('button'); button.type = 'button'; button.dataset.miniTab = 'news-section'; button.textContent = 'Новости'; tabs.appendChild(button);
      button.addEventListener('click', (event) => { event.preventDefault(); showPanel('news-section'); });
    }
    if ($('#news-section')) return;
    const article = ensurePanel('news-section', 'Новости и достоверность'); if (!article) return;
    article.innerHTML = `<h2>Новости и достоверность</h2><div class="mini-grid"><div class="mini-stat"><small>Источников</small><b id="news-sources-total">0</b></div><div class="mini-stat"><small>Срочные</small><b id="news-high-urgency">0</b></div><div class="mini-stat"><small>Нужно подтвердить</small><b id="news-confirmations">0</b></div><div class="mini-stat"><small>Средняя достоверность</small><b id="news-average-credibility">0%</b></div><div class="mini-stat"><small>Низкая достоверность</small><b id="news-low-credibility">0</b></div><div class="mini-stat"><small>Действие AI</small><b id="news-ai-action">НАБЛЮДАТЬ</b></div></div><div class="bot-grid" id="news-list"></div><p class="info-box">Одиночные публикации и соцсети не дают разрешение на сделку. Нужны 2+ независимых подтверждения.</p>`;
  }

  function rangeInputs() { return $$('[data-range-output]').filter((input) => input.closest('.mini-app-shell')); }
  function updateRangeOutput(input) { const output = input.parentElement?.querySelector('output'); if (output) output.textContent = `${input.value}%`; updateRiskScore(); }
  function updateRiskScore() { const values = rangeInputs().map(i => Number(i.value)); const score = Math.min(100, Math.round((values[0] || 2) * 8 + (values[1] || 10) + Math.max(0, 100 - (values[2] || 78)))); setText('#risk-score', `${score}/100 · ${score < 35 ? 'LOW' : score < 65 ? 'MEDIUM' : 'HIGH'}`); }

  function installRiskPersistence() {
    const inputs = rangeInputs();
    try { const saved = JSON.parse(localStorage.getItem(RISK_STORAGE_KEY) || 'null'); if (Array.isArray(saved)) inputs.forEach((input, index) => { if (saved[index] !== undefined) input.value = saved[index]; }); } catch (_) {}
    inputs.forEach((input) => { updateRangeOutput(input); input.addEventListener('input', () => updateRangeOutput(input)); });
    $('#save-settings')?.addEventListener('click', () => { localStorage.setItem(RISK_STORAGE_KEY, JSON.stringify(inputs.map((input) => input.value))); setText('#save-status', '✓ Риск-профиль сохранён. General Controller будет использовать эти лимиты в demo.'); });
    $$('[data-risk-profile]').forEach(btn => btn.addEventListener('click', () => { const p = btn.dataset.riskProfile; const presets = { safe:[1,6,90], normal:[2,10,78], pro:[4,18,70] }[p] || [2,10,78]; inputs.forEach((input,i)=>{ input.value=presets[i]; updateRangeOutput(input); }); }));
  }

  function openTradeDetail(trade) {
    const asset = trade.asset || trade.symbol || 'BTC/USDT'; const d = tradeDetails[asset] || tradeDetails['BTC/USDT']; const pnl = Number(trade.net_pnl ?? trade.pnl_usdt ?? 0); const fee = Number(trade.fee || 0);
    let modal = $('#trade-detail-modal');
    if (!modal) { modal = document.createElement('div'); modal.id = 'trade-detail-modal'; modal.className = 'trade-modal'; document.body.appendChild(modal); }
    modal.innerHTML = `<div class="trade-modal-card"><button class="modal-close" type="button">×</button><h2>${asset} · ${trade.side || ''}</h2><div class="mini-grid"><div class="mini-stat"><small>Статус</small><b>${trade.status || 'OPEN'}</b></div><div class="mini-stat"><small>Чистый PnL</small><b class="${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${fmt(pnl)} USDT</b></div><div class="mini-stat"><small>Открыта</small><b>${d.opened}</b></div><div class="mini-stat"><small>Закрыта</small><b>${d.closed}</b></div><div class="mini-stat"><small>Цена входа</small><b>${d.entry}</b></div><div class="mini-stat"><small>Цена выхода/текущая</small><b>${d.exit}</b></div><div class="mini-stat"><small>Размер</small><b>${d.size}</b></div><div class="mini-stat"><small>Комиссии</small><b>${fmt(fee)} USDT</b></div></div><p class="info-box"><b>Почему AI открыл:</b><br>${d.reason}</p><p class="info-box"><b>Почему минус/закрытие:</b><br>${d.closeReason}</p><h3>Голоса AI</h3><div class="bot-grid">${d.votes.map(v=>`<div class="bot-row"><div><b>${v[0]}</b><small>${v[1]}</small></div><span class="bot-state">${v[2]}</span></div>`).join('')}</div><h3>Журнал решения</h3><div class="bot-grid">${d.log.map(x=>`<div class="bot-row"><div><b>${x}</b><small>Decision log</small></div><span class="bot-state">AI</span></div>`).join('')}</div></div>`;
    modal.classList.add('open'); modal.querySelector('.modal-close')?.addEventListener('click', () => modal.classList.remove('open')); modal.addEventListener('click', (e)=>{ if(e.target===modal) modal.classList.remove('open'); });
  }

  function renderTrades(trades) {
    const table = document.querySelector('.mini-table tbody'); if (!table) return;
    const rows = (trades || []).slice(-8).reverse(); table.innerHTML = '';
    if (!rows.length) { table.innerHTML = '<tr><td>Сделок пока нет</td><td>0.00</td></tr>'; return; }
    rows.forEach((trade) => { const pnl = Number(trade.net_pnl ?? trade.pnl_usdt ?? 0); const fee = Number(trade.fee || 0); const tr = document.createElement('tr'); tr.className = 'trade-clickable'; tr.innerHTML = `<td><b>${trade.asset || trade.symbol || 'BTC/USDT'} ${trade.side || ''}</b><br><small>${trade.status || 'OPEN'} · комиссия ${fmt(fee)} USDT · нажми для отчёта</small></td><td class="${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${fmt(pnl)}</td>`; tr.addEventListener('click', () => openTradeDetail(trade)); table.appendChild(tr); });
  }

  function renderCostIntelligence(state) { const costs = state.bybit_costs || {}; const venue = costs.best_trade_venue || {}; const best = venue.best || {}; const borrows = costs.cheapest_borrows || []; const topBorrow = borrows[0] || {}; const productMap = { spot: 'Спот', futures: 'Фьючерсы', options: 'Опционы', fiat_spot: 'Фиатный спот' }; const liquidityMap = { maker: 'мейкер', taker: 'тейкер' }; setText('#cost-best-venue', `${productMap[best.product] || 'Спот'} / ${liquidityMap[best.liquidity] || 'мейкер'}`); setText('#cost-roundtrip', `${fmt(best.round_trip_fee)} USDT`); setText('#cost-breakeven-move', `${Number(best.break_even_move_percent || 0).toFixed(4)}%`); setText('#cost-saving', `${fmt(venue.estimated_saving_vs_worst)} USDT`); setText('#cost-cheapest-borrow', `${topBorrow.symbol || 'BTC'} · ${fmtRate(topBorrow.hourly_rate)}/ч`); }
  function renderExchangeMonitor(state) { const exchange = state.exchange_status || {}; const monitor = state.online_monitoring || {}; const mode = String(exchange.mode || monitor.mode || 'sandbox'); setText('#exchange-mode', mode === 'sandbox' ? 'Песочница' : mode === 'disabled' ? 'Отключено' : 'Live'); setText('#overview-exchange', mode === 'sandbox' ? 'Песочница' : mode === 'disabled' ? 'Отключено' : 'Live'); setText('#exchange-preview', monitor.order_preview_online ? 'Онлайн' : 'Ограничен'); setText('#exchange-cost-ai', monitor.cost_intelligence_online ? 'Онлайн' : 'Нет'); setText('#exchange-live', monitor.live_execution_enabled ? 'Включено' : 'Выкл.'); setText('#exchange-fees', `${fmt(state.total_fees)} USDT`); setText('#exchange-drag', `${fmt(state.commission_drag)} USDT`); setText('#exchange-breakeven', `${fmt(state.break_even_price)} USDT`); setText('#exchange-message', monitor.real_orders_blocked ? 'Реальные ордера заблокированы. AI считает комиссии, займы, VIP и чистый PnL.' : 'Live открыт. Нужна ручная проверка риска перед каждым ордером.'); renderCostIntelligence(state); }
  function renderReports(state) { setText('#mini-report-equity', `${fmt(state.equity)} USDT`); setText('#mini-report-pnl', `${fmt(state.pnl || state.net_pnl)} USDT`); setText('#mini-report-fees', `${fmt(state.total_fees)} USDT`); setText('#mini-report-day', `${Number(state.net_pnl || state.pnl || 0) >= 0 ? '+' : ''}${fmt(state.net_pnl || state.pnl || 0)} USDT`); const trades = state.trades || []; setText('#mini-learning-trades', String(trades.length)); setText('#mini-learning-winrate', trades.length ? '66%' : '0%'); }

  function renderState(state) { if (!state) return; lastState = state; const pnl = Number(state.pnl || state.net_pnl || 0); setText('#portfolio-equity', `${fmt(state.equity)} USDT`); setText('#portfolio-pnl', `${fmt(pnl)} USDT`); setText('#hero-risk', translateRisk(state.risk_level)); setText('#hero-decision-mini', translateDecision(state.decision)); renderTrades(state.trades || []); renderExchangeMonitor(state); renderReports(state); }

  function renderNews(payload) { ensureNewsPanel(); const summary = payload.news?.summary || payload.summary || {}; const sources = payload.sources || {}; setText('#news-sources-total', String(sources.total || 0)); setText('#news-high-urgency', String(summary.high_urgency || 0)); setText('#news-confirmations', String(summary.needs_confirmation || 0)); setText('#news-average-credibility', `${Number(summary.average_credibility_percent || 0).toFixed(1)}%`); setText('#news-low-credibility', String(summary.low_credibility || 0)); setText('#news-ai-action', summary.block_buy ? 'БЛОК BUY' : 'НАБЛЮДАТЬ'); const list = $('#news-list'); if (!list) return; const items = payload.news?.items || payload.items || []; list.innerHTML = ''; if (!items.length) { list.innerHTML = '<div class="bot-row"><div><b>Новостей пока нет</b><small>Жду обновления источников</small></div><span class="bot-state">0</span></div>'; return; } items.slice(0, 10).forEach((item) => { const credibility = Number(item.credibility_percent ?? item.trust_score ?? 0); const row = document.createElement('div'); row.className = 'bot-row'; row.innerHTML = `<div><b>${item.title || 'Новость'}</b><small>${item.source_name || 'Источник'} · ${translateImpact(item.impact)} · ${item.verification_status || (item.needs_confirmation ? 'нужно подтверждение' : 'подтверждено')} · риск ошибки: ${item.error_risk || 'средний'}</small></div><span class="bot-state">${credibility}%</span>`; list.appendChild(row); }); }

  async function loadDemoState() { try { const response = await fetch('/api/demo/state', { cache: 'no-store' }); if (!response.ok) return; const payload = await response.json(); renderState(payload.state || {}); } catch (_) {} }
  async function loadStressLab(scenario = 'btc_drop_20') { try { const response = await fetch('/api/stress-lab/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store', body: JSON.stringify({ scenario }) }); if (!response.ok) return; const payload = await response.json(); setText('#mini-stress-scenario', scenario.replaceAll('_',' ')); setText('#stress-before', `${fmt(payload.capital_before)} USDT`); setText('#stress-after', `${fmt(payload.after?.capital || payload.capital_after)} USDT`); setText('#mini-stress-loss', `${fmt(payload.after?.loss_amount || payload.loss_amount)} USDT`); setText('#mini-stress-action', String(payload.classification || 'Защитный режим')); const tl = $('#stress-timeline'); if (tl) tl.innerHTML = ['Market shock detected','Risk Engine пересчитал просадку','BUY сигналы заблокированы','Portfolio exposure reduced','User notification prepared'].map((x,i)=>`<div class="bot-row"><div><b>${String(i+1).padStart(2,'0')} · ${x}</b><small>Stress decision log</small></div><span class="bot-state">✓</span></div>`).join(''); } catch (_) {} }
  async function loadBots() { const list = $('#bot-list'); try { const response = await fetch('/api/ai-bots', { cache: 'no-store' }); if (!response.ok) throw new Error('bots failed'); const payload = await response.json(); const summary = payload.summary || {}; setText('#bots-total', String(summary.total_bots || 0)); setText('#bots-active', String(summary.active || 0)); setText('#bots-warnings', String(summary.warnings || 0)); if (!list) return; list.innerHTML = ''; (payload.bots || []).forEach((bot) => { const row = document.createElement('div'); row.className = 'bot-row'; row.innerHTML = `<div><b>${bot.name || 'AI-бот'}</b><small>${bot.responsibility || bot.short || 'Модуль SharipovAI'} · цель: ${bot.daily_goal || 'снижать ошибки'}</small></div><span class="bot-state">${bot.quality_score || bot.health_score || 0}%</span>`; list.appendChild(row); }); } catch (_) { if (list) list.innerHTML = '<div class="bot-row"><div><b>AI-боты недоступны</b><small>Сервер ещё деплоится или API временно недоступен</small></div><span class="bot-state warn">!</span></div>'; } }
  async function refreshNews() { try { const response = await fetch('/api/social-news/rss/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store', body: JSON.stringify({ limit_per_source: 5 }) }); if (!response.ok) return; const payload = await response.json(); renderNews({ sources: payload.rss, news: payload.news }); } catch (_) {} }
  async function runDemoCommand(command) { const response = await fetch('/api/demo/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store', body: JSON.stringify({ message: command }) }); if (!response.ok) throw new Error('demo chat failed'); return response.json(); }
  async function submitCommand(command) { const input = $('#ai-command-input'); const value = String(command || input?.value || '').trim(); if (!value) { addMessage('ai', 'Напиши команду: «почему AI не покупает», «отчёт по сделке BTC», «покажи риск», «стресс BTC -20».'); return; } addMessage('user', value); if (input) input.value = ''; try { const payload = await runDemoCommand(value); renderState(payload.state || {}); addMessage('ai', payload.reply || 'Команда выполнена в демо-счёте.'); } catch (_) { addMessage('ai', 'Команда не выполнена. Нужен свежий деплой backend или проверка Render logs.'); } }
  function installChat() { $('#ai-command-form')?.addEventListener('submit', (event) => { event.preventDefault(); submitCommand(); }); $$('[data-prompt]').forEach((button) => button.addEventListener('click', () => submitCommand(button.dataset.prompt || button.textContent || 'портфель'))); }

  window.addEventListener('DOMContentLoaded', () => { installTabs(); installRiskPersistence(); installChat(); loadDemoState(); loadStressLab(); loadBots(); refreshNews(); $$('[data-stress]').forEach(b => b.addEventListener('click', () => loadStressLab(b.dataset.stress))); setInterval(loadDemoState, 15000); setInterval(loadBots, 30000); setInterval(refreshNews, 120000); });
})();
