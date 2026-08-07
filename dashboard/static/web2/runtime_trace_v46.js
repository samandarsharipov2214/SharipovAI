(() => {
  'use strict';

  const TARGET_PAGES = new Set(['overview', 'bots', 'trades']);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const activePage = () => window.SharipovAIPageCoordinator?.activePage?.()
    || document.querySelector('#nav button.active[data-page]')?.dataset.page
    || 'overview';
  const value = (item, fallback = '—') => item === null || item === undefined || item === '' ? fallback : item;
  const ms = (item) => Number.isFinite(Number(item)) ? `${Math.max(0, Number(item)).toLocaleString('ru-RU')} ms` : '—';
  const number = (item, digits = 2) => Number.isFinite(Number(item)) ? Number(item).toLocaleString('ru-RU', { maximumFractionDigits: digits }) : '—';
  const tone = (status) => {
    const value = String(status || '').toUpperCase();
    if (value === 'BUY' || value === 'SELL') return 'positive';
    if (value === 'BLOCK') return 'negative';
    return '';
  };

  async function truth() {
    const response = await fetch('/api/system/runtime-truth', { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function traces(payload) {
    const rows = payload?.paper?.state?.decision_traces;
    return Array.isArray(rows) ? rows : [];
  }

  function voteText(trace) {
    const votes = trace.vote_counts || {};
    return `BUY ${Number(votes.BUY || 0)} · SELL ${Number(votes.SELL || 0)} · WAIT ${Number(votes.WAIT || 0)} · BLOCK ${Number(votes.BLOCK || 0)}`;
  }

  function traceCard(trace) {
    const status = String(trace.status || 'WAIT').toUpperCase();
    const risk = Array.isArray(trace.risk_blocks) ? trace.risk_blocks : [];
    const news = Array.isArray(trace.news_actions) ? trace.news_actions : [];
    const confidence = trace.decision_quality_confidence;
    const agreement = trace.decision_quality_agreement;
    return `<article class="panel runtime-trace-card">
      <div class="section-head"><div><small>CANONICAL DECISION TRACE</small><h3>${esc(trace.symbol || '—')}</h3></div><strong class="${tone(status)}">${esc(status)}</strong></div>
      <p class="v10-explanation">${esc(value(trace.reason, 'Причина ещё не записана.'))}</p>
      <div class="v10-row"><span>Фаза</span><b>${esc(value(trace.phase))}</b></div>
      <div class="v10-row"><span>Market verified</span><b>${trace.market_verified === true ? 'YES' : trace.market_verified === false ? 'NO' : '—'}</b></div>
      <div class="v10-row"><span>Consensus</span><b>${esc(value(trace.consensus_source_count))}/${esc(value(trace.required_consensus_source_count))}</b></div>
      <div class="v10-row"><span>Возраст котировки</span><b>${esc(ms(trace.quote_age_ms))} / ${esc(ms(trace.quote_max_age_ms))}</b></div>
      <div class="v10-row"><span>24h / порог</span><b>${esc(number(trace.change_24h_percent, 4))}% / ±${esc(number(trace.entry_change_percent, 4))}%</b></div>
      <div class="v10-row"><span>Turnover / минимум</span><b>${esc(number(trace.turnover_usdt, 2))} / ${esc(number(trace.min_turnover_usdt, 2))} USDT</b></div>
      <div class="v10-row"><span>Голоса</span><b>${esc(voteText(trace))}</b></div>
      <div class="v10-row"><span>News</span><b>${esc(news.length ? news.join(' · ') : '—')}</b></div>
      <div class="v10-row"><span>Risk blockers</span><b class="${risk.length ? 'negative' : 'positive'}">${esc(risk.length ? risk.join('; ') : 'нет')}</b></div>
      <div class="v10-row"><span>Decision Quality</span><b>${confidence == null ? '—' : `${esc(number(confidence, 2))}%`} · agreement ${agreement == null ? '—' : esc(number(agreement, 4))}</b></div>
      <div class="v10-row"><span>Candidate validation</span><b>${trace.candidate_validation_valid === true ? 'VALID' : trace.candidate_validation_valid === false ? 'INVALID' : '—'}</b></div>
      <small>${trace.updated_at_ms ? esc(new Date(Number(trace.updated_at_ms)).toLocaleString('ru-RU')) : '—'} · ${esc(value(trace.decision_id))}</small>
    </article>`;
  }

  function inject(payload) {
    const page = activePage();
    if (!TARGET_PAGES.has(page)) return;
    const content = document.getElementById('content');
    if (!content) return;
    document.getElementById('canonicalRuntimeTracePanel')?.remove();
    const section = document.createElement('section');
    section.id = 'canonicalRuntimeTracePanel';
    section.className = 'v10-grid runtime-trace-grid';
    const rows = traces(payload);
    section.innerHTML = `<article class="panel wide"><small>OPERATOR TRANSPARENCY</small><h2>Почему ИИ сейчас BUY / SELL / WAIT / BLOCK</h2><p>Последний безопасный decision trace по каждой паре. Этот блок только читает канонический runtime и не меняет торговые решения.</p></article>${rows.length ? rows.slice(0, 6).map(traceCard).join('') : '<article class="panel wide"><div class="empty">Decision trace ещё не сформирован. После следующего paper tick здесь появится точная причина.</div></article>'}`;
    const title = content.querySelector('.title');
    if (title?.nextSibling) content.insertBefore(section, title.nextSibling);
    else content.prepend(section);
  }

  async function refresh() {
    if (!TARGET_PAGES.has(activePage()) || document.hidden) return;
    try { inject(await truth()); } catch (_) { /* existing page owns error presentation */ }
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('#nav button[data-page]');
    if (button && TARGET_PAGES.has(button.dataset.page)) setTimeout(refresh, 120);
  });
  document.getElementById('refresh')?.addEventListener('click', () => setTimeout(refresh, 120));
  window.addEventListener('DOMContentLoaded', () => setTimeout(refresh, 180));
  setInterval(refresh, 10000);
})();
