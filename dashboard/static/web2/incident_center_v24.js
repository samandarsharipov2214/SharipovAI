(() => {
  'use strict';

  const OWNER = 'incident_center_v24.js';
  const state = { health: {}, recovery: {}, evidence: {}, loadedAt: null, error: '' };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const content = document.getElementById('content');
  const nav = document.getElementById('nav');
  if (!content || !nav) return;

  const text = (ru, en, uz) => document.documentElement.lang === 'en' ? en : document.documentElement.lang === 'uz' ? uz : ru;
  const firstArray = (...values) => values.find(Array.isArray) || [];

  function activePage() {
    return window.SharipovAIPageCoordinator?.activePage?.() || nav.querySelector('button.active[data-page]')?.dataset.page || 'overview';
  }

  function incidents() {
    const components = firstArray(state.health?.components);
    const rows = [];
    components.forEach((component) => {
      if (!component || component.status === 'healthy') return;
      const blockers = firstArray(component.blockers);
      if (!blockers.length) {
        rows.push({ component: component.component || 'unknown', level: component.status === 'blocked' ? 'critical' : 'warning', message: `status=${component.status}` });
        return;
      }
      blockers.forEach((message) => rows.push({
        component: component.component || 'unknown',
        level: String(message).startsWith('critical:') || component.status === 'blocked' ? 'critical' : 'warning',
        message: String(message),
      }));
    });
    return rows;
  }

  function evidenceCount() {
    return firstArray(state.evidence?.items, state.evidence?.records, state.evidence?.events).length;
  }

  function render() {
    const page = activePage();
    if (page !== 'incidents' || !window.SharipovAIPageCoordinator?.canRender?.(OWNER, page)) return;
    const rows = incidents();
    const critical = rows.filter((item) => item.level === 'critical').length;
    const warnings = rows.filter((item) => item.level !== 'critical').length;
    const actions = firstArray(state.recovery?.actions);
    const list = rows.length ? rows.map((item) => `<article class="panel incident-row ${item.level === 'critical' ? 'negative' : ''}"><small>${esc(item.level === 'critical' ? text('КРИТИЧЕСКАЯ', 'CRITICAL', 'JIDDIY') : text('ПРЕДУПРЕЖДЕНИЕ', 'WARNING', 'OGOHLANTIRISH'))}</small><h2>${esc(item.component)}</h2><p>${esc(item.message)}</p></article>`).join('') : `<article class="panel wide"><small>SHARIPOVAI</small><h2>${esc(text('Активных ошибок не найдено', 'No active incidents found', 'Faol xatolar topilmadi'))}</h2><p>${esc(text('Это означает только отсутствие проблем в последнем ответе системного API.', 'This only means the latest system API response reported no issues.', 'Bu faqat oxirgi tizim API javobida muammo yo‘qligini bildiradi.'))}</p></article>`;
    const recovery = actions.length ? actions.map((item) => `<div class="activity-item"><div><b>${esc(item.component || 'system')}</b><p>${esc(item.action || '—')}</p><small>${esc(item.automatic === true ? text('автоматическое', 'automatic', 'avtomatik') : text('только вручную', 'manual only', 'faqat qo‘lda'))}</small></div></div>`).join('') : `<div class="empty">${esc(text('План восстановления не содержит действий', 'Recovery plan has no actions', 'Tiklash rejasida amallar yo‘q'))}</div>`;

    content.innerHTML = `<div class="title"><h1>${esc(text('Центр ошибок', 'Incident center', 'Xatolar markazi'))}</h1><p>${esc(text('Подтверждённые проблемы, причины и безопасный план восстановления', 'Verified problems, causes and safe recovery plan', 'Tasdiqlangan muammolar, sabablar va xavfsiz tiklash rejasi'))}</p></div>
      <section class="metrics">
        <article class="card"><span>${esc(text('Критические', 'Critical', 'Jiddiy'))}</span><strong class="${critical ? 'negative' : 'positive'}">${critical}</strong><small>${esc(text('Требуют внимания', 'Require attention', 'E’tibor talab qiladi'))}</small></article>
        <article class="card"><span>${esc(text('Предупреждения', 'Warnings', 'Ogohlantirishlar'))}</span><strong>${warnings}</strong><small>${esc(text('Деградации', 'Degradations', 'Pasayishlar'))}</small></article>
        <article class="card"><span>${esc(text('Безопасный режим', 'Safe mode', 'Xavfsiz rejim'))}</span><strong>${state.health?.safe_mode === true ? text('ВКЛЮЧЁН', 'ON', 'YOQILGAN') : text('НЕ АКТИВИРОВАН', 'NOT ACTIVE', 'FAOL EMAS')}</strong><small>${esc(text('По данным API', 'According to API', 'API ma’lumotiga ko‘ra'))}</small></article>
        <article class="card"><span>${esc(text('Доказательства', 'Evidence', 'Dalillar'))}</span><strong>${evidenceCount()}</strong><small>${esc(text('Записей получено', 'Records received', 'Yozuv olindi'))}</small></article>
      </section>
      <section class="grid">${list}</section>
      <article class="panel wide"><small>${esc(text('ПЛАН ВОССТАНОВЛЕНИЯ', 'RECOVERY PLAN', 'TIKLASH REJASI'))}</small><h2>${esc(text('Только безопасные ручные действия', 'Safe manual actions only', 'Faqat xavfsiz qo‘lda amallar'))}</h2>${recovery}</article>
      ${state.error ? `<div class="notice">${esc(state.error)}</div>` : ''}`;
  }

  async function getJson(url) {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return response.json();
  }

  async function load() {
    state.error = '';
    const [health, recovery, evidence] = await Promise.allSettled([
      getJson('/api/system/health'), getJson('/api/system/recovery-plan'), getJson('/api/evidence-vault/recent')
    ]);
    if (health.status === 'fulfilled') state.health = health.value; else state.error = health.reason?.message || 'health unavailable';
    if (recovery.status === 'fulfilled') state.recovery = recovery.value;
    if (evidence.status === 'fulfilled') state.evidence = evidence.value;
    state.loadedAt = new Date().toISOString();
    render();
  }

  function install() {
    if (!nav.querySelector('[data-page="incidents"]')) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.page = 'incidents';
      button.textContent = text('Центр ошибок', 'Incident center', 'Xatolar markazi');
      nav.appendChild(button);
    }
    nav.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-page="incidents"]');
      if (button) setTimeout(() => load().catch(() => render()), 0);
    });
    window.addEventListener('sharipovai:refresh', () => {
      if (activePage() === 'incidents') load().catch(() => render());
    });
    window.addEventListener('sharipovai:language', () => {
      nav.querySelector('[data-page="incidents"]')?.replaceChildren(document.createTextNode(text('Центр ошибок', 'Incident center', 'Xatolar markazi')));
      render();
    });
    if (location.hash === '#incidents') setTimeout(() => nav.querySelector('[data-page="incidents"]')?.click(), 0);
  }

  window.addEventListener('DOMContentLoaded', install, { once: true });
})();
