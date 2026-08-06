(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const finite = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
  const array = (value) => Array.isArray(value) ? value : [];
  const object = (value) => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const money = (value) => {
    const number = finite(value);
    return number === null ? '—' : `${number.toLocaleString('ru-RU', {maximumFractionDigits: 4})} USDT`;
  };
  const statusClass = (status) => {
    const value = String(status || '').toLowerCase();
    return value === 'healthy' || value === 'ok' || value === 'running' ? 'positive'
      : value === 'blocked' || value === 'error' || value === 'failed' ? 'negative'
        : '';
  };
  const statusText = (status) => String(status || 'unknown').toUpperCase();
  const card = (label, value, note = '', tone = '') => `<article class="card"><span>${esc(label)}</span><strong class="${esc(tone)}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
  const row = (label, value, tone = '') => `<div class="v10-row"><span>${esc(label)}</span><b class="${esc(tone)}">${esc(value)}</b></div>`;
  const empty = (text) => `<div class="empty">${esc(text)}</div>`;
  const panel = (title, body, wide = '') => `<article class="panel ${wide}"><small>CANONICAL RUNTIME</small><h2>${esc(title)}</h2>${body}</article>`;

  const state = {
    loading: false,
    loadedAt: null,
    paper: null,
    decisionRuntime: null,
    organs: null,
    health: null,
    market: null,
    quote: null,
    news: null,
    evidence: null,
    errors: {},
  };

  const activePage = () => window.SharipovAIPageCoordinator?.activePage?.()
    || document.querySelector('#nav button.active[data-page]')?.dataset.page
    || 'overview';

  async function getJson(url) {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function positions(paper) {
    const value = paper?.positions;
    if (Array.isArray(value)) return value;
    if (value && typeof value === 'object') {
      return Object.entries(value).map(([symbol, position]) => ({symbol, ...object(position)}));
    }
    return [];
  }

  function organRows() {
    return array(state.organs?.organs);
  }

  function componentRows() {
    return array(state.health?.components);
  }

  function newsRows() {
    const payload = object(state.news);
    const nested = object(payload.news);
    const candidates = [nested.items, payload.news, payload.items, payload.articles];
    return array(candidates.find(Array.isArray));
  }

  function renderOverview() {
    const paper = object(state.paper);
    const market = object(paper.market_stream || state.market);
    const organs = organRows();
    const counts = object(state.organs?.counts);
    const components = componentRows();
    const healthStatus = String(state.health?.status || 'unknown');
    const currentPositions = positions(paper);
    const quote = object(state.quote);
    const news = newsRows().slice(0, 5);
    const failures = Object.keys(state.errors).length;
    const realOrdersBlocked = paper.real_execution_enabled !== true;
    const source = paper.source_of_truth || 'autonomous_paper';
    const decisionMode = state.decisionRuntime?.decision_mode || 'CANONICAL_COUNCIL_REQUIRED';

    const positionRows = currentPositions.length
      ? currentPositions.slice(0, 8).map((position) => `<div class="v10-row"><span>${esc(position.symbol || '—')}</span><b>${esc(money((finite(position.current_price) || finite(position.entry_price) || 0) * (finite(position.quantity) || 0)))}</b></div>`).join('')
      : empty('Открытых канонических позиций нет.');
    const confirmedNews = news.length
      ? news.map((item) => `<div class="news-item"><b>${esc(item.title || item.headline || 'Новость')}</b><small>${esc(item.source || item.publisher || 'Источник не указан')}</small></div>`).join('')
      : empty('Подтверждённые новости пока не получены.');

    return `<div class="title"><h1>Центр управления</h1><p>Только канонические runtime-данные; legacy API не участвуют в выводах</p></div>
      <section class="metrics">
        ${card('Источник исполнения', 'CouncilAuthorizedPaperLoop', source, 'positive')}
        ${card('Equity', money(paper.equity), 'канонический paper account')}
        ${card('Cash', money(paper.cash), 'свободный виртуальный капитал')}
        ${card('Открытые позиции', String(currentPositions.length), 'снимок без мутации при чтении')}
        ${card('AI runtime', statusText(state.organs?.status), `healthy ${counts.healthy || 0} · degraded ${counts.degraded || 0} · blocked ${counts.blocked || 0}`, statusClass(state.organs?.status))}
        ${card('System health', statusText(healthStatus), `${components.length} наблюдаемых компонентов`, statusClass(healthStatus))}
      </section>
      <section class="v10-grid">
        ${panel('Каноническое исполнение', `${row('Режим решения', decisionMode, decisionMode === 'CANONICAL_COUNCIL_REQUIRED' ? 'positive' : 'negative')}${row('Реальные ордера', realOrdersBlocked ? 'ЗАБЛОКИРОВАНЫ' : 'РАЗРЕШЕНЫ', realOrdersBlocked ? 'positive' : 'negative')}${row('DB-backed state', paper.database_backed === true ? 'ДА' : 'НЕТ', paper.database_backed === true ? 'positive' : 'negative')}${row('Worker', paper.worker_running === true ? 'RUNNING' : 'STOPPED', paper.worker_running === true ? 'positive' : '')}${row('WAIT dedup interval', paper.wait_event_min_interval_seconds != null ? `${paper.wait_event_min_interval_seconds} сек` : '—')}${row('Read mutation', paper.mutation_on_read === false ? 'ЗАПРЕЩЕНА' : 'НЕ ПОДТВЕРЖДЕНО', paper.mutation_on_read === false ? 'positive' : 'negative')}`)}
        ${panel('Рынок', `${row('BTC/USDT', quote.price != null ? money(quote.price) : '—')}${row('Market stream', statusText(market.status || state.market?.status), statusClass(market.status || state.market?.status))}${row('Verified', market.verified === true ? 'ДА' : 'НЕТ', market.verified === true ? 'positive' : 'negative')}${row('Источник', quote.source || '—')}`)}
        ${panel('Открытые позиции', positionRows, 'wide')}
        ${panel('Новости', confirmedNews)}
        ${panel('Runtime honesty', `${row('Legacy /api/run', 'НЕ ИСПОЛЬЗУЕТСЯ', 'positive')}${row('Legacy /api/ai-bots', 'НЕ ИСПОЛЬЗУЕТСЯ', 'positive')}${row('Legacy PaperActivityEngine', 'DEPRECATED', 'positive')}${row('Ошибки загрузки', String(failures), failures ? 'negative' : 'positive')}${row('Обновлено', state.loadedAt || '—')}`)}
      </section>`;
  }

  function organCard(organ) {
    const evidence = array(organ.evidence);
    const blockers = array(organ.blockers);
    return `<article class="ai14-card"><header><div><small>${esc(organ.responsibility || 'Ответственность не передана')}</small><h3>${esc(organ.organ_id || 'unknown')}</h3></div><span class="ai14-badge ${statusClass(organ.status) === 'positive' ? 'good' : statusClass(organ.status) === 'negative' ? 'bad' : 'warn'}">${esc(statusText(organ.status))}</span></header>
      <p>Проверено: ${esc(organ.checked_at_ms ? new Date(Number(organ.checked_at_ms)).toLocaleString('ru-RU') : '—')}</p>
      <section><h3>Evidence</h3>${evidence.length ? `<ul>${evidence.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>` : empty('Evidence не получены.')}</section>
      <section><h3>Blockers</h3>${blockers.length ? `<ul>${blockers.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>` : '<p class="positive">Блокеров нет.</p>'}</section></article>`;
  }

  function renderAiCenter() {
    const organs = organRows();
    const counts = object(state.organs?.counts);
    return `<div class="title"><h1>Центр ИИ</h1><p>Девять зарегистрированных органов — это реестр архитектуры, а не обещание, что все healthy</p></div>
      <section class="metrics">
        ${card('Зарегистрировано', String(state.organs?.organ_count ?? organs.length), 'канонический реестр')}
        ${card('Healthy', String(counts.healthy || 0), 'подтверждено runtime evidence', 'positive')}
        ${card('Degraded', String(counts.degraded || 0), 'есть предупреждения')}
        ${card('Blocked', String(counts.blocked || 0), 'есть критические блокеры', counts.blocked ? 'negative' : '')}
        ${card('Итог', statusText(state.organs?.status), 'не подменяется формулой 9/9', statusClass(state.organs?.status))}
      </section>
      <div class="status-actions"><button id="canonicalRefreshOrgans" class="action" type="button">Обновить evidence</button><span>${esc(state.loadedAt || '')}</span></div>
      <section class="ai14-grid">${organs.length ? organs.map(organCard).join('') : empty('Канонический реестр ИИ недоступен.')}</section>`;
  }

  function componentCard(component) {
    const evidence = array(component.evidence);
    const blockers = array(component.blockers);
    const recovery = array(component.recovery);
    const detail = [
      evidence.length ? `Evidence: ${evidence.join(' · ')}` : '',
      blockers.length ? `Blockers: ${blockers.join(' · ')}` : '',
      recovery.length ? `Recovery: ${recovery.join(' · ')}` : '',
    ].filter(Boolean).join(' | ');
    return `<article class="status-service ${statusClass(component.status) === 'negative' ? 'bad' : 'ok'}"><div class="status-service-head"><span class="status-dot"></span><div><b>${esc(component.component || 'unknown')}</b><small>${esc(detail || 'Нет дополнительного evidence')}</small></div><strong>${esc(statusText(component.status))}</strong></div></article>`;
  }

  function renderSystemStatus() {
    const components = componentRows();
    const systemCounts = object(state.health?.counts);
    const organCounts = object(state.organs?.counts);
    const market = object(state.market);
    const paper = object(state.paper);
    return `<div class="title"><h1>Состояние системы</h1><p>Статусы из SystemHealthCenter и AIOrganRuntimeMonitor, а не из количества ответивших URL</p></div>
      <section class="metrics">
        ${card('System verdict', statusText(state.health?.status), `healthy ${systemCounts.healthy || 0} · degraded ${systemCounts.degraded || 0} · blocked ${systemCounts.blocked || 0}`, statusClass(state.health?.status))}
        ${card('AI verdict', statusText(state.organs?.status), `healthy ${organCounts.healthy || 0} · degraded ${organCounts.degraded || 0} · blocked ${organCounts.blocked || 0}`, statusClass(state.organs?.status))}
        ${card('Market stream', statusText(market.status), market.verified === true ? 'verified' : 'not verified', market.verified === true ? 'positive' : 'negative')}
        ${card('Paper worker', paper.worker_running === true ? 'RUNNING' : 'STOPPED', 'CouncilAuthorizedPaperLoop', paper.worker_running === true ? 'positive' : '')}
        ${card('Execution locks', paper.real_execution_enabled === false ? 'ACTIVE' : 'UNSAFE', 'real execution must remain disabled', paper.real_execution_enabled === false ? 'positive' : 'negative')}
      </section>
      <div class="status-actions"><button id="canonicalRefreshStatus" class="action" type="button">Проверить сейчас</button><span>${esc(state.loadedAt || '')}</span></div>
      <section class="status-grid">${components.length ? components.map(componentCard).join('') : empty('SystemHealthCenter недоступен.')}</section>`;
  }

  function render() {
    const content = $('content');
    if (!content) return;
    const page = activePage();
    if (page === 'overview') content.innerHTML = renderOverview();
    else if (page === 'bots') content.innerHTML = renderAiCenter();
    else if (page === 'system-status') content.innerHTML = renderSystemStatus();
    else return;
    bind();
  }

  function bind() {
    $('canonicalRefreshOrgans')?.addEventListener('click', () => load(true));
    $('canonicalRefreshStatus')?.addEventListener('click', () => load(true));
  }

  async function load(forceOrganRefresh = false) {
    if (state.loading) return;
    const page = activePage();
    if (!['overview', 'bots', 'system-status'].includes(page)) return;
    state.loading = true;
    const endpoints = [
      ['paper', '/api/autonomous-paper/status'],
      ['decisionRuntime', '/api/autonomous-paper/decision-runtime'],
      ['organs', forceOrganRefresh ? '/api/system/ai-organs/refresh' : '/api/system/ai-organs', forceOrganRefresh ? 'POST' : 'GET'],
      ['health', '/api/system/health'],
      ['market', '/api/market/stream/status'],
      ['quote', '/api/market/quote/BTCUSDT'],
      ['news', '/api/social-news'],
      ['evidence', '/api/evidence-vault/recent'],
    ];
    const settled = await Promise.allSettled(endpoints.map(async ([, url, method]) => {
      const response = await fetch(url, {method: method || 'GET', credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }));
    state.errors = {};
    settled.forEach((result, index) => {
      const key = endpoints[index][0];
      if (result.status === 'fulfilled') state[key] = result.value;
      else state.errors[key] = result.reason?.message || 'unavailable';
    });
    state.loadedAt = new Date().toLocaleString('ru-RU');
    state.loading = false;
    render();
  }

  function ensureSystemStatusButton() {
    const nav = $('nav');
    if (!nav || nav.querySelector('[data-page="system-status"]')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.page = 'system-status';
    button.textContent = 'Состояние системы';
    nav.insertBefore(button, nav.firstChild);
  }

  function install() {
    ensureSystemStatusButton();
    const nav = $('nav');
    nav?.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-page]');
      if (!button || !['overview', 'bots', 'system-status'].includes(button.dataset.page)) return;
      setTimeout(() => load().catch(() => {}), 0);
    });
    $('refresh')?.addEventListener('click', () => load().catch(() => {}));
    if (['overview', 'bots', 'system-status'].includes(activePage())) load().catch(() => {});
  }

  window.addEventListener('DOMContentLoaded', install);
  setInterval(() => {
    if (!document.hidden && ['overview', 'bots', 'system-status'].includes(activePage())) {
      load().catch(() => {});
    }
  }, 15000);
})();
