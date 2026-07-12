(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const num = (value, digits = 2) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toLocaleString('ru-RU', { maximumFractionDigits: digits }) : '—';
  };
  const dateText = (value) => {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? esc(value) : date.toLocaleString('ru-RU');
  };
  const asArray = (value) => Array.isArray(value) ? value : [];
  const firstArray = (...values) => values.find(Array.isArray) || [];

  const state = {
    health: null,
    run: null,
    account: null,
    bots: null,
    news: null,
    learning: null,
    evidence: null,
    virtual: null,
    report: null,
    loadedAt: null,
    errors: {}
  };

  const endpoints = {
    health: '/api/health',
    run: '/api/run',
    account: '/api/exchange/account/snapshot',
    bots: '/api/ai-bots',
    news: '/api/social-news',
    learning: '/api/learning-os/status',
    evidence: '/api/evidence-vault/recent',
    virtual: '/api/virtual-account/state',
    report: '/api/ai-control-center/daily-report'
  };

  const title = (heading, description) => `<div class="title"><h1>${esc(heading)}</h1><p>${esc(description)}</p></div>`;
  const card = (label, value, note = '', cls = '') => `<article class="card"><span>${esc(label)}</span><strong class="${esc(cls)}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
  const panel = (heading, body, cls = '') => `<article class="panel ${esc(cls)}"><small>SHARIPOVAI</small><h2>${esc(heading)}</h2>${body}</article>`;
  const empty = (text) => `<div class="empty">${esc(text)}</div>`;
  const badge = (text, tone = 'neutral') => `<span class="v10-badge ${esc(tone)}">${esc(text)}</span>`;
  const row = (label, value, tone = '') => `<div class="v10-row"><span>${esc(label)}</span><b class="${esc(tone)}">${esc(value)}</b></div>`;
  const sourceStamp = (source, time) => `<div class="v10-source">Источник: <b>${esc(source || 'не указан')}</b> · Получено: ${dateText(time)}</div>`;

  function accountData() {
    const raw = state.account || {};
    const data = raw.snapshot || raw.account || raw.result || raw;
    return {
      equity: data.total_equity ?? data.totalEquity ?? data.equity,
      available: data.total_available_balance ?? data.totalAvailableBalance ?? data.available_balance,
      walletBalance: data.total_wallet_balance ?? data.totalWalletBalance ?? data.wallet_balance,
      positions: firstArray(data.positions, raw.positions),
      orders: firstArray(data.orders, raw.orders),
      trades: firstArray(data.trades, data.executions, raw.trades, raw.executions),
      assets: firstArray(data.assets, data.coins, data.coin, raw.assets),
      connected: Boolean(state.account && !state.errors.account)
    };
  }

  function botList() {
    return firstArray(state.bots?.bots, state.bots?.items, state.bots?.agents, state.bots);
  }

  function newsItems() {
    return firstArray(state.news?.news?.items, state.news?.news, state.news?.items, state.news?.articles, state.news);
  }

  function evidenceItems() {
    return firstArray(state.evidence?.items, state.evidence?.records, state.evidence?.events, state.evidence);
  }

  function learningItems() {
    return firstArray(state.learning?.insights, state.learning?.recommendations, state.learning?.lessons, state.learning?.items);
  }

  function reportData() {
    return state.report || state.run || {};
  }

  function freshness(item) {
    const raw = item?.last_seen || item?.updated_at || item?.timestamp || item?.generated_at;
    if (!raw) return { fresh: false, age: null, label: 'нет отметки времени' };
    const age = Math.max(0, (Date.now() - new Date(raw).getTime()) / 1000);
    return { fresh: age < 90, age, label: age < 60 ? `${Math.round(age)} сек. назад` : `${Math.round(age / 60)} мин. назад` };
  }

  function verifiedBot(bot) {
    if (!bot) return false;
    if (Number.isFinite(Number(bot.heartbeat_age_seconds))) return Number(bot.heartbeat_age_seconds) < 90;
    return freshness(bot).fresh;
  }

  function overviewPage() {
    const account = accountData();
    const bots = botList();
    const verified = bots.filter(verifiedBot).length;
    const news = newsItems();
    const evidence = evidenceItems();
    const run = state.run || {};
    const warnings = Object.keys(state.errors).length;
    return title('Центр управления', 'Фактическая сводка SharipovAI по всем рабочим контурам') +
      `<section class="metrics">
        ${card('Капитал', account.equity != null ? `${num(account.equity, 8)} USDT` : '—', account.connected ? 'Bybit отвечает' : 'Нет подтверждения биржи')}
        ${card('Открытые позиции', String(account.positions.length), 'Фактические позиции')}
        ${card('ИИ подтверждены', `${verified}/${bots.length}`, 'Свежий сигнал до 90 секунд', verified ? 'positive' : '')}
        ${card('Решение ИИ', run.decision || '—', run.reason || 'Нет подтверждённого объяснения')}
        ${card('Предупреждения', String(warnings), warnings ? 'Есть недоступные источники' : 'Источники доступны', warnings ? 'negative' : 'positive')}
      </section>
      <section class="v10-grid">
        ${panel('Последнее решение', `<div class="v10-decision">${esc(run.decision || 'НЕТ РЕШЕНИЯ')}</div>${row('Уверенность', run.confidence != null ? `${num(run.confidence)}%` : '—')}${row('Риск', run.risk_level || '—')}${sourceStamp('API решения', run.generated_at || run.updated_at)}`, 'wide')}
        ${panel('Важные новости', news.length ? news.slice(0, 4).map(newsCompact).join('') : empty('Подтверждённые новости пока не получены.'))}
        ${panel('Последние доказательства', evidence.length ? evidence.slice(0, 5).map(evidenceCompact).join('') : empty('Хранилище доказательств не вернуло записи.'))}
      </section>`;
  }

  function decisionPage() {
    const run = state.run || {};
    const bots = botList();
    const voters = firstArray(run.votes, run.agent_votes, run.consensus_details, run.participants);
    const evidence = evidenceItems().filter((item) => String(item.type || item.event || '').toLowerCase().includes('decision')).slice(0, 10);
    const voterHtml = voters.length ? voters.map((vote) => `<div class="v10-vote"><b>${esc(vote.name || vote.agent || vote.module || 'ИИ-модуль')}</b>${badge(vote.decision || vote.vote || vote.signal || '—', String(vote.decision || '').toLowerCase().includes('sell') ? 'bad' : 'good')}<p>${esc(vote.reason || vote.explanation || 'Причина не передана')}</p></div>`).join('') : empty('API не передал отдельные голоса ИИ. Финальное решение показано без выдуманных участников.');
    return title('Решение ИИ', 'Причины, участники, риски и доказательства решения') +
      `<section class="metrics">
        ${card('Решение', run.decision || '—', 'Финальный результат')}
        ${card('Уверенность', run.confidence != null ? `${num(run.confidence)}%` : '—', 'Только измеренное значение')}
        ${card('Риск', run.risk_level || '—', 'Оценка центра рисков')}
        ${card('Согласие', run.consensus_agreement != null ? `${num(run.consensus_agreement)}%` : run.consensus || '—', 'Согласование модулей')}
      </section>
      <section class="v10-grid">
        ${panel('Обоснование', `<p class="v10-explanation">${esc(run.reason || run.report || 'Подтверждённое объяснение пока не получено.')}</p>${sourceStamp('API решения', run.generated_at || run.updated_at)}`, 'wide')}
        ${panel('Голоса ИИ', voterHtml, 'wide')}
        ${panel('Доказательства решения', evidence.length ? evidence.map(evidenceCompact).join('') : empty('Связанные доказательства пока не найдены.'))}
      </section>`;
  }

  function portfolioPage() {
    const account = accountData();
    const total = Number(account.equity) || 0;
    const assets = account.assets.length ? account.assets : account.positions;
    const allocation = assets.length ? assets.map((asset) => {
      const value = Number(asset.usdValue ?? asset.usd_value ?? asset.positionValue ?? asset.value ?? asset.walletBalance ?? 0);
      const share = total > 0 ? (value / total) * 100 : null;
      return `<div class="v10-allocation"><div><b>${esc(asset.coin || asset.symbol || asset.asset || 'Актив')}</b><span>${share != null ? `${num(share)}%` : '—'}</span></div><progress max="100" value="${share != null ? Math.max(0, Math.min(100, share)) : 0}"></progress><small>${value ? `${num(value, 8)} USDT` : 'Стоимость не передана'}</small></div>`;
    }).join('') : empty('Биржа не вернула состав активов.');
    const positions = account.positions.length ? `<table class="v10-table"><thead><tr><th>Инструмент</th><th>Сторона</th><th>Размер</th><th>Цена входа</th><th>Текущий PnL</th></tr></thead><tbody>${account.positions.map((position) => `<tr><td>${esc(position.symbol || '—')}</td><td>${esc(position.side || '—')}</td><td>${esc(position.size ?? position.qty ?? '—')}</td><td>${esc(position.avgPrice ?? position.entry_price ?? position.entryPrice ?? '—')}</td><td>${esc(position.unrealisedPnl ?? position.unrealized_pnl ?? '—')}</td></tr>`).join('')}</tbody></table>` : empty('Открытых позиций нет или API их не вернул.');
    return title('Портфель', 'Капитал, распределение, позиции и фактический риск') +
      `<section class="metrics">${card('Капитал', total ? `${num(total, 8)} USDT` : '—', 'Общая стоимость')}${card('Доступно', account.available != null ? `${num(account.available, 8)} USDT` : '—', 'Свободные средства')}${card('Баланс кошелька', account.walletBalance != null ? `${num(account.walletBalance, 8)} USDT` : '—', 'До нереализованного PnL')}${card('Позиций', String(account.positions.length), 'Открыто сейчас')}</section>
      <section class="v10-grid">${panel('Распределение капитала', allocation)}${panel('Открытые позиции', positions, 'wide')}${panel('Контроль портфеля', `${row('Источник', account.connected ? 'Bybit' : 'нет подтверждения', account.connected ? 'positive' : 'negative')}${row('Время загрузки', dateText(state.loadedAt))}${row('Синтетические данные', 'запрещены', 'positive')}`)}</section>`;
  }

  function tradesPage() {
    const account = accountData();
    const trades = account.trades.length ? account.trades : account.orders;
    const body = trades.length ? `<table class="v10-table"><thead><tr><th>Время</th><th>Инструмент</th><th>Сторона</th><th>Цена</th><th>Количество</th><th>Статус / результат</th></tr></thead><tbody>${trades.slice(0, 100).map((trade) => `<tr><td>${dateText(trade.createdTime || trade.time || trade.created_at || trade.updatedTime)}</td><td>${esc(trade.symbol || '—')}</td><td>${esc(trade.side || '—')}</td><td>${esc(trade.execPrice ?? trade.price ?? '—')}</td><td>${esc(trade.execQty ?? trade.qty ?? trade.size ?? '—')}</td><td>${esc(trade.status ?? trade.closedPnl ?? trade.pnl ?? '—')}</td></tr>`).join('')}</tbody></table>` : empty('Подтверждённые сделки и ордера пока не получены.');
    return title('Сделки', 'Реальный журнал исполнения без демонстрационных операций') + panel('История исполнения', body, 'wide');
  }

  function botsPage() {
    const bots = botList();
    const cards = bots.length ? bots.map((bot) => {
      const ok = verifiedBot(bot);
      const stamp = freshness(bot);
      const evidence = bot.evidence_id || bot.last_evidence_id || null;
      return `<article class="v10-agent"><header><div><small>${esc(bot.kind || bot.role || 'ИИ-модуль')}</small><h3>${esc(bot.name || 'Без названия')}</h3></div>${badge(ok ? 'подтверждён' : 'не подтверждён', ok ? 'good' : 'bad')}</header><div class="v10-agent-stats">${row('Последний сигнал', Number.isFinite(Number(bot.heartbeat_age_seconds)) ? `${num(bot.heartbeat_age_seconds, 0)} сек.` : stamp.label, ok ? 'positive' : 'negative')}${row('Качество', bot.metrics_verified && bot.quality_score != null ? `${num(bot.quality_score)}%` : 'нет измерений')}${row('Ошибка', bot.error || bot.last_error || 'не передана')}${row('Подчиняется', bot.reports_to || 'не указано')}</div><p>${esc(evidence && bot.last_action ? bot.last_action : 'Подтверждённой записи о последнем действии нет.')}</p><footer>${evidence ? `Доказательство: ${esc(evidence)}` : 'Доказательство отсутствует'}</footer></article>`;
    }).join('') : empty('Реестр ИИ не получен.');
    return title('Центр ИИ', 'Все ИИ, их фактическое состояние, работа и доказательства') + `<section class="v10-agent-grid">${cards}</section>`;
  }

  function newsCompact(item) {
    const titleText = item.title || item.headline || 'Без заголовка';
    const source = item.source_name || item.source || item.publisher || 'Источник не указан';
    const impact = String(item.impact || item.sentiment || 'нейтрально').toLowerCase();
    const tone = impact.includes('bear') || impact.includes('neg') || impact.includes('нег') ? 'bad' : impact.includes('bull') || impact.includes('pos') || impact.includes('позит') ? 'good' : 'neutral';
    return `<div class="v10-compact"><div><b>${esc(titleText)}</b><small>${esc(source)} · ${dateText(item.published_at || item.pubDate || item.checked_at || item.created_at)}</small></div>${badge(item.impact || item.sentiment || 'не оценено', tone)}</div>`;
  }

  function newsPage() {
    const items = newsItems();
    const summary = state.news?.news?.summary || state.news?.summary || {};
    const cards = items.length ? items.map((item) => {
      const image = item.image_url || item.image || item.thumbnail || item.og_image;
      const source = item.source_name || item.source || item.publisher || 'Источник не указан';
      const url = item.url || item.link || item.source_url;
      const impact = item.impact || item.sentiment || 'не оценено';
      const credibility = item.credibility_percent ?? item.credibility ?? item.source_score;
      const assets = firstArray(item.assets, item.symbols, item.related_assets);
      return `<article class="v10-news-card">${image ? `<img src="${esc(image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : '<div class="v10-no-image">Изображение источником не предоставлено</div>'}<div class="v10-news-body"><div class="v10-news-meta">${badge(item.category || 'новость')}${badge(impact, String(impact).toLowerCase().includes('neg') ? 'bad' : String(impact).toLowerCase().includes('pos') ? 'good' : 'neutral')}</div><h3>${esc(item.title || item.headline || 'Без заголовка')}</h3><p>${esc(item.summary || item.description || item.excerpt || 'Краткое описание не передано источником.')}</p><div class="v10-news-details">${row('Источник', source)}${row('Опубликовано', dateText(item.published_at || item.pubDate || item.checked_at))}${row('Доверие', credibility != null ? `${num(credibility)}%` : 'не измерено')}${row('Связанные активы', assets.length ? assets.join(', ') : 'не указаны')}</div>${item.analysis || item.ai_analysis || item.reason ? `<div class="v10-ai-note"><b>Анализ ИИ</b><p>${esc(item.analysis || item.ai_analysis || item.reason)}</p></div>` : ''}${url ? `<a class="action v10-open" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Открыть источник</a>` : '<span class="v10-missing-link">Ссылка источника отсутствует</span>'}</div></article>`;
    }).join('') : empty('Подтверждённые новости не получены. Заголовки и изображения не подставляются искусственно.');
    return title('Новости', 'Заголовки, изображения источников, влияние и проверка новостным ИИ') +
      `<section class="metrics">${card('Получено', String(items.length), 'Новости текущего пакета')}${card('Требуют подтверждения', String(summary.needs_confirmation ?? '—'), 'Нужен второй источник')}${card('Среднее доверие', summary.average_credibility_percent != null ? `${num(summary.average_credibility_percent)}%` : '—', 'Только измеренное значение')}${card('Блокировка покупки', summary.block_buy === true ? 'ДА' : summary.block_buy === false ? 'НЕТ' : '—', 'Решение новостного контура')}</section><section class="v10-news-grid">${cards}</section>`;
  }

  function riskPage() {
    const run = state.run || {};
    const account = accountData();
    const virtual = state.virtual || {};
    const limits = run.risk_limits || run.limits || state.report?.risk_limits || {};
    const warnings = firstArray(run.risk_warnings, run.warnings, state.report?.warnings);
    return title('Центр рисков', 'Лимиты, просадка, блокировки и право вето') +
      `<section class="metrics">${card('Текущий риск', run.risk_level || '—', 'Оценка системы')}${card('Открытые позиции', String(account.positions.length), 'Фактические')}${card('Просадка', virtual.drawdown_percent != null ? `${num(virtual.drawdown_percent)}%` : run.drawdown_percent != null ? `${num(run.drawdown_percent)}%` : '—', 'Из подтверждённых данных')}${card('Режим торговли', run.run_mode || run.mode || virtual.mode || '—', 'Текущий режим')}</section>
      <section class="v10-grid">${panel('Защитные ограничения', `${row('Вывод средств', 'запрещён', 'positive')}${row('Ордера без проверки', 'запрещены', 'positive')}${row('Максимальный риск сделки', limits.max_trade_risk_percent != null ? `${num(limits.max_trade_risk_percent)}%` : 'не передан')}${row('Максимальная просадка', limits.max_drawdown_percent != null ? `${num(limits.max_drawdown_percent)}%` : 'не передана')}${row('Право вето центра рисков', 'активно', 'positive')}`)}${panel('Предупреждения', warnings.length ? warnings.map((warning) => `<div class="v10-warning">${esc(warning.message || warning.title || warning)}</div>`).join('') : empty('Активные подтверждённые предупреждения не получены.'), 'wide')}</section>`;
  }

  function bybitPage() {
    const account = accountData();
    return title('Bybit', 'Состояние подключения, капитал, позиции и безопасность ключа') +
      `<section class="metrics">${card('Подключение', account.connected ? 'ПОДКЛЮЧЕНО' : 'НЕ ПОДТВЕРЖДЕНО', 'Ответ личного API', account.connected ? 'positive' : 'negative')}${card('Капитал', account.equity != null ? `${num(account.equity, 8)} USDT` : '—', 'Единый счёт')}${card('Доступно', account.available != null ? `${num(account.available, 8)} USDT` : '—', 'Свободные средства')}${card('Позиции', String(account.positions.length), 'Открыто')}</section>${panel('Безопасность API', `${row('Секреты на странице', 'не отображаются', 'positive')}${row('Право вывода', 'должно быть отключено', 'positive')}${row('Синтетический баланс', 'запрещён', 'positive')}${row('Последняя загрузка', dateText(state.loadedAt))}`, 'wide')}`;
  }

  function learningPage() {
    const learning = state.learning || {};
    const items = learningItems();
    const stats = learning.summary || learning.stats || {};
    const body = items.length ? items.map((item) => `<article class="v10-lesson"><header>${badge(item.status || item.priority || 'урок')}<small>${dateText(item.created_at || item.updated_at || item.timestamp)}</small></header><h3>${esc(item.title || item.lesson || item.pattern || 'Вывод обучения')}</h3><p>${esc(item.description || item.recommendation || item.reason || item.details || '')}</p>${item.evidence_id ? `<footer>Доказательство: ${esc(item.evidence_id)}</footer>` : ''}</article>`).join('') : empty('Подтверждённые выводы обучения не получены.');
    return title('Центр обучения', 'Ошибки, закономерности, улучшения и доказательства') +
      `<section class="metrics">${card('Наблюдения', String(stats.observations ?? learning.count ?? items.length), 'Сохранено')}${card('Сделки', String(stats.total_trades ?? learning.total_trades ?? '—'), 'Проанализировано')}${card('Доля успешных', stats.win_rate != null ? `${num(stats.win_rate)}%` : learning.win_rate != null ? `${num(learning.win_rate)}%` : '—', 'Только фактическая статистика')}${card('Версия', learning.version || '—', 'Контур обучения')}</section><section class="v10-lesson-grid">${body}</section>`;
  }

  function controlPage() {
    const bots = botList();
    const run = state.run || {};
    const nodes = bots.length ? bots.map((bot) => `<div class="v10-node ${verifiedBot(bot) ? 'ok' : 'bad'}"><b>${esc(bot.name || 'ИИ-модуль')}</b><span>${esc(bot.reports_to || 'Главный управляющий ИИ')}</span><small>${verifiedBot(bot) ? 'сигнал подтверждён' : 'нет свежего сигнала'}</small></div>`).join('') : empty('Карта ИИ не может быть построена без реестра модулей.');
    const decisions = evidenceItems().filter((item) => String(item.type || item.event || item.action || '').toLowerCase().match(/decision|решен|consensus/)).slice(0, 20);
    return title('Главное управление', 'Карта ИИ, подчинение, конфликты и журнал решений') +
      `<section class="metrics">${card('Всего ИИ', String(bots.length), 'В реестре')}${card('Подтверждены', String(bots.filter(verifiedBot).length), 'Свежий сигнал')}${card('Финальное решение', run.decision || '—', 'Главный управляющий ИИ')}${card('Конфликт', run.conflict || run.conflicts?.length ? 'ЕСТЬ' : 'НЕ ПОДТВЕРЖДЁН', 'Между сигналами')}</section>
      <section class="v10-grid">${panel('Карта ИИ', `<div class="v10-controller"><div class="v10-root">Главный управляющий ИИ</div><div class="v10-tree">${nodes}</div></div>`, 'wide')}${panel('Журнал решений', decisions.length ? decisions.map(evidenceCompact).join('') : empty('Подтверждённые решения в хранилище не найдены.'))}</section>`;
  }

  function evidenceCompact(item) {
    return `<div class="v10-evidence"><b>${esc(item.event || item.action || item.title || item.type || 'Событие')}</b><small>${dateText(item.time || item.created_at || item.timestamp)} · ${esc(item.source || item.agent || item.module || 'источник не указан')}</small></div>`;
  }

  function evidencePage() {
    const items = evidenceItems();
    const rows = items.length ? `<table class="v10-table"><thead><tr><th>Время</th><th>Событие</th><th>ИИ / источник</th><th>Доказательство</th><th>Результат</th></tr></thead><tbody>${items.slice(0, 200).map((item) => `<tr><td>${dateText(item.time || item.created_at || item.timestamp)}</td><td>${esc(item.event || item.action || item.title || '—')}</td><td>${esc(item.source || item.agent || item.module || '—')}</td><td>${esc(item.evidence_id || item.id || item.hash || '—')}</td><td>${esc(item.result || item.status || item.outcome || '—')}</td></tr>`).join('')}</tbody></table>` : empty('Хранилище доказательств пока не вернуло записи.');
    return title('Хранилище доказательств', 'Связь данных, решений, действий и результатов') + panel('Журнал доказательств', rows, 'wide');
  }

  function virtualPage() {
    const data = state.virtual || {};
    const trades = firstArray(data.trades, data.orders, data.history);
    return title('Виртуальный счёт', 'Проверка стратегий на реальных рыночных данных без риска капиталом') +
      `<section class="metrics">${card('Баланс', data.balance != null ? `${num(data.balance, 8)} USDT` : data.equity != null ? `${num(data.equity, 8)} USDT` : '—', 'Виртуальный капитал')}${card('PnL', data.pnl != null ? `${num(data.pnl, 8)} USDT` : '—', 'Результат')}${card('Просадка', data.drawdown_percent != null ? `${num(data.drawdown_percent)}%` : '—', 'Максимальная')}${card('Сделки', String(trades.length || data.trade_count || 0), 'История')}</section>${panel('Последние операции', trades.length ? `<table class="v10-table"><thead><tr><th>Время</th><th>Актив</th><th>Сторона</th><th>Результат</th></tr></thead><tbody>${trades.slice(0, 50).map((trade) => `<tr><td>${dateText(trade.time || trade.created_at)}</td><td>${esc(trade.symbol || trade.asset || '—')}</td><td>${esc(trade.side || '—')}</td><td>${esc(trade.net_pnl ?? trade.pnl ?? trade.status ?? '—')}</td></tr>`).join('')}</tbody></table>` : empty('Виртуальные операции пока не получены.'), 'wide')}`;
  }

  function reportsPage() {
    const report = reportData();
    const bots = botList();
    const learning = state.learning || {};
    const periods = firstArray(report.periods, report.reports, report.history);
    return title('Отчёты', 'Дневная, недельная и месячная эффективность системы') +
      `<section class="metrics">${card('Решение', report.decision || '—', 'Последнее')}${card('Фактический рост', report.actual_growth_percent != null ? `${num(report.actual_growth_percent)}%` : '—', 'Только измеренный')}${card('ИИ в отчёте', String(report.total_bots ?? bots.length), 'Модулей')}${card('Уроков', String(learning.count ?? learningItems().length), 'Центр обучения')}</section>
      <section class="v10-grid">${panel('Текущая сводка', `<p class="v10-explanation">${esc(report.report || report.reason || 'Текст отчёта пока не сформирован.')}</p>${row('Статус цели', report.goal_status || '—')}${row('Следующее действие', report.next_action || '—')}${sourceStamp('Система отчётов', report.generated_at || report.updated_at)}`, 'wide')}${panel('История отчётов', periods.length ? periods.map((period) => `<div class="v10-report"><b>${esc(period.period || period.title || 'Период')}</b><span>${esc(period.result || period.summary || period.status || '—')}</span></div>`).join('') : empty('Исторические отчёты не переданы API.'))}</section>`;
  }

  function settingsPage() {
    const saved = (() => { try { return JSON.parse(localStorage.getItem('sharipovai-settings') || '{}'); } catch { return {}; } })();
    return title('Настройки', 'Язык, рынок, обновления, ИИ, новости и безопасность') +
      `<section class="v10-settings">
        ${panel('Язык интерфейса', `<div class="v10-choice"><button data-v10-lang="ru" class="action">Русский</button><button data-v10-lang="en" class="action">English</button><button data-v10-lang="uz" class="action">O‘zbek</button></div><p>Русский язык используется по умолчанию. Переключение RU / EN / UZ остаётся доступным.</p>`)}
        ${panel('Обновление данных', `<label class="v10-field">Частота обновления<select id="v10Refresh"><option value="3">3 секунды</option><option value="5">5 секунд</option><option value="10">10 секунд</option><option value="30">30 секунд</option><option value="60">60 секунд</option></select></label><button id="v10SaveRefresh" class="action">Сохранить</button>`)}
        ${panel('Новости', `<label class="v10-check"><input type="checkbox" id="v10ImportantNews" ${saved.importantNewsOnly ? 'checked' : ''}> Только важные новости</label><label class="v10-check"><input type="checkbox" id="v10VerifiedNews" ${saved.verifiedNewsOnly !== false ? 'checked' : ''}> Только проверенные источники</label><label class="v10-check"><input type="checkbox" id="v10NewsImages" ${saved.newsImages !== false ? 'checked' : ''}> Показывать изображения источников</label>`)}
        ${panel('ИИ', `<label class="v10-check"><input type="checkbox" id="v10VerifiedAi" ${saved.verifiedOnly ? 'checked' : ''}> Показывать только подтверждённые ИИ</label><label class="v10-check"><input type="checkbox" checked disabled> Требовать доказательство действия</label><label class="v10-check"><input type="checkbox" checked disabled> Запрещать выдуманные показатели</label>`)}
        ${panel('Безопасность', `${row('Вывод средств', 'отключён', 'positive')}${row('Секреты API', 'скрыты', 'positive')}${row('Аварийная остановка', 'обязательна', 'positive')}${row('Ордера без проверки', 'запрещены', 'positive')}`)}
        ${panel('Сохранение', `<button id="v10SaveSettings" class="action">Сохранить настройки</button><button id="v10ResetSettings" class="action">Сбросить настройки</button><p id="v10SettingsStatus"></p>`, 'wide')}
      </section>`;
  }

  const renderers = {
    overview: overviewPage,
    decision: decisionPage,
    portfolio: portfolioPage,
    trades: tradesPage,
    bots: botsPage,
    news: newsPage,
    risk: riskPage,
    bybit: bybitPage,
    learning: learningPage,
    control: controlPage,
    evidence: evidencePage,
    virtual: virtualPage,
    reports: reportsPage,
    settings: settingsPage
  };

  function render(page) {
    const content = $('content');
    if (!content || !renderers[page]) return;
    content.innerHTML = renderers[page]();
    bindPage(page);
  }

  function bindPage(page) {
    if (page !== 'settings') return;
    const save = $('v10SaveSettings');
    const reset = $('v10ResetSettings');
    const saveRefresh = $('v10SaveRefresh');
    const refreshSelect = $('v10Refresh');
    let settings = {};
    try { settings = JSON.parse(localStorage.getItem('sharipovai-settings') || '{}'); } catch { settings = {}; }
    if (refreshSelect) refreshSelect.value = String(settings.refreshSeconds || 5);
    document.querySelectorAll('[data-v10-lang]').forEach((button) => button.addEventListener('click', () => {
      document.querySelector(`[data-lang="${button.dataset.v10Lang}"]`)?.click();
    }));
    const persist = () => {
      const merged = {
        ...settings,
        refreshSeconds: Number(refreshSelect?.value || settings.refreshSeconds || 5),
        importantNewsOnly: Boolean($('v10ImportantNews')?.checked),
        verifiedNewsOnly: Boolean($('v10VerifiedNews')?.checked),
        newsImages: Boolean($('v10NewsImages')?.checked),
        verifiedOnly: Boolean($('v10VerifiedAi')?.checked)
      };
      localStorage.setItem('sharipovai-settings', JSON.stringify(merged));
      if ($('v10SettingsStatus')) $('v10SettingsStatus').textContent = 'Настройки сохранены.';
    };
    save?.addEventListener('click', persist);
    saveRefresh?.addEventListener('click', persist);
    reset?.addEventListener('click', () => {
      localStorage.removeItem('sharipovai-settings');
      if ($('v10SettingsStatus')) $('v10SettingsStatus').textContent = 'Настройки сброшены. Обновите страницу.';
    });
  }

  async function getJson(url) {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error(`${response.status}`);
    return response.json();
  }

  async function load() {
    const entries = Object.entries(endpoints);
    const results = await Promise.allSettled(entries.map(([, url]) => getJson(url)));
    state.errors = {};
    results.forEach((result, index) => {
      const key = entries[index][0];
      if (result.status === 'fulfilled') state[key] = result.value;
      else state.errors[key] = result.reason?.message || 'недоступно';
    });
    state.loadedAt = new Date().toISOString();
    const active = document.querySelector('#nav button.active')?.dataset.page;
    if (renderers[active]) render(active);
  }

  function installNavigation() {
    const nav = $('nav');
    if (!nav) return;
    nav.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-page]');
      if (!button || !renderers[button.dataset.page]) return;
      setTimeout(() => render(button.dataset.page), 0);
    });
    $('refresh')?.addEventListener('click', () => setTimeout(load, 0));
  }

  window.addEventListener('DOMContentLoaded', () => {
    installNavigation();
    load().catch(() => {});
    setTimeout(() => {
      const active = document.querySelector('#nav button.active')?.dataset.page || 'overview';
      if (renderers[active]) render(active);
    }, 600);
  });
})();
