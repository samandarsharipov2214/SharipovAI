(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const PAGES = new Set(['decision', 'portfolio', 'risk', 'control', 'learning', 'evidence', 'reports', 'trades', 'virtual', 'bybit', 'settings']);
  const state = { truth: null, events: [], evidence: [], learning: null, report: null, account: null, errors: {}, loadedAt: null, loading: false, tradeFilter: 'all' };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const finite = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
  const array = (...values) => values.find(Array.isArray) || [];
  const money = (value, digits = 4) => finite(value) === null ? '—' : Number(value).toLocaleString('ru-RU', { maximumFractionDigits: digits });
  const time = (value) => {
    if (!value) return '—';
    const number = Number(value);
    const normalized = Number.isFinite(number) && number > 0 && number < 1e12 ? number * 1000 : value;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('ru-RU');
  };
  const card = (label, value, note = '', tone = '') => `<article class="card"><span>${esc(label)}</span><strong class="${esc(tone)}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
  const row = (label, value, tone = '') => `<div class="v10-row"><span>${esc(label)}</span><b class="${esc(tone)}">${esc(value)}</b></div>`;
  const panel = (title, body, wide = '') => `<article class="panel ${wide}"><small>CANONICAL RUNTIME</small><h2>${esc(title)}</h2>${body}</article>`;
  const empty = (text) => `<div class="empty">${esc(text)}</div>`;

  const activePage = () => window.SharipovAIPageCoordinator?.activePage?.()
    || document.querySelector('#nav button.active[data-page]')?.dataset.page
    || 'overview';

  async function getJson(url) {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return response.json();
  }

  function paper() { return state.truth?.paper || {}; }
  function summary() { return paper().summary || {}; }
  function paperState() { return paper().state || {}; }
  function trades() { return array(paper().trades, paperState().trades); }
  function positions() {
    const raw = paperState().positions;
    if (Array.isArray(raw)) return raw;
    if (raw && typeof raw === 'object') return Object.entries(raw).map(([symbol, item]) => ({ symbol, ...(item || {}) }));
    return [];
  }
  function organs() { return array(state.truth?.organs?.organs); }
  function riskOrgan() { return organs().find((item) => String(item.organ_id || '').toLowerCase().includes('risk')) || null; }
  function sortedByTime(items) {
    return items.slice().sort((a, b) => Number(b.created_at_ms || b.timestamp_ms || b.time || 0) - Number(a.created_at_ms || a.timestamp_ms || a.time || 0));
  }
  function latestEvent() { return sortedByTime(state.events)[0] || null; }
  function latestTrade() { return sortedByTime(trades())[0] || null; }
  function decision() {
    const event = latestEvent();
    const trade = latestTrade();
    return {
      action: String(event?.action || trade?.general_controller_decision || trade?.decision_quality_action || 'NO_DECISION').toUpperCase(),
      reason: event?.reason || trade?.reason || 'Каноническое решение пока не сформировано.',
      decisionId: trade?.decision_id || event?.decision_id || null,
      confidence: trade?.decision_quality_confidence ?? null,
      agreement: trade?.decision_quality_agreement ?? null,
      mode: paperState().decision_mode || 'CANONICAL_COUNCIL_REQUIRED',
      event,
      trade,
    };
  }
  function accountData() {
    const raw = state.account || {};
    const data = raw.snapshot || raw.account || raw.result || raw;
    const assets = array(data.assets, data.coins, data.coin, raw.assets);
    const positions = array(data.positions, raw.positions);
    const orders = array(data.orders, raw.orders);
    const executions = array(data.trades, data.executions, raw.trades, raw.executions);
    const equity = data.total_equity ?? data.totalEquity ?? data.equity ?? data.total_wallet_balance ?? data.totalWalletBalance;
    const connected = Boolean(raw.connected === true || raw.verified === true || equity != null || assets.length || positions.length || orders.length);
    return { data, assets, positions, orders, executions, equity, connected };
  }
  function evidenceItems() { return array(state.evidence?.items, state.evidence?.records, state.evidence?.events, state.evidence); }
  function learningItems() { return array(state.learning?.insights, state.learning?.recommendations, state.learning?.lessons, state.learning?.items); }
  function reportHistory() { return array(state.report?.periods, state.report?.reports, state.report?.history); }

  function tradeNumbers(item) {
    const entry = finite(item.entry_price ?? item.price) ?? 0;
    const live = finite(item.exit_price ?? item.current_price ?? item.price) ?? entry;
    const quantity = finite(item.quantity ?? item.qty ?? item.size) ?? 0;
    const notional = finite(item.notional) ?? entry * quantity;
    const fee = finite(item.fee ?? item.total_fees) ?? 0;
    const net = finite(item.net_pnl) ?? 0;
    return { entry, live, quantity, notional, fee, net };
  }
  function tradeCard(item) {
    const values = tradeNumbers(item);
    const side = String(item.side || '—').toUpperCase();
    const status = String(item.status || (side === 'SELL' ? 'CLOSED' : 'OPEN')).toUpperCase();
    const tone = values.net >= 0 ? 'positive' : 'negative';
    return `<article class="trade-card" data-status="${esc(status.toLowerCase())}" data-side="${esc(side.toLowerCase())}">
      <div class="trade-card-head"><div><div class="trade-card-title"><h3>${esc(item.symbol || item.asset || '—')}</h3><span class="status-chip ${side === 'BUY' ? 'buy' : 'sell'}">${esc(side)}</span><span class="status-chip ${status === 'CLOSED' ? 'closed' : 'open'}">${esc(status)}</span></div><div class="trade-card-subtitle">${esc(time(item.created_at_ms || item.time))} · CouncilAuthorizedPaperLoop</div></div></div>
      <div class="trade-card-grid"><div class="trade-metric"><span>Размер позиции</span><b>${esc(money(values.notional, 2))} USDT</b></div><div class="trade-metric"><span>Количество</span><b>${esc(money(values.quantity, 8))}</b></div><div class="trade-metric"><span>Цена входа</span><b>${esc(money(values.entry, 4))}</b></div><div class="trade-metric"><span>${status === 'CLOSED' ? 'Цена выхода' : 'Текущая цена'}</span><b>${esc(money(values.live, 4))}</b></div></div>
      <div class="trade-breakdown"><div class="trade-metric"><span>Комиссии</span><b class="negative">${esc(money(values.fee, 4))} USDT</b></div><div class="trade-metric total"><span>Чистый результат</span><b class="${tone}">${esc(money(values.net, 4))} USDT</b></div></div>
      <div class="trade-explanation"><p>${esc(item.entry_reason_ru || item.reason || 'Причина хранится в каноническом журнале решения.')}</p></div><div class="trade-card-foot"><span>Decision: ${esc(item.decision_id || '—')}</span><span>Реальный ордер: нет</span></div>
    </article>`;
  }

  function renderDecision() {
    const d = decision();
    const risk = riskOrgan();
    const s = summary();
    const evidence = evidenceItems().slice(0, 12);
    const evidenceHtml = evidence.length ? evidence.map((item) => `<div class="v10-evidence"><b>${esc(item.event || item.action || item.title || item.type || 'Событие')}</b><p>${esc(item.result || item.outcome || item.status || item.description || '—')}</p><small>${esc(item.evidence_id || item.id || item.hash || 'без идентификатора')}</small></div>`).join('') : empty('Связанные доказательства пока не получены.');
    return `<div class="title"><h1>Решение ИИ</h1><p>Только CouncilAuthorizedPaperLoop, Decision Quality и канонический журнал событий</p></div><section class="metrics">${card('Каноническое решение', d.action, d.mode, d.action === 'BLOCK' ? 'negative' : '')}${card('Уверенность', d.confidence == null ? '—' : `${money(d.confidence, 2)}%`, 'из сохранённой оценки')}${card('Согласие', d.agreement == null ? '—' : `${money(d.agreement, 4)}`, 'Decision Quality')}${card('Risk organ', String(risk?.status || 'unavailable').toUpperCase(), 'AIOrganRuntimeMonitor')}${card('Открыто позиций', String(s.open_positions ?? positions().length), 'канонический paper')}${card('Net PnL', `${money(s.net_pnl)} USDT`, 'после комиссий', Number(s.net_pnl || 0) >= 0 ? 'positive' : 'negative')}</section><section class="v10-grid">${panel('Обоснование', `<p class="v10-explanation">${esc(d.reason)}</p>${row('Decision ID', d.decisionId || '—')}${row('Источник', '/api/system/runtime-truth + /api/autonomous-paper/events')}${row('Исполнение', 'только virtual, после council authorization', 'positive')}`, 'wide')}${panel('Последнее событие', d.event ? `${row('Действие', d.event.action || '—')}${row('Пара', d.event.symbol || '—')}${row('Причина', d.event.reason || '—')}${row('Время', time(d.event.created_at_ms || d.event.time))}` : empty('Канонические события пока отсутствуют.'))}${panel('Risk evidence', risk ? `${row('Статус', risk.status || '—')}${row('Evidence', String(array(risk.evidence).length))}${row('Blockers', String(array(risk.blockers).length))}` : empty('Risk organ недоступен.'))}${panel('Доказательства решения', evidenceHtml, 'wide')}</section>`;
  }

  function renderPortfolio() {
    const s = summary();
    const paperPositions = positions();
    const account = accountData();
    const rows = paperPositions.length ? `<table class="v10-table"><thead><tr><th>Инструмент</th><th>Количество</th><th>Вход</th><th>Текущая цена</th><th>Decision</th></tr></thead><tbody>${paperPositions.map((item) => `<tr><td>${esc(item.symbol || item.asset || '—')}</td><td>${esc(money(item.quantity ?? item.qty, 8))}</td><td>${esc(money(item.entry_price, 4))}</td><td>${esc(money(item.current_price ?? item.last_price, 4))}</td><td>${esc(item.decision_id || '—')}</td></tr>`).join('')}</tbody></table>` : empty('Открытых канонических позиций нет.');
    return `<div class="title"><h1>Портфель</h1><p>Канонический paper-портфель отделён от необязательного Bybit read-only</p></div><section class="metrics">${card('Equity', `${money(s.equity)} USDT`, 'CouncilAuthorizedPaperLoop')}${card('Cash', `${money(s.cash)} USDT`, 'свободный виртуальный капитал')}${card('Открытые позиции', String(s.open_positions ?? paperPositions.length), 'канонический state')}${card('Net PnL', `${money(s.net_pnl)} USDT`, 'realized + unrealized')}${card('Комиссии', `${money(s.total_fees)} USDT`, 'канонический журнал')}${card('Bybit read-only', account.connected ? 'ПОДКЛЮЧЁН' : 'НЕ НАСТРОЕН', 'не влияет на paper runtime')}</section><section class="v10-grid">${panel('Канонические позиции', rows, 'wide')}${panel('Источник истины', `${row('Paper', state.truth?.source_of_truth?.paper || '—')}${row('Database', state.truth?.source_of_truth?.database || '—')}${row('Real orders', state.truth?.safety?.real_orders_blocked ? 'BLOCKED' : 'UNSAFE', state.truth?.safety?.real_orders_blocked ? 'positive' : 'negative')}`)}${panel('Личный Bybit', account.connected ? `${row('Equity', account.equity == null ? '—' : `${money(account.equity)} USDT`)}${row('Позиции', String(account.positions.length))}${row('Ордера', String(account.orders.length))}` : empty('Read-only ключ не настроен; это не деградация paper runtime.'))}</section>`;
  }

  function renderRisk() {
    const risk = riskOrgan();
    const safety = state.truth?.safety || {};
    const blockers = array(risk?.blockers);
    const evidence = array(risk?.evidence);
    return `<div class="title"><h1>Центр рисков</h1><p>Единственный владелец политики — risk_engine.canonical_service</p></div><section class="metrics">${card('Risk service', state.truth?.source_of_truth?.risk || 'unavailable', 'единый владелец')}${card('Risk organ', String(risk?.status || 'unavailable').toUpperCase(), 'AIOrganRuntimeMonitor')}${card('Kill switch', safety.execution_kill_switch ? 'ACTIVE' : 'UNSAFE', 'должен быть включён', safety.execution_kill_switch ? 'positive' : 'negative')}${card('Testnet', safety.testnet_execution_enabled ? 'ENABLED' : 'DISABLED', 'исполнение должно быть выключено', safety.testnet_execution_enabled ? 'negative' : 'positive')}${card('Live', safety.live_execution_enabled ? 'ENABLED' : 'DISABLED', 'Mainnet должен быть выключен', safety.live_execution_enabled ? 'negative' : 'positive')}${card('Real orders', safety.real_orders_blocked ? 'BLOCKED' : 'UNSAFE', 'fail-closed', safety.real_orders_blocked ? 'positive' : 'negative')}</section><section class="v10-grid">${panel('Blockers', blockers.length ? `<ul>${blockers.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>` : empty('Активных blockers нет.'))}${panel('Evidence', evidence.length ? `<ul>${evidence.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>` : empty('Evidence не передана.'))}${panel('Политика', `${row('Live execution', 'ВСЕГДА ЗАПРЕЩЕНО', 'positive')}${row('Paper entry', 'только после council authorization')}${row('Источник рынка', 'verified market stream')}${row('Синтетические котировки', 'запрещены', 'positive')}`, 'wide')}</section>`;
  }

  function renderControl() {
    const d = decision();
    const list = organs();
    const counts = state.truth?.organs?.counts || {};
    const records = evidenceItems().slice(0, 50);
    return `<div class="title"><h1>Главное управление</h1><p>Проверяемая цепочка: органы → Decision Quality → CouncilAuthorizedPaperLoop</p></div><section class="metrics">${card('Runtime', String(state.truth?.status || 'unavailable').toUpperCase(), 'canonical_runtime_v1')}${card('Решение', d.action, d.mode)}${card('Органы', String(state.truth?.organs?.organ_count ?? list.length), `healthy ${counts.healthy || 0} · degraded ${counts.degraded || 0} · blocked ${counts.blocked || 0}`)}${card('Decision ID', d.decisionId || '—', 'канонический журнал')}${card('Real orders', state.truth?.safety?.real_orders_blocked ? 'BLOCKED' : 'UNSAFE', 'защитный контур')}</section><section class="gc15-grid">${panel('Обоснование', `<p class="gc15-reason">${esc(d.reason)}</p>`, 'wide')}${panel('Органы ИИ', list.length ? list.map((item) => `<div class="gc15-vote"><b>${esc(item.organ_id || 'unknown')}</b><span>${esc(String(item.status || 'blocked').toUpperCase())}</span><p>${esc(item.responsibility || '')}</p></div>`).join('') : empty('Реестр органов недоступен.'))}${panel('Blockers', list.flatMap((item) => array(item.blockers).map((blocker) => `${item.organ_id}: ${blocker}`)).length ? `<ul>${list.flatMap((item) => array(item.blockers).map((blocker) => `<li>${esc(item.organ_id)}: ${esc(blocker)}</li>`)).join('')}</ul>` : empty('Подтверждённых blockers нет.'))}${panel('Цепочка доказательств', records.length ? records.map((item) => `<div class="gc15-record"><b>${esc(item.event || item.action || item.title || item.type || 'Событие')}</b><span>${esc(item.source || item.agent || item.module || 'источник не указан')}</span><p>${esc(item.result || item.reason || item.description || item.status || '')}</p><code>${esc(item.evidence_id || item.id || item.hash || '')}</code></div>`).join('') : empty('Хранилище доказательств не вернуло записи.'), 'wide')}</section>`;
  }

  function renderLearning() {
    const closed = trades().filter((item) => String(item.status || (String(item.side).toUpperCase() === 'SELL' ? 'CLOSED' : '')).toUpperCase() === 'CLOSED');
    const wins = closed.filter((item) => Number(item.net_pnl) > 0);
    const lessons = learningItems();
    const lessonHtml = lessons.length ? lessons.map((item) => `<article class="v17-lesson"><header><span class="v17-badge neutral">${esc(item.status || item.priority || 'наблюдение')}</span></header><h3>${esc(item.title || item.lesson || item.pattern || 'Вывод обучения')}</h3><p>${esc(item.description || item.recommendation || item.reason || item.details || 'Описание не передано.')}</p></article>`).join('') : empty('Подтверждённые выводы Learning OS пока не получены.');
    const tradeHtml = closed.length ? `<div class="trade-list">${closed.map(tradeCard).join('')}</div>` : empty('Закрытых канонических paper-сделок пока нет.');
    return `<div class="title"><h1>Центр обучения</h1><p>Только проверенные результаты CouncilAuthorizedPaperLoop; автоматический допуск к live запрещён</p></div><section class="metrics">${card('Закрыто', String(closed.length), 'материал для анализа')}${card('Прибыльных', String(wins.length), 'Net PnL выше нуля')}${card('Win rate', closed.length ? `${money(wins.length / closed.length * 100, 2)}%` : '—', 'по закрытым сделкам')}${card('Net PnL', `${money(summary().net_pnl)} USDT`, 'после комиссий')}${card('Уроков', String(lessons.length), 'Learning OS')}</section><section class="v17-lesson-grid">${lessonHtml}</section>${panel('Закрытые paper-сделки', tradeHtml, 'wide')}`;
  }

  function renderEvidence() {
    const items = evidenceItems();
    const events = state.events;
    const rows = items.length ? `<table class="v17-table"><thead><tr><th>Время</th><th>Событие</th><th>Источник</th><th>ID</th><th>Результат</th></tr></thead><tbody>${items.slice(0, 250).map((item) => `<tr><td>${esc(time(item.time || item.created_at || item.timestamp))}</td><td>${esc(item.event || item.action || item.title || item.type || '—')}</td><td>${esc(item.source || item.agent || item.module || '—')}</td><td>${esc(item.evidence_id || item.id || item.hash || '—')}</td><td>${esc(item.result || item.outcome || item.status || '—')}</td></tr>`).join('')}</tbody></table>` : empty('Evidence Vault не вернул записи.');
    return `<div class="title"><h1>Хранилище доказательств</h1><p>Evidence Vault и неизменяемый журнал канонического paper runtime</p></div><section class="metrics">${card('Evidence records', String(items.length), 'последний пакет')}${card('Paper events', String(events.length), '/api/autonomous-paper/events')}${card('Decision ID', decision().decisionId || '—', 'последняя связанная цепочка')}${card('Runtime', String(state.truth?.status || 'unavailable').toUpperCase(), 'canonical truth')}</section>${panel('Журнал доказательств', rows, 'wide')}`;
  }

  function renderReports() {
    const report = state.report || {};
    const history = reportHistory();
    const d = decision();
    const counts = state.truth?.organs?.counts || {};
    const body = history.length ? history.map((item) => `<article class="v17-report"><header><b>${esc(item.period || item.title || 'Период')}</b><small>${esc(time(item.generated_at || item.created_at || item.timestamp))}</small></header><p>${esc(item.summary || item.result || item.report || item.status || 'Сводка не передана.')}</p><div>${row('Сделки', item.total_trades ?? item.trades ?? '—')}${row('PnL', item.pnl == null ? '—' : `${money(item.pnl)} USDT`)}${row('Просадка', item.drawdown_percent == null ? '—' : `${money(item.drawdown_percent, 2)}%`)}</div></article>`).join('') : empty('Исторические отчёты пока отсутствуют.');
    return `<div class="title"><h1>Отчёты</h1><p>Сводка строится на canonical runtime, а не на legacy offline runner</p></div><section class="metrics">${card('Последнее решение', d.action, d.mode)}${card('Paper trades', String(summary().trade_count ?? trades().length), 'ProjectDatabase')}${card('Net PnL', `${money(summary().net_pnl)} USDT`, 'после комиссий')}${card('Органы healthy', String(counts.healthy || 0), 'AIOrganRuntimeMonitor')}${card('Органы blocked', String(counts.blocked || 0), 'критические блокеры')}</section><section class="v17-grid">${panel('Текущая сводка', `<p class="v17-summary">${esc(report.report || report.reason || d.reason)}</p>${row('Статус цели', report.goal_status || '—')}${row('Следующее действие', report.next_action || '—')}${row('Сформировано', time(report.generated_at || report.updated_at))}`, 'wide')}${panel('История', body, 'wide')}</section>`;
  }

  function filteredTrades() {
    const items = trades();
    if (state.tradeFilter === 'open') return items.filter((item) => String(item.status || '').toUpperCase() !== 'CLOSED');
    if (state.tradeFilter === 'closed') return items.filter((item) => String(item.status || '').toUpperCase() === 'CLOSED' || String(item.side || '').toUpperCase() === 'SELL');
    if (state.tradeFilter === 'buy') return items.filter((item) => String(item.side || '').toUpperCase() === 'BUY');
    if (state.tradeFilter === 'sell') return items.filter((item) => String(item.side || '').toUpperCase() === 'SELL');
    return items;
  }
  function tradeFilters() {
    return `<div class="section-actions">${[['all', 'Все'], ['open', 'Открытые'], ['closed', 'Закрытые'], ['buy', 'BUY'], ['sell', 'SELL']].map(([value, label]) => `<button class="action ${state.tradeFilter === value ? 'primary' : ''}" data-canonical-trade-filter="${value}" type="button">${label}</button>`).join('')}</div>`;
  }
  function renderTrades() {
    const items = filteredTrades();
    const s = summary();
    const real = accountData();
    const cards = items.length ? `<div class="trade-list">${sortedByTime(items).map(tradeCard).join('')}</div>` : empty('По выбранному фильтру операций нет.');
    return `<div class="title"><h1>Сделки</h1><p>Только журнал CouncilAuthorizedPaperLoop; реальные исполнения показываются отдельно и read-only</p></div><section class="metrics">${card('Всего', String(s.trade_count ?? trades().length), 'канонических операций')}${card('Открыто', String(s.open_positions ?? positions().length), 'paper-позиции')}${card('Net PnL', `${money(s.net_pnl)} USDT`, 'после комиссий')}${card('Комиссии', `${money(s.total_fees)} USDT`, 'учтены в результате')}${card('Real orders', state.truth?.safety?.real_orders_blocked ? 'BLOCKED' : 'UNSAFE', 'защитный контур')}</section><article class="panel wide"><div class="section-head"><div><small>CANONICAL PAPER</small><h2>Виртуальные операции</h2><p>OPEN показывает текущую цену; цена выхода появляется после закрытия.</p></div>${tradeFilters()}</div>${cards}</article>${panel('Bybit read-only executions', real.connected && real.executions.length ? `<table class="v10-table"><tbody>${real.executions.slice(0, 100).map((item) => `<tr><td>${esc(time(item.execTime || item.time))}</td><td>${esc(item.symbol || '—')}</td><td>${esc(item.side || '—')}</td><td>${esc(item.orderStatus || item.status || '—')}</td></tr>`).join('')}</tbody></table>` : empty('Реальные исполнения отсутствуют или read-only API не настроен.'), 'wide')}`;
  }

  function renderVirtual() {
    const s = summary();
    const cards = trades().length ? `<div class="trade-list">${sortedByTime(trades()).slice(0, 100).map(tradeCard).join('')}</div>` : empty('Канонических операций пока нет.');
    return `<div class="title"><h1>Канонический виртуальный счёт</h1><p>Единственный владелец — CouncilAuthorizedPaperLoop; старый Virtual Account отключён</p></div><section class="metrics">${card('Cash', `${money(s.cash)} USDT`, 'после комиссий')}${card('Equity', `${money(s.equity)} USDT`, 'cash + позиции')}${card('Net PnL', `${money(s.net_pnl)} USDT`, 'realized + unrealized')}${card('Комиссии', `${money(s.total_fees)} USDT`, 'канонический журнал')}${card('Открыто', String(s.open_positions ?? positions().length), 'текущие позиции')}${card('Worker', s.worker_running ? 'RUNNING' : 'STOPPED', 'CouncilAuthorizedPaperLoop')}</section>${panel('Операции', cards, 'wide')}`;
  }

  function renderBybit() {
    const account = accountData();
    if (!account.connected) return `<div class="title"><h1>Bybit</h1><p>Необязательный личный API только для чтения</p></div>${panel('Read-only API не настроен', empty('Это не влияет на canonical paper runtime. Для подключения нужен ключ без прав торговли и вывода.'), 'wide')}`;
    const data = account.data;
    const available = data.total_available_balance ?? data.totalAvailableBalance ?? data.available_balance;
    const assets = account.assets.length ? `<table class="v10-table"><thead><tr><th>Актив</th><th>Баланс</th><th>Доступно</th></tr></thead><tbody>${account.assets.map((item) => `<tr><td>${esc(item.coin || item.asset || item.symbol || '—')}</td><td>${esc(money(item.walletBalance ?? item.balance))}</td><td>${esc(money(item.availableBalance ?? item.available))}</td></tr>`).join('')}</tbody></table>` : empty('Состав активов не передан.');
    return `<div class="title"><h1>Bybit</h1><p>Фактические данные личного кабинета, отделённые от paper runtime</p></div><section class="metrics">${card('Подключение', 'READ-ONLY', 'торговые права не требуются')}${card('Капитал', account.equity == null ? '—' : `${money(account.equity)} USDT`, 'личный API')}${card('Доступно', available == null ? '—' : `${money(available)} USDT`, 'личный API')}${card('Позиции', String(account.positions.length), 'реальный аккаунт')}${card('Ордера', String(account.orders.length), 'read-only')}</section>${panel('Активы', assets, 'wide')}`;
  }

  function renderSettings() {
    const safety = state.truth?.safety || {};
    return `<div class="title"><h1>Настройки безопасности</h1><p>Информационный экран: торговые флаги здесь не изменяются</p></div><section class="metrics">${card('Kill switch', safety.execution_kill_switch ? '1 · ACTIVE' : '0 · UNSAFE', 'EXECUTION_KILL_SWITCH')}${card('Live trading', safety.live_execution_enabled ? 'ENABLED' : 'DISABLED', 'EXCHANGE_LIVE_TRADING_ENABLED')}${card('Testnet', safety.testnet_execution_enabled ? 'ENABLED' : 'DISABLED', 'TESTNET_EXECUTION_ENABLED')}${card('Memory', 'FEATURE-FLAGGED', 'не влияет на исполнение')}</section>${panel('Политика', `${row('Секреты', 'не отображаются')}${row('Docker socket', 'не используется')}${row('Old Virtual Account autorun', 'запрещён', 'positive')}${row('Mainnet/Testnet enablement', 'только отдельным ручным решением', 'positive')}`, 'wide')}`;
  }

  const renderers = { decision: renderDecision, portfolio: renderPortfolio, risk: renderRisk, control: renderControl, learning: renderLearning, evidence: renderEvidence, reports: renderReports, trades: renderTrades, virtual: renderVirtual, bybit: renderBybit, settings: renderSettings };

  function render(page = activePage()) {
    if (!PAGES.has(page)) return;
    const content = $('content');
    if (!content) return;
    const renderer = renderers[page];
    content.innerHTML = renderer ? renderer() : empty('Страница недоступна.');
    bind(page);
  }

  function bind(page) {
    document.querySelectorAll('[data-canonical-trade-filter]').forEach((button) => button.addEventListener('click', () => {
      state.tradeFilter = button.dataset.canonicalTradeFilter || 'all';
      if (page === 'trades') render('trades');
    }));
  }

  async function load(page = activePage()) {
    if (!PAGES.has(page) || state.loading) return;
    state.loading = true;
    const specs = [
      ['truth', '/api/system/runtime-truth'],
      ['events', '/api/autonomous-paper/events?limit=500'],
      ['evidence', '/api/evidence-vault/recent'],
      ['learning', '/api/learning-os/status'],
      ['report', '/api/ai-control-center/daily-report'],
      ['account', '/api/exchange/account/snapshot'],
    ];
    const settled = await Promise.allSettled(specs.map(([, url]) => getJson(url)));
    state.errors = {};
    settled.forEach((result, index) => {
      const key = specs[index][0];
      if (result.status === 'fulfilled') {
        if (key === 'events') state.events = array(result.value?.events);
        else state[key] = result.value;
      } else {
        state.errors[key] = result.reason?.message || 'unavailable';
        if (key === 'events') state.events = [];
      }
    });
    state.loadedAt = new Date().toISOString();
    state.loading = false;
    render(page);
  }

  function install() {
    document.addEventListener('click', (event) => {
      const button = event.target.closest('#nav button[data-page]');
      if (!button || !PAGES.has(button.dataset.page)) return;
      setTimeout(() => load(button.dataset.page).catch(() => render(button.dataset.page)), 0);
    });
    $('refresh')?.addEventListener('click', () => {
      const page = activePage();
      if (PAGES.has(page)) setTimeout(() => load(page).catch(() => render(page)), 0);
    });
    const page = activePage();
    if (PAGES.has(page)) load(page).catch(() => render(page));
  }

  window.SharipovAICanonicalPages = Object.freeze({ load, render, pages: [...PAGES] });
  window.addEventListener('DOMContentLoaded', install, { once: true });
})();
