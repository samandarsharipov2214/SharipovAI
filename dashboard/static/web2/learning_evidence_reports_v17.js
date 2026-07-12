(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const asArray = (value) => Array.isArray(value) ? value : [];
  const firstArray = (...values) => values.find(Array.isArray) || [];
  const num = (value, digits = 2) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toLocaleString('ru-RU', { maximumFractionDigits: digits }) : '—';
  };
  const dateText = (value) => {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? esc(value) : date.toLocaleString('ru-RU');
  };
  const title = (heading, text) => `<div class="title"><h1>${esc(heading)}</h1><p>${esc(text)}</p></div>`;
  const card = (label, value, note = '', cls = '') => `<article class="card"><span>${esc(label)}</span><strong class="${esc(cls)}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
  const panel = (heading, body, cls = '') => `<article class="panel ${esc(cls)}"><small>SHARIPOVAI</small><h2>${esc(heading)}</h2>${body}</article>`;
  const empty = (text) => `<div class="empty">${esc(text)}</div>`;
  const badge = (text, tone = 'neutral') => `<span class="v17-badge ${esc(tone)}">${esc(text)}</span>`;
  const row = (label, value, tone = '') => `<div class="v17-row"><span>${esc(label)}</span><b class="${esc(tone)}">${esc(value)}</b></div>`;

  const endpoints = {
    learning: '/api/learning-os/status',
    evidence: '/api/evidence-vault/recent',
    report: '/api/ai-control-center/daily-report',
    run: '/api/run',
    account: '/api/exchange/account/snapshot',
    bots: '/api/ai-bots'
  };

  const state = { learning: null, evidence: null, report: null, run: null, account: null, bots: null, errors: {}, loadedAt: null };

  function learningItems() {
    return firstArray(state.learning?.insights, state.learning?.recommendations, state.learning?.lessons, state.learning?.items);
  }

  function evidenceItems() {
    return firstArray(state.evidence?.items, state.evidence?.records, state.evidence?.events, state.evidence);
  }

  function reportHistory() {
    return firstArray(state.report?.periods, state.report?.reports, state.report?.history);
  }

  function learningPage() {
    const data = state.learning || {};
    const stats = data.summary || data.stats || {};
    const items = learningItems();
    const proven = items.filter((item) => item.evidence_id || item.evidence || item.source_id).length;
    const lessons = items.length ? items.map((item) => {
      const status = item.status || item.priority || 'наблюдение';
      const tone = String(status).toLowerCase().match(/ошиб|high|critical/) ? 'bad' : String(status).toLowerCase().match(/готов|done|success/) ? 'good' : 'neutral';
      return `<article class="v17-lesson"><header>${badge(status, tone)}<small>${dateText(item.created_at || item.updated_at || item.timestamp)}</small></header><h3>${esc(item.title || item.lesson || item.pattern || 'Вывод обучения')}</h3><p>${esc(item.description || item.recommendation || item.reason || item.details || 'Описание не передано.')}</p><div class="v17-lesson-meta">${row('Источник', item.source || item.module || item.agent || 'не указан')}${row('Доказательство', item.evidence_id || item.evidence || item.source_id || 'отсутствует', (item.evidence_id || item.evidence || item.source_id) ? 'positive' : 'negative')}${row('Следующее действие', item.next_action || item.action || 'не указано')}</div></article>`;
    }).join('') : empty('Подтверждённые выводы обучения не получены.');

    return title('Центр обучения', 'Ошибки, закономерности, улучшения и доказательства обучения') +
      `<section class="metrics">
        ${card('Наблюдения', String(stats.observations ?? data.count ?? items.length), 'Получено из API')}
        ${card('Проанализировано сделок', String(stats.total_trades ?? data.total_trades ?? '—'), 'Фактические данные')}
        ${card('Успешность', stats.win_rate != null ? `${num(stats.win_rate)}%` : data.win_rate != null ? `${num(data.win_rate)}%` : '—', 'Только измеренное значение')}
        ${card('С доказательством', `${proven}/${items.length}`, 'Подтверждённые выводы', proven ? 'positive' : '')}
      </section>
      <section class="v17-toolbar"><button id="v17LearningRefresh" class="action">Обновить обучение</button><span>Загружено: ${dateText(state.loadedAt)}</span></section>
      <section class="v17-lesson-grid">${lessons}</section>`;
  }

  function evidencePage() {
    const items = evidenceItems();
    const verified = items.filter((item) => item.evidence_id || item.id || item.hash).length;
    const decisions = items.filter((item) => String(item.type || item.event || item.action || '').toLowerCase().match(/decision|решен|consensus/)).length;
    const results = items.filter((item) => item.result || item.outcome || item.status).length;
    const rows = items.length ? `<table class="v17-table"><thead><tr><th>Время</th><th>Событие</th><th>Источник</th><th>Доказательство</th><th>Результат</th></tr></thead><tbody>${items.slice(0, 250).map((item) => `<tr><td>${dateText(item.time || item.created_at || item.timestamp)}</td><td>${esc(item.event || item.action || item.title || item.type || '—')}</td><td>${esc(item.source || item.agent || item.module || '—')}</td><td>${esc(item.evidence_id || item.id || item.hash || '—')}</td><td>${esc(item.result || item.outcome || item.status || '—')}</td></tr>`).join('')}</tbody></table>` : empty('Хранилище доказательств не вернуло записи.');

    return title('Хранилище доказательств', 'Полная цепочка: данные → ИИ → решение → действие → результат') +
      `<section class="metrics">
        ${card('Всего записей', String(items.length), 'Последний пакет')}
        ${card('С идентификатором', String(verified), 'Проверяемые записи', verified ? 'positive' : '')}
        ${card('Решения', String(decisions), 'Связанные с решениями')}
        ${card('С результатом', String(results), 'Есть итог выполнения')}
      </section>
      <section class="v17-toolbar"><input id="v17EvidenceSearch" type="search" placeholder="Поиск по событию, ИИ или доказательству"><button id="v17EvidenceRefresh" class="action">Обновить</button></section>
      ${panel('Журнал доказательств', `<div id="v17EvidenceTable">${rows}</div>`, 'wide')}`;
  }

  function reportsPage() {
    const report = state.report || {};
    const run = state.run || {};
    const learning = state.learning || {};
    const bots = firstArray(state.bots?.bots, state.bots?.items, state.bots?.agents, state.bots);
    const periods = reportHistory();
    const body = periods.length ? periods.map((period) => `<article class="v17-report"><header><b>${esc(period.period || period.title || 'Период')}</b><small>${dateText(period.generated_at || period.created_at || period.timestamp)}</small></header><p>${esc(period.summary || period.result || period.report || period.status || 'Сводка не передана.')}</p><div>${row('Сделки', period.total_trades ?? period.trades ?? '—')}${row('Успешные', period.wins ?? period.successful_trades ?? '—')}${row('PnL', period.pnl != null ? `${num(period.pnl, 8)} USDT` : '—')}${row('Просадка', period.drawdown_percent != null ? `${num(period.drawdown_percent)}%` : '—')}</div></article>`).join('') : empty('Исторические отчёты API пока не передал.');

    return title('Отчёты', 'Дневная, недельная и месячная эффективность SharipovAI') +
      `<section class="metrics">
        ${card('Последнее решение', report.decision || run.decision || '—', 'Финальный результат')}
        ${card('Фактический рост', report.actual_growth_percent != null ? `${num(report.actual_growth_percent)}%` : '—', 'Без прогнозных цифр')}
        ${card('ИИ в отчёте', String(report.total_bots ?? bots.length), 'Модулей')}
        ${card('Уроков', String(learning.count ?? learningItems().length), 'Центр обучения')}
      </section>
      <section class="v17-grid">
        ${panel('Текущая сводка', `<p class="v17-summary">${esc(report.report || report.reason || run.reason || 'Текст отчёта пока не сформирован.')}</p>${row('Статус цели', report.goal_status || '—')}${row('Следующее действие', report.next_action || '—')}${row('Сформировано', dateText(report.generated_at || report.updated_at))}`, 'wide')}
        ${panel('История отчётов', body, 'wide')}
      </section>`;
  }

  const renderers = { learning: learningPage, evidence: evidencePage, reports: reportsPage };

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

  function render(page) {
    const content = $('content');
    if (!content || !renderers[page]) return;
    content.innerHTML = renderers[page]();
    bind(page);
  }

  function bind(page) {
    if (page === 'learning') $('v17LearningRefresh')?.addEventListener('click', load);
    if (page === 'evidence') {
      $('v17EvidenceRefresh')?.addEventListener('click', load);
      $('v17EvidenceSearch')?.addEventListener('input', (event) => {
        const q = String(event.target.value || '').trim().toLowerCase();
        document.querySelectorAll('#v17EvidenceTable tbody tr').forEach((tr) => {
          tr.hidden = Boolean(q) && !tr.textContent.toLowerCase().includes(q);
        });
      });
    }
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
      const active = document.querySelector('#nav button.active')?.dataset.page;
      if (renderers[active]) render(active);
    }, 750);
  });
})();