(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  const state = { health: null, recovery: null, loadedAt: null, error: '' };
  const labels = {
    database: 'База данных', ai_organs: 'ИИ-модули', market: 'Рынок', news: 'Новости',
    telegram: 'Telegram', security: 'Безопасность', storage: 'Диск', backup: 'Резервные копии'
  };

  async function request(url) {
    const started = performance.now();
    const response = await fetch(url, { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return { data: await response.json(), latency: Math.round(performance.now() - started) };
  }

  function statusText(status) {
    return status === 'healthy' ? 'НОРМА' : status === 'degraded' ? 'ТРЕБУЕТ ВНИМАНИЯ' : 'ЗАБЛОКИРОВАНО';
  }

  function componentCard(component) {
    const evidence = Array.isArray(component.evidence) ? component.evidence : [];
    const blockers = Array.isArray(component.blockers) ? component.blockers : [];
    const recovery = Array.isArray(component.recovery) ? component.recovery : [];
    return `<article class="ops-component ${esc(component.status || 'blocked')}">
      <header><div><small>${esc(component.component || 'unknown')}</small><h3>${esc(labels[component.component] || component.component || 'Компонент')}</h3></div><strong>${statusText(component.status)}</strong></header>
      <div class="ops-columns">
        <section><b>Подтверждения</b>${evidence.length ? `<ul>${evidence.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '<p>Нет подтверждений.</p>'}</section>
        <section><b>Проблемы</b>${blockers.length ? `<ul>${blockers.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '<p>Проблемы не обнаружены.</p>'}</section>
        <section><b>Рекомендации</b>${recovery.length ? `<ul>${recovery.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '<p>Действия не требуются.</p>'}</section>
      </div>
    </article>`;
  }

  function render() {
    const out = $('content');
    if (!out) return;
    if (state.error) {
      out.innerHTML = `<div class="title"><h1>Центр эксплуатации</h1><p>Диагностика VPS и сервисов</p></div><article class="panel wide"><h2>Диагностика недоступна</h2><p>${esc(state.error)}</p><button id="opsRefresh" class="action">Повторить</button></article>`;
      $('opsRefresh')?.addEventListener('click', load);
      return;
    }
    const health = state.health || {};
    const components = Array.isArray(health.components) ? health.components : [];
    const counts = health.counts || {};
    const actions = Array.isArray(state.recovery?.actions) ? state.recovery.actions : [];
    const checked = health.checked_at_ms ? new Date(health.checked_at_ms).toLocaleString('ru-RU') : '—';
    out.innerHTML = `<div class="title"><h1>Центр эксплуатации</h1><p>VPS, база данных, безопасность, резервные копии и восстановление</p></div>
      <section class="ops-metrics">
        <article><span>Общее состояние</span><strong class="${esc(health.status || 'blocked')}">${statusText(health.status)}</strong><small>Проверено: ${esc(checked)}</small></article>
        <article><span>В норме</span><strong>${Number(counts.healthy || 0)}</strong><small>Подтверждённые компоненты</small></article>
        <article><span>Предупреждения</span><strong>${Number(counts.degraded || 0)}</strong><small>Нужна проверка</small></article>
        <article><span>Блокировки</span><strong>${Number(counts.blocked || 0)}</strong><small>Критические проблемы</small></article>
        <article><span>Безопасный режим</span><strong>${health.safe_mode ? 'ВКЛЮЧЁН' : 'НЕ ТРЕБУЕТСЯ'}</strong><small>Автовосстановление торговли запрещено</small></article>
      </section>
      <div class="ops-toolbar"><button id="opsRefresh" class="action">Проверить сейчас</button><span>Последнее обновление: ${esc(state.loadedAt ? new Date(state.loadedAt).toLocaleTimeString('ru-RU') : '—')}</span></div>
      <section class="ops-list">${components.map(componentCard).join('') || '<article class="panel wide"><p>Компоненты не переданы API.</p></article>'}</section>
      <article class="panel wide ops-plan"><small>ПЛАН ВОССТАНОВЛЕНИЯ</small><h2>Только ручные и безопасные действия</h2>${actions.length ? `<ol>${actions.map((item) => `<li><b>${esc(labels[item.component] || item.component)}</b>: ${esc(item.action)} <span>${item.automatic ? 'автоматически' : 'вручную'}</span></li>`).join('')}</ol>` : '<p>Действия не требуются.</p>'}<p>Центр эксплуатации ничего не перезапускает, не меняет настройки биржи и не включает реальные сделки.</p></article>`;
    $('opsRefresh')?.addEventListener('click', load);
  }

  async function load() {
    const button = $('opsRefresh');
    if (button) { button.disabled = true; button.textContent = 'Проверяю…'; }
    state.error = '';
    try {
      const [health, recovery] = await Promise.all([
        request('/api/system/health'),
        request('/api/system/recovery-plan')
      ]);
      state.health = health.data;
      state.recovery = recovery.data;
      state.loadedAt = new Date().toISOString();
    } catch (error) {
      state.error = `API центра эксплуатации не ответил: ${error?.message || 'неизвестная ошибка'}`;
    }
    render();
  }

  function install() {
    const nav = $('nav');
    if (!nav || nav.querySelector('[data-page="operations"]')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.page = 'operations';
    button.textContent = 'Эксплуатация';
    const settings = nav.querySelector('[data-page="settings"]');
    nav.insertBefore(button, settings || null);
    button.addEventListener('click', () => {
      nav.querySelectorAll('button[data-page]').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      history.replaceState(null, '', '#operations');
      render();
      load();
    });
    if (location.hash === '#operations') button.click();
  }

  window.addEventListener('DOMContentLoaded', install);
})();