(() => {
  'use strict';
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const content = () => document.getElementById('content');
  const settings = () => { try { return JSON.parse(localStorage.getItem('sharipovai-settings') || '{}'); } catch { return {}; } };
  const state = { items: [], filter: 'all', search: '', loading: false, error: '' };
  const firstArray = (...values) => values.find(Array.isArray) || [];
  const dateText = (v) => { if (!v) return '—'; const d = new Date(v); return Number.isNaN(d.getTime()) ? esc(v) : d.toLocaleString('ru-RU'); };
  const tone = (v) => { const x = String(v || '').toLowerCase(); return x.includes('neg') || x.includes('bear') || x.includes('пад') ? 'bad' : x.includes('pos') || x.includes('bull') || x.includes('рост') ? 'good' : 'neutral'; };
  const category = (item) => String(item.category || item.topic || item.section || 'другое').toLowerCase();
  const credibility = (item) => Number(item.credibility_percent ?? item.credibility ?? item.source_score);
  const assets = (item) => firstArray(item.assets, item.symbols, item.related_assets).map(String);
  const published = (item) => item.published_at || item.pubDate || item.checked_at || item.created_at;

  async function loadNews() {
    state.loading = true; state.error = ''; render();
    try {
      const response = await fetch('/api/social-news', { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      state.items = firstArray(data?.news?.items, data?.news, data?.items, data?.articles, data);
    } catch (error) {
      state.error = error?.message || 'Источник недоступен';
      state.items = [];
    } finally {
      state.loading = false; render();
    }
  }

  function filtered() {
    const cfg = settings();
    return state.items.filter((item) => {
      const text = `${item.title || item.headline || ''} ${item.summary || item.description || ''} ${assets(item).join(' ')}`.toLowerCase();
      if (state.search && !text.includes(state.search.toLowerCase())) return false;
      if (state.filter !== 'all' && !category(item).includes(state.filter)) return false;
      if (cfg.verifiedNewsOnly !== false && !(item.verified === true || Number.isFinite(credibility(item)) && credibility(item) >= 60)) return false;
      if (cfg.importantNewsOnly && !['high','critical','высок'].some(x => String(item.importance || item.priority || '').toLowerCase().includes(x))) return false;
      return true;
    });
  }

  function render() {
    const box = content();
    if (!box || document.querySelector('#nav button.active')?.dataset.page !== 'news') return;
    const rows = filtered();
    const sources = new Set(rows.map(x => x.source_name || x.source || x.publisher).filter(Boolean));
    const important = rows.filter(x => ['high','critical','высок'].some(k => String(x.importance || x.priority || '').toLowerCase().includes(k))).length;
    box.innerHTML = `<div class="title"><h1>Новости</h1><p>Проверенные заголовки, изображения источников и влияние на активы</p></div>
      <section class="metrics"><article class="card"><span>Получено</span><strong>${rows.length}</strong><small>После фильтров</small></article><article class="card"><span>Источники</span><strong>${sources.size}</strong><small>Уникальные</small></article><article class="card"><span>Важные</span><strong>${important}</strong><small>Высокий приоритет</small></article><article class="card"><span>Статус</span><strong class="${state.error ? 'negative' : 'positive'}">${state.error ? 'ОШИБКА' : 'ДАННЫЕ ПОЛУЧЕНЫ'}</strong><small>${esc(state.error || 'Без выдуманных новостей')}</small></article></section>
      <div class="news-v12-toolbar"><input id="newsSearch" placeholder="Поиск по заголовкам и активам" value="${esc(state.search)}"><select id="newsFilter"><option value="all">Все категории</option><option value="крип">Криптовалюты</option><option value="акц">Акции</option><option value="эконом">Экономика</option><option value="технолог">Технологии</option><option value="геополит">Геополитика</option></select><button id="newsReload" class="action">Обновить новости</button></div>
      ${state.loading ? '<div class="empty">Новости загружаются…</div>' : state.error ? `<div class="empty">Не удалось получить новости: ${esc(state.error)}</div>` : rows.length ? `<section class="news-v12-grid">${rows.map(cardHtml).join('')}</section>` : '<div class="empty">Подтверждённые новости по выбранным фильтрам не найдены.</div>'}`;
    const filter = document.getElementById('newsFilter'); if (filter) filter.value = state.filter;
    document.getElementById('newsSearch')?.addEventListener('input', e => { state.search = e.target.value; render(); });
    filter?.addEventListener('change', e => { state.filter = e.target.value; render(); });
    document.getElementById('newsReload')?.addEventListener('click', loadNews);
  }

  function cardHtml(item) {
    const image = item.image_url || item.image || item.thumbnail || item.og_image;
    const source = item.source_name || item.source || item.publisher || 'Источник не указан';
    const url = item.url || item.link || item.source_url;
    const impact = item.impact || item.sentiment || 'не оценено';
    const related = assets(item);
    const cfg = settings();
    return `<article class="news-v12-card">${image && cfg.newsImages !== false ? `<img src="${esc(image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : '<div class="news-v12-noimage">Изображение источником не предоставлено</div>'}<div class="news-v12-body"><div class="news-v12-meta"><span>${esc(item.category || 'новость')}</span><span class="${tone(impact)}">${esc(impact)}</span></div><h3>${esc(item.title || item.headline || 'Без заголовка')}</h3><p>${esc(item.summary || item.description || item.excerpt || 'Краткое описание отсутствует.')}</p><dl><div><dt>Источник</dt><dd>${esc(source)}</dd></div><div><dt>Опубликовано</dt><dd>${dateText(published(item))}</dd></div><div><dt>Доверие</dt><dd>${Number.isFinite(credibility(item)) ? `${credibility(item).toFixed(0)}%` : 'не измерено'}</dd></div><div><dt>Активы</dt><dd>${related.length ? esc(related.join(', ')) : 'не указаны'}</dd></div></dl>${item.analysis || item.ai_analysis || item.reason ? `<div class="news-v12-ai"><b>Анализ новостного ИИ</b><p>${esc(item.analysis || item.ai_analysis || item.reason)}</p></div>` : ''}<div class="news-v12-actions">${related[0] ? `<button class="action" data-open-market="${esc(related[0])}">Открыть на графике</button>` : ''}${url ? `<a class="action" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Открыть источник</a>` : ''}</div></div></article>`;
  }

  document.addEventListener('click', (event) => {
    const marketButton = event.target.closest('[data-open-market]');
    if (marketButton) {
      localStorage.setItem('sharipovai-market-symbol', String(marketButton.dataset.openMarket).replace(/[^A-Za-z0-9]/g, '').toUpperCase());
      document.querySelector('#nav button[data-page="market"]')?.click();
      return;
    }
    const navButton = event.target.closest('#nav button[data-page="news"]');
    if (navButton) setTimeout(() => { render(); if (!state.items.length && !state.loading) loadNews(); }, 80);
  }, true);

  window.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('#nav button.active')?.dataset.page === 'news') loadNews();
  });
})();