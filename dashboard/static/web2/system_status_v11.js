(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  const nowText = () => new Date().toLocaleString('ru-RU');
  const state = { loadedAt: null, results: {}, errors: {} };

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

  function semanticState(key) {
    const result = state.results[key];
    const error = state.errors[key];
    if (!result || error) return { level: 'bad', label: 'НЕДОСТУПЕН', detail: error || 'нет ответа' };
    const data = result.data || {};
    if (key === 'account') {
      if (data.credentials_configured !== true || data.sync_enabled === false) {
        return { level: 'optional', label: 'НЕ НАСТРОЕН', detail: 'необязательный личный API; виртуальный режим активен' };
      }
      if (data.connected === true) return { level: 'ok', label: 'ПОДКЛЮЧЁН', detail: 'read-only snapshot подтверждён' };
      return { level: 'bad', label: 'ОШИБКА', detail: data.last_error || 'учётные данные заданы, но snapshot не получен' };
    }
    const status = String(data.status || data.state || '').toLowerCase();
    if (['error', 'unavailable', 'failed', 'offline'].includes(status)) {
      return { level: 'bad', label: 'НЕДОСТУПЕН', detail: data.message || data.error || status };
    }
    return { level: 'ok', label: 'ДОСТУПЕН', detail: 'нет' };
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
    const css = semantic.level === 'bad' ? 'bad' : 'ok';
    return `<article class="status-service ${css}">
      <div class="status-service-head">
        <span class="status-dot"></span>
        <div><b>${esc(meta.label)}</b><small>${esc(meta.url)}${meta.required ? '' : ' · необязательный'}</small></div>
        <strong>${esc(semantic.label)}</strong>
      </div>
      <div class="status-service-body">
        <span>Задержка: <b>${result ? `${result.latencyMs} мс` : '—'}</b></span>
        <span>Записей: <b>${count == null ? '—' : count}</b></span>
        <span>Состояние: <b>${esc(semantic.detail)}</b></span>
      </div>
    </article>`;
  }

  function render() {
    const content = $('content');
    if (!content) return;
    const keys = Object.keys(checks);
    const required = keys.filter((key) => checks[key].required);
    const available = required.filter((key) => semanticState(key).level === 'ok').length;
    const ai = verifiedAi(state.results.bots?.data);
    const market = state.results.market?.data || {};
    const account = semanticState('account');
    const overall = available === required.length ? 'ОСНОВНЫЕ СИСТЕМЫ ДОСТУПНЫ' : available > 0 ? 'ЧАСТЬ ОСНОВНЫХ СИСТЕМ НЕДОСТУПНА' : 'СИСТЕМА НЕ ОТВЕЧАЕТ';
    const tone = available === required.length ? 'positive' : 'negative';

    content.innerHTML = `<div class="title"><h1>Состояние системы</h1><p>Основные сервисы и необязательные подключения проверяются раздельно</p></div>
      <section class="metrics">
        <article class="card"><span>Общее состояние</span><strong class="${tone}">${overall}</strong><small>${available}/${required.length} основных источников отвечают</small></article>
        <article class="card"><span>ИИ с подтверждением</span><strong>${ai.verified}/${ai.total}</strong><small>Свежий сигнал до 90 секунд</small></article>
        <article class="card"><span>Личный Bybit API</span><strong class="${account.level === 'bad' ? 'negative' : 'positive'}">${esc(account.label)}</strong><small>${esc(account.detail)}</small></article>
        <article class="card"><span>Поток рынка</span><strong>${esc(market.status || market.state || (state.results.market ? 'ОТВЕЧАЕТ' : '—'))}</strong><small>Публичный WebSocket</small></article>
        <article class="card"><span>Последняя проверка</span><strong>${esc(state.loadedAt ? new Date(state.loadedAt).toLocaleTimeString('ru-RU') : '—')}</strong><small>Локальное время</small></article>
      </section>
      <div class="status-actions"><button id="statusRefresh" class="action">Проверить сейчас</button><span>Проверено: ${esc(state.loadedAt ? nowText() : 'ещё не проверено')}</span></div>
      <section class="status-grid">${keys.map(serviceCard).join('')}</section>
      <article class="panel wide"><small>ПРАВИЛО ДОСТОВЕРНОСТИ</small><h2>Как читать статусы</h2><p>«Доступен» означает успешный и семантически корректный ответ API. «Не настроен» для личного Bybit API не считается поломкой: виртуальная торговля продолжает использовать публичные котировки, а реальные ордера остаются заблокированными.</p></article>`;
    $('statusRefresh')?.addEventListener('click', load);
  }

  async function load() {
    const button = $('statusRefresh');
    if (button) { button.disabled = true; button.textContent = 'Проверяю…'; }
    state.results = {};
    state.errors = {};
    const entries = Object.entries(checks);
    const settled = await Promise.allSettled(entries.map(([, meta]) => getJson(meta.url)));
    settled.forEach((result, index) => {
      const key = entries[index][0];
      if (result.status === 'fulfilled') state.results[key] = result.value;
      else state.errors[key] = result.reason?.message || 'нет ответа';
    });
    state.loadedAt = new Date().toISOString();
    render();
  }

  function install() {
    const nav = $('nav');
    if (!nav || nav.querySelector('[data-page="system-status"]')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.page = 'system-status';
    button.textContent = 'Состояние системы';
    nav.insertBefore(button, nav.firstChild);
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
})();
