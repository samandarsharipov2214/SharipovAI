(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  const state = { loadedAt: null, results: {}, errors: {}, loading: false };
  const AUTO_REFRESH_MS = 15000;

  const checks = {
    health: { label: 'Сервер и API', url: '/api/health', required: true },
    market: { label: 'Поток котировок Bybit', url: '/api/market/bybit-websocket/status', required: true },
    account: { label: 'Личный кабинет Bybit', url: '/api/exchange/account/status', required: false },
    bots: { label: 'Реестр ИИ', url: '/api/ai-bots', required: true },
    run: { label: 'Контур решений', url: '/api/run', required: true },
    news: { label: 'Новостной контур', url: '/api/social-news', required: true },
    learning: { label: 'Контур обучения', url: '/api/learning-os/status', required: true },
    evidence: { label: 'Хранилище доказательств', url: '/api/evidence-vault/recent', required: true },
    virtual: { label: 'Виртуальный счёт', url: '/api/virtual-account/state', required: true },
    reports: { label: 'Система отчётов', url: '/api/ai-control-center/daily-report', required: true }
  };

  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === 'system-status';

  async function getJson(url) {
    const started = performance.now();
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    const latencyMs = Math.round(performance.now() - started);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return { data: await response.json(), latencyMs };
  }

  function itemCount(key, data) {
    if (!data || typeof data !== 'object') return null;
    const candidates = key === 'bots'
      ? [data.bots, data.items, data.agents]
      : key === 'news'
        ? [data.news?.items, data.news, data.items, data.articles]
        : key === 'evidence'
          ? [data.items, data.records, data.events]
          : key === 'learning'
            ? [data.items, data.lessons, data.memory?.recent_lessons]
            : [];
    const found = candidates.find(Array.isArray);
    return found ? found.length : null;
  }

  function shortDiagnostic(value) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    if (!text) return '';
    const lower = text.toLowerCase();
    if (lower.includes('read-only') || lower.includes('read only')) return 'Ключ Bybit должен разрешать только чтение аккаунта.';
    if (lower.includes('api key') || lower.includes('preflight')) return 'Проверь read-only ключи Bybit. Виртуальная торговля работает без них.';
    if (lower.includes('http 401') || lower.includes('http 403')) return 'Доступ отклонён.';
    if (lower.includes('http 503')) return 'Сервис временно не отвечает.';
    return text.length > 120 ? `${text.slice(0, 117)}…` : text;
  }

  function semanticState(key) {
    const result = state.results[key];
    const error = state.errors[key];
    if (key === 'account') {
      if (!result || error) {
        return { level: 'optional', label: 'НЕ НАСТРОЕН', detail: shortDiagnostic(error) || 'Необязательное подключение.' };
      }
      const data = result.data || {};
      if (data.connected === true) return { level: 'ok', label: 'ПОДКЛЮЧЁН', detail: 'Только чтение.' };
      if (data.credentials_configured !== true || data.sync_enabled === false) {
        return { level: 'optional', label: 'НЕ НАСТРОЕН', detail: 'Не влияет на виртуальную торговлю.' };
      }
      return { level: 'optional', label: 'НЕ НАСТРОЕН', detail: shortDiagnostic(data.last_error || data.error) || 'Проверь read-only ключи.' };
    }
    if (!result || error) return { level: 'bad', label: 'НЕДОСТУПЕН', detail: shortDiagnostic(error) || 'Нет ответа.' };
    const data = result.data || {};
    const status = String(data.status || data.state || '').toLowerCase();
    if (['error', 'unavailable', 'failed', 'offline'].includes(status)) {
      return { level: 'bad', label: 'НЕДОСТУПЕН', detail: shortDiagnostic(data.message || data.error || status) };
    }
    return { level: 'ok', label: 'ДОСТУПЕН', detail: '' };
  }

  function verifiedAi(data) {
    const bots = Array.isArray(data?.bots) ? data.bots : Array.isArray(data?.items) ? data.items : [];
    const verified = bots.filter((bot) => {
      const age = Number(bot?.heartbeat_age_seconds);
      if (Number.isFinite(age)) return age < 90;
      const stamp = bot?.last_seen || bot?.updated_at || bot?.timestamp;
      if (!stamp) return false;
      return Date.now() - new Date(stamp).getTime() < 90000;
    }).length;
    return { total: bots.length, verified };
  }

  function serviceCard(key) {
    const meta = checks[key];
    const result = state.results[key];
    const semantic = semanticState(key);
    const count = result ? itemCount(key, result.data) : null;
    const css = semantic.level === 'bad' && meta.required ? 'bad' : 'ok';
    const facts = [];
    if (result) facts.push(`<span>Отклик <b>${result.latencyMs} мс</b></span>`);
    if (count != null) facts.push(`<span>Объектов <b>${count}</b></span>`);
    if (semantic.detail) facts.push(`<span class="status-service-note">${esc(semantic.detail)}</span>`);
    return `<article class="status-service ${css}">
      <div class="status-service-head">
        <span class="status-dot"></span>
        <div><b>${esc(meta.label)}</b><small>${esc(meta.url)}${meta.required ? '' : ' · необязательно'}</small></div>
        <strong>${esc(semantic.label)}</strong>
      </div>
      ${facts.length ? `<div class="status-service-body">${facts.join('')}</div>` : ''}
    </article>`;
  }

  function ageText() {
    if (!state.loadedAt) return 'Проверка ещё не выполнялась';
    const seconds = Math.max(0, Math.floor((Date.now() - new Date(state.loadedAt).getTime()) / 1000));
    if (seconds < 60) return `Проверено ${seconds} сек назад`;
    const minutes = Math.floor(seconds / 60);
    return `Проверено ${minutes} мин назад`;
  }

  function updateClock() {
    const clock = $('statusClock');
    const age = $('statusAge');
    const checked = $('statusCheckedAt');
    if (clock) clock.textContent = new Date().toLocaleTimeString('ru-RU');
    if (age) age.textContent = ageText();
    if (checked) checked.textContent = state.loadedAt ? `Последняя проверка: ${new Date(state.loadedAt).toLocaleTimeString('ru-RU')}` : 'Ожидание первой проверки';
  }

  function render() {
    if (!active()) return;
    const content = $('content');
    if (!content) return;
    const keys = Object.keys(checks);
    const required = keys.filter((key) => checks[key].required);
    const available = required.filter((key) => semanticState(key).level === 'ok').length;
    const ai = verifiedAi(state.results.bots?.data);
    const market = semanticState('market');
    const account = semanticState('account');
    const overall = available === required.length ? 'ВСЁ РАБОТАЕТ' : available > 0 ? 'ЕСТЬ СБОИ' : 'НЕТ СВЯЗИ';
    const tone = available === required.length ? 'positive' : 'negative';

    content.innerHTML = `<div class="title"><h1>Состояние системы</h1><p>Автоматическая проверка каждые 15 секунд</p></div>
      <section class="metrics">
        <article class="card"><span>Основные системы</span><strong class="${tone}">${overall}</strong><small>${available}/${required.length} работают</small></article>
        <article class="card"><span>ИИ онлайн</span><strong>${ai.verified}/${ai.total}</strong><small>Активность до 90 секунд</small></article>
        <article class="card"><span>Рынок</span><strong class="${market.level === 'ok' ? 'positive' : 'negative'}">${esc(market.label)}</strong><small>Публичные котировки Bybit</small></article>
        <article class="card"><span>Личный Bybit</span><strong class="${account.level === 'ok' ? 'positive' : ''}">${esc(account.label)}</strong><small>Не нужен для виртуального счёта</small></article>
        <article class="card"><span>Текущее время</span><strong id="statusClock">${esc(new Date().toLocaleTimeString('ru-RU'))}</strong><small id="statusAge">${esc(ageText())}</small></article>
      </section>
      <div class="status-actions"><button id="statusRefresh" class="action">Проверить сейчас</button><span id="statusCheckedAt"></span></div>
      <section class="status-grid">${keys.map(serviceCard).join('')}</section>`;
    $('statusRefresh')?.addEventListener('click', () => load(true));
    updateClock();
  }

  async function load(manual = false) {
    if (state.loading || !active()) return;
    state.loading = true;
    const button = $('statusRefresh');
    if (button && manual) { button.disabled = true; button.textContent = 'Проверяю…'; }
    const entries = Object.entries(checks);
    const settled = await Promise.allSettled(entries.map(([, meta]) => getJson(meta.url)));
    const nextResults = {};
    const nextErrors = {};
    settled.forEach((result, index) => {
      const key = entries[index][0];
      if (result.status === 'fulfilled') nextResults[key] = result.value;
      else nextErrors[key] = result.reason?.message || 'Нет ответа';
    });
    state.results = nextResults;
    state.errors = nextErrors;
    state.loadedAt = new Date().toISOString();
    state.loading = false;
    render();
  }

  function install() {
    const nav = $('nav');
    if (!nav) return;
    let button = nav.querySelector('[data-page="system-status"]');
    if (!button) {
      button = document.createElement('button');
      button.type = 'button';
      button.dataset.page = 'system-status';
      button.textContent = 'Состояние системы';
      nav.insertBefore(button, nav.firstChild);
    }
    if (button.dataset.statusBound === '1') return;
    button.dataset.statusBound = '1';
    button.addEventListener('click', () => {
      nav.querySelectorAll('button[data-page]').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      render();
      load();
      history.replaceState(null, '', '#system-status');
    });
    if (location.hash === '#system-status') button.click();
  }

  window.addEventListener('DOMContentLoaded', install);
  setInterval(updateClock, 1000);
  setInterval(() => { if (active() && !document.hidden) load(); }, AUTO_REFRESH_MS);
})();
