(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  const nowText = () => new Date().toLocaleString('ru-RU');
  const state = { loadedAt: null, results: {}, errors: {} };

  const checks = {
    health: { label: 'Сервер и API', url: '/api/health' },
    market: { label: 'Поток котировок Bybit', url: '/api/market/bybit-websocket/status' },
    account: { label: 'Личный кабинет Bybit', url: '/api/exchange/account/snapshot' },
    bots: { label: 'Реестр ИИ', url: '/api/ai-bots' },
    run: { label: 'Контур решений', url: '/api/run' },
    news: { label: 'Новостной контур', url: '/api/social-news' },
    learning: { label: 'Контур обучения', url: '/api/learning-os/status' },
    evidence: { label: 'Хранилище доказательств', url: '/api/evidence-vault/recent' },
    virtual: { label: 'Виртуальный счёт', url: '/api/virtual-account/state' },
    reports: { label: 'Система отчётов', url: '/api/ai-control-center/daily-report' }
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
          : key === 'account'
            ? [data.positions, data.snapshot?.positions, data.orders]
            : [];
    const found = candidates.find(Array.isArray);
    return found ? found.length : null;
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
    const error = state.errors[key];
    const ok = Boolean(result) && !error;
    const count = result ? itemCount(key, result.data) : null;
    return `<article class="status-service ${ok ? 'ok' : 'bad'}">
      <div class="status-service-head">
        <span class="status-dot"></span>
        <div><b>${esc(meta.label)}</b><small>${esc(meta.url)}</small></div>
        <strong>${ok ? 'ДОСТУПЕН' : 'НЕДОСТУПЕН'}</strong>
      </div>
      <div class="status-service-body">
        <span>Задержка: <b>${ok ? `${result.latencyMs} мс` : '—'}</b></span>
        <span>Записей: <b>${count == null ? '—' : count}</b></span>
        <span>Ошибка: <b>${error ? esc(error) : 'нет'}</b></span>
      </div>
    </article>`;
  }

  function render() {
    const content = $('content');
    if (!content) return;
    const keys = Object.keys(checks);
    const available = keys.filter((key) => state.results[key] && !state.errors[key]).length;
    const ai = verifiedAi(state.results.bots?.data);
    const market = state.results.market?.data || {};
    const accountOk = Boolean(state.results.account && !state.errors.account);
    const overall = available === keys.length ? 'ВСЕ СИСТЕМЫ ДОСТУПНЫ' : available > 0 ? 'ЧАСТЬ СИСТЕМ НЕДОСТУПНА' : 'СИСТЕМА НЕ ОТВЕЧАЕТ';
    const tone = available === keys.length ? 'positive' : 'negative';

    content.innerHTML = `<div class="title"><h1>Состояние системы</h1><p>Единая проверка сервисов SharipovAI без выдуманных статусов</p></div>
      <section class="metrics">
        <article class="card"><span>Общее состояние</span><strong class="${tone}">${overall}</strong><small>${available}/${keys.length} источников отвечают</small></article>
        <article class="card"><span>ИИ с подтверждением</span><strong>${ai.verified}/${ai.total}</strong><small>Свежий сигнал до 90 секунд</small></article>
        <article class="card"><span>Bybit</span><strong class="${accountOk ? 'positive' : 'negative'}">${accountOk ? 'ПОДКЛЮЧЁН' : 'НЕ ПОДТВЕРЖДЁН'}</strong><small>Личный API</small></article>
        <article class="card"><span>Поток рынка</span><strong>${esc(market.status || market.state || (state.results.market ? 'ОТВЕЧАЕТ' : '—'))}</strong><small>Публичный WebSocket</small></article>
        <article class="card"><span>Последняя проверка</span><strong>${esc(state.loadedAt ? new Date(state.loadedAt).toLocaleTimeString('ru-RU') : '—')}</strong><small>Локальное время</small></article>
      </section>
      <div class="status-actions"><button id="statusRefresh" class="action">Проверить сейчас</button><span>Проверено: ${esc(state.loadedAt ? nowText() : 'ещё не проверено')}</span></div>
      <section class="status-grid">${keys.map(serviceCard).join('')}</section>
      <article class="panel wide"><small>ПРАВИЛО ДОСТОВЕРНОСТИ</small><h2>Как читать статусы</h2><p>«Доступен» означает только успешный ответ конкретного API в этой проверке. Это не доказывает прибыльность, качество решения или выполнение торговли. При отсутствии ответа система показывает «Недоступен», а не продолжает изображать работу.</p></article>`;
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
