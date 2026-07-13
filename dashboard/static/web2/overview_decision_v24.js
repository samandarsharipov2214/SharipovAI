(() => {
  'use strict';

  const OWNER = 'overview_decision_v24.js';
  const state = { health: {}, system: {}, run: {}, account: {}, bots: {}, evidence: {}, loadedAt: null, errors: {} };
  const content = document.getElementById('content');
  const nav = document.getElementById('nav');
  if (!content || !nav) return;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const locale = () => document.documentElement.lang === 'en' ? 'en-US' : document.documentElement.lang === 'uz' ? 'uz-UZ' : 'ru-RU';
  const text = (ru, en, uz) => document.documentElement.lang === 'en' ? en : document.documentElement.lang === 'uz' ? uz : ru;
  const number = (value, digits = 2) => Number(value).toLocaleString(locale(), { maximumFractionDigits: digits });
  const firstArray = (...values) => values.find(Array.isArray) || [];
  const title = (heading, subtitle) => `<div class="title"><h1>${esc(heading)}</h1><p>${esc(subtitle)}</p></div>`;
  const card = (label, value, note, tone = '') => `<article class="card"><span>${esc(label)}</span><strong class="${tone}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
  const panel = (heading, body, extra = '') => `<article class="panel ${extra}"><small>SHARIPOVAI</small><h2>${esc(heading)}</h2>${body}</article>`;
  const empty = (message) => `<div class="empty">${esc(message)}</div>`;

  function activePage() {
    return window.SharipovAIPageCoordinator?.activePage?.() || nav.querySelector('button.active[data-page]')?.dataset.page || 'overview';
  }

  function mayRender(page) {
    return window.SharipovAIPageCoordinator?.canRender?.(OWNER, page) ?? ['overview', 'decision'].includes(page);
  }

  function accountSnapshot() {
    const root = state.account || {};
    const data = root.snapshot || root.account || root.result || root;
    const positions = firstArray(data.positions, root.positions, data.list);
    const equity = data.total_equity ?? data.totalEquity ?? data.equity ?? data.wallet_balance;
    const available = data.total_available_balance ?? data.totalAvailableBalance ?? data.available_balance ?? data.available;
    const connected = root.connected === true || root.verified === true || (equity != null && root.status !== 'error');
    return { equity, available, positions, connected };
  }

  function bots() {
    return firstArray(state.bots?.bots, state.bots?.items, state.bots?.agents);
  }

  function freshBot(bot) {
    const age = Number(bot?.heartbeat_age_seconds);
    return Number.isFinite(age) && age <= 90;
  }

  function evidenceItems() {
    return firstArray(state.evidence?.items, state.evidence?.records, state.evidence?.events);
  }

  function renderOverview() {
    const account = accountSnapshot();
    const list = bots();
    const fresh = list.filter(freshBot).length;
    const healthComponents = firstArray(state.system?.components);
    const blocked = healthComponents.filter((item) => item?.status === 'blocked').length;
    const degraded = healthComponents.filter((item) => item?.status === 'degraded').length;
    const quoteMode = state.health?.status === 'ok' ? text('API отвечает', 'API online', 'API ishlamoqda') : text('API не подтверждён', 'API unverified', 'API tasdiqlanmagan');
    const lastDecision = state.run?.decision || state.run?.action || '—';
    const risk = state.run?.risk_level || state.run?.risk || '—';
    const records = evidenceItems().slice(0, 8);

    return title(text('Центр управления', 'Control center', 'Boshqaruv markazi'), text('Фактическое состояние SharipovAI без выдуманных процентов', 'Verified SharipovAI state without invented percentages', 'To‘qima foizlarsiz SharipovAI holati')) +
      `<section class="metrics">
        ${card(text('Сервер и API', 'Server and API', 'Server va API'), quoteMode, state.loadedAt ? new Date(state.loadedAt).toLocaleTimeString(locale()) : '—', state.health?.status === 'ok' ? 'positive' : 'negative')}
        ${card(text('Bybit', 'Bybit', 'Bybit'), account.connected ? text('Подключён', 'Connected', 'Ulangan') : text('Не подтверждён', 'Unverified', 'Tasdiqlanmagan'), account.equity != null ? `${number(account.equity, 8)} USDT` : '—', account.connected ? 'positive' : 'negative')}
        ${card(text('ИИ со свежим сигналом', 'AI with fresh heartbeat', 'Yangi signalli AI'), `${fresh}/${list.length}`, text('Не старше 90 секунд', 'Not older than 90 seconds', '90 soniyadan eski emas'))}
        ${card(text('Системные блокировки', 'System blocks', 'Tizim bloklari'), String(blocked), degraded ? `${degraded} ${text('в деградации', 'degraded', 'pasaygan')}` : text('Деградаций нет', 'No degradation', 'Pasayish yo‘q'), blocked ? 'negative' : 'positive')}
        ${card(text('Последнее решение', 'Latest decision', 'Oxirgi qaror'), lastDecision, risk !== '—' ? `${text('Риск', 'Risk', 'Xavf')}: ${risk}` : '')}
      </section>
      <section class="grid">
        ${panel(text('Капитал и позиции', 'Capital and positions', 'Kapital va pozitsiyalar'), `<div class="status-list"><div><span>${esc(text('Капитал', 'Equity', 'Kapital'))}</span><b>${account.equity != null ? `${number(account.equity, 8)} USDT` : '—'}</b></div><div><span>${esc(text('Доступно', 'Available', 'Mavjud'))}</span><b>${account.available != null ? `${number(account.available, 8)} USDT` : '—'}</b></div><div><span>${esc(text('Открытые позиции', 'Open positions', 'Ochiq pozitsiyalar'))}</span><b>${account.positions.length}</b></div></div>`, 'wide')}
        ${panel(text('Последние доказательства', 'Latest evidence', 'Oxirgi dalillar'), records.length ? records.map((item) => `<div class="activity-item"><div><b>${esc(item.event || item.action || item.title || item.type || text('Событие', 'Event', 'Hodisa'))}</b><p>${esc(item.result || item.status || item.outcome || '')}</p><small>${esc(item.source || item.agent || item.module || '—')} · ${esc(item.evidence_id || item.id || '—')}</small></div></div>`).join('') : empty(text('Записи пока не получены', 'No records received yet', 'Yozuvlar hali olinmadi')))}
      </section>`;
  }

  function voteItems() {
    return firstArray(state.run?.votes, state.run?.agents, state.run?.signals, state.run?.consensus?.votes);
  }

  function renderDecision() {
    const run = state.run || {};
    const decision = run.decision || run.action || '—';
    const confidence = run.confidence != null && Number.isFinite(Number(run.confidence)) ? `${number(run.confidence)}%` : '—';
    const risk = run.risk_level || run.risk || '—';
    const votes = voteItems();
    const evidence = evidenceItems().filter((item) => /decision|consensus|решен/i.test(String(item.type || item.event || item.action || ''))).slice(0, 12);
    const votesHtml = votes.length ? votes.map((vote) => `<div class="activity-item"><div><b>${esc(vote.name || vote.agent || vote.module || text('ИИ-модуль', 'AI module', 'AI moduli'))}</b><p>${esc(vote.vote || vote.decision || vote.signal || '—')}</p><small>${esc(vote.reason || vote.explanation || '')}</small></div></div>`).join('') : empty(text('Голоса ИИ не переданы API', 'AI votes were not returned by the API', 'AI ovozlari API orqali kelmadi'));
    const evidenceHtml = evidence.length ? evidence.map((item) => `<div class="activity-item"><div><b>${esc(item.event || item.action || item.type || text('Решение', 'Decision', 'Qaror'))}</b><p>${esc(item.result || item.outcome || item.status || '')}</p><small>${esc(item.evidence_id || item.id || '—')}</small></div></div>`).join('') : empty(text('Доказательства решения пока не найдены', 'Decision evidence was not found', 'Qaror dalillari topilmadi'));

    return title(text('Решение ИИ', 'AI decision', 'AI qarori'), text('Решение, риск, объяснение, голоса и доказательства', 'Decision, risk, explanation, votes and evidence', 'Qaror, xavf, izoh, ovozlar va dalillar')) +
      `<section class="metrics">
        ${card(text('Решение', 'Decision', 'Qaror'), decision, text('Главный управляющий ИИ', 'General AI', 'Bosh AI'))}
        ${card(text('Уверенность', 'Confidence', 'Ishonch'), confidence, text('Только при наличии измерения', 'Only when measured', 'Faqat o‘lchov bo‘lsa'))}
        ${card(text('Риск', 'Risk', 'Xavf'), risk, text('Оценка центра рисков', 'Risk center assessment', 'Xavf markazi bahosi'))}
        ${card(text('Голоса', 'Votes', 'Ovozlar'), String(votes.length), text('Переданы API', 'Returned by API', 'API orqali kelgan'))}
      </section>
      <section class="grid">
        ${panel(text('Обоснование', 'Reasoning', 'Asos'), `<p class="v10-explanation">${esc(run.reason || run.explanation || run.report || text('Обоснование пока не получено', 'No reasoning received yet', 'Asos hali olinmadi'))}</p>`, 'wide')}
        ${panel(text('Голоса ИИ', 'AI votes', 'AI ovozlari'), votesHtml)}
        ${panel(text('Цепочка доказательств', 'Evidence chain', 'Dalillar zanjiri'), evidenceHtml)}
      </section>`;
  }

  function render() {
    const page = activePage();
    if (!mayRender(page)) return;
    if (page === 'overview') content.innerHTML = renderOverview();
    else if (page === 'decision') content.innerHTML = renderDecision();
  }

  async function getJson(url) {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function load() {
    const endpoints = {
      health: '/api/health', system: '/api/system/health', run: '/api/run',
      account: '/api/exchange/account/snapshot', bots: '/api/ai-bots',
      evidence: '/api/evidence-vault/recent'
    };
    const entries = Object.entries(endpoints);
    const results = await Promise.allSettled(entries.map(([, url]) => getJson(url)));
    state.errors = {};
    results.forEach((result, index) => {
      const key = entries[index][0];
      if (result.status === 'fulfilled') state[key] = result.value;
      else state.errors[key] = result.reason?.message || 'unavailable';
    });
    state.loadedAt = new Date().toISOString();
    render();
  }

  nav.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-page]');
    if (button && ['overview', 'decision'].includes(button.dataset.page)) setTimeout(render, 0);
  });
  window.addEventListener('sharipovai:refresh', load);
  window.addEventListener('sharipovai:language', render);
  window.addEventListener('DOMContentLoaded', () => {
    load().catch(() => render());
    setInterval(() => {
      if (['overview', 'decision'].includes(activePage())) load().catch(() => {});
    }, 15000);
  }, { once: true });
})();
