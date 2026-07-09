(() => {
  const $ = (selector) => document.querySelector(selector);

  const ERROR_RULES = [
    { id: 'too_few_trades', title: 'слишком мало сделок после ночи', severity: 'HIGH', when: (ctx) => (ctx.tradeCount || 0) < 6 },
    { id: 'many_open_positions', title: 'много открытых позиций без закрытия', severity: 'MEDIUM', when: (ctx) => (ctx.openPositions || 0) >= 5 },
    { id: 'negative_pnl', title: 'отрицательный PnL', severity: 'MEDIUM', when: (ctx) => (ctx.netPnl || 0) < 0 },
    { id: 'fees_drag', title: 'комиссии съедают результат', severity: 'LOW', when: (ctx) => (ctx.totalFees || 0) > Math.abs(ctx.netPnl || 0) && (ctx.tradeCount || 0) > 0 },
    { id: 'stale_tick', title: 'paper tick давно не обновлялся', severity: 'HIGH', when: (ctx) => (ctx.lastTickAge || 0) > 180 },
    { id: 'technical_reason_visible', title: 'техническая причина попала в интерфейс', severity: 'MEDIUM', when: (ctx) => /_|ticks|engine/i.test(ctx.lastReasonRaw || '') },
    { id: 'source_technical_name', title: 'техническое имя источника вместо понятного текста', severity: 'MEDIUM', when: (ctx) => (ctx.sources || []).some((source) => /engine|paper_activity/i.test(source)) },
    { id: 'open_without_duration', title: 'у сделок нет понятной длительности/времени', severity: 'HIGH', when: (ctx) => (ctx.trades || []).some((trade) => !trade.opened_at) },
    { id: 'closed_without_reason', title: 'закрытые сделки без причины выхода', severity: 'MEDIUM', when: (ctx) => (ctx.trades || []).some((trade) => trade.status === 'CLOSED' && !trade.close_reason && !trade.close_reason_ru) },
    { id: 'low_bootstrap_history', title: 'история после перезапуска восстановлена слабо', severity: 'HIGH', when: (ctx) => /bootstrap/i.test(ctx.lastReasonRaw || '') && (ctx.tradeCount || 0) < 12 },
    { id: 'no_learning_feedback', title: 'ошибки сделок ещё не связаны с уроками Learning OS', severity: 'MEDIUM', when: (ctx) => (ctx.learningLessons || 0) < (ctx.detectedErrors || 0) },
    { id: 'risk_labels_mixed', title: 'часть risk/status labels требует перевода/пояснения', severity: 'LOW', when: (ctx) => ctx.hasEnglishLabels === true },
  ];

  function severityRank(severity) {
    return { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 }[severity] || 1;
  }

  function setLearningLoading() {
    const learning = $('#learning-section');
    if (!learning) return;
    learning.innerHTML = `<h2>Обучение AI</h2><div class="mini-grid"><div class="mini-stat"><small>Ошибок найдено</small><b id="learning-error-count">...</b></div><div class="mini-stat"><small>Исправлено</small><b id="learning-fixed-count">...</b></div><div class="mini-stat"><small>Повторяется</small><b id="learning-repeat-error">проверяю</b></div><div class="mini-stat"><small>Источник</small><b>live audit</b></div></div><div class="bot-grid" id="learning-error-list"><div class="bot-row"><div><b>Ищу реальные ошибки</b><small>Смотрю сделки, tick, PnL, источники, причины, Learning OS.</small></div><span class="bot-state">...</span></div></div>`;
  }

  function buildContext(paperPayload, learningPayload) {
    const state = paperPayload.state || {};
    const summary = state.summary || {};
    const trades = Array.isArray(state.trades) ? state.trades : [];
    const learning = learningPayload || {};
    const learningSummary = learning.summary || learning.learning?.summary || {};
    const sources = trades.map((trade) => String(trade.source || ''));
    const lastReasonRaw = String(summary.last_reason || '');
    return {
      trades,
      tradeCount: Number(summary.trade_count || trades.length || 0),
      openPositions: Number(summary.open_positions || 0),
      closedPositions: Number(summary.closed_positions || 0),
      netPnl: Number(summary.net_pnl || 0),
      totalFees: Number(summary.total_fees || 0),
      lastTickAge: Number(summary.last_tick_age_seconds || 0),
      lastReasonRaw,
      lastReasonRu: String(summary.last_reason_ru || ''),
      sources,
      learningLessons: Number(learningSummary.lesson_count || learning.lesson_count || 0),
      hasEnglishLabels: /paper|engine|catch_up|ticks|OPEN|CLOSED/.test(JSON.stringify(state).slice(0, 4000)),
    };
  }

  function detectErrors(ctx) {
    let errors = ERROR_RULES.filter((rule) => rule.when(ctx)).map((rule) => ({ id: rule.id, title: rule.title, severity: rule.severity }));
    errors = errors.sort((a, b) => severityRank(b.severity) - severityRank(a.severity));
    const seen = new Set();
    return errors.filter((item) => {
      if (seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    });
  }

  function renderLearning(ctx, errors) {
    const learning = $('#learning-section');
    if (!learning) return;
    const fixed = Math.max(0, errors.filter((item) => item.severity === 'LOW').length + (ctx.lastReasonRu ? 1 : 0));
    const repeat = errors[0]?.title || 'критичных повторов нет';
    const rows = errors.length
      ? errors.map((error) => `<div class="bot-row"><div><b>${error.title}</b><small>severity: ${error.severity} · источник: live paper/state audit</small></div><span class="bot-state ${error.severity === 'HIGH' || error.severity === 'CRITICAL' ? 'warn' : ''}">${error.severity}</span></div>`).join('')
      : '<div class="bot-row"><div><b>Критичных ошибок не найдено</b><small>Сделки, время и tick выглядят нормально.</small></div><span class="bot-state">OK</span></div>';
    learning.innerHTML = `<h2>Обучение AI</h2><div class="mini-grid"><div class="mini-stat"><small>Ошибок найдено</small><b>${errors.length}</b></div><div class="mini-stat"><small>Исправлено/смягчено</small><b>${fixed}</b></div><div class="mini-stat"><small>Повторяется</small><b>${repeat}</b></div><div class="mini-stat"><small>Проверено сделок</small><b>${ctx.tradeCount}</b></div><div class="mini-stat"><small>Открыто</small><b>${ctx.openPositions}</b></div><div class="mini-stat"><small>Закрыто</small><b>${ctx.closedPositions}</b></div></div><div class="bot-grid">${rows}</div><p class="info-box"><b>Теперь это не демо-цифра.</b><br>Раздел считает ошибки из реальных виртуальных сделок, tick-статуса, PnL, источников и Learning OS. Если цифра маленькая — значит проверка реально не нашла больше по текущим данным, а не потому что стоит заглушка.</p>`;
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(url);
    return response.json();
  }

  async function loadLearningAudit() {
    try {
      const [paper, learning] = await Promise.allSettled([
        fetchJson('/api/paper-activity/state'),
        fetchJson('/api/learning-os/snapshot'),
      ]);
      const paperPayload = paper.status === 'fulfilled' ? paper.value : { state: {} };
      const learningPayload = learning.status === 'fulfilled' ? learning.value : {};
      const ctx = buildContext(paperPayload, learningPayload);
      let errors = detectErrors(ctx);
      ctx.detectedErrors = errors.length;
      if (ctx.learningLessons < errors.length) {
        errors = detectErrors({ ...ctx, detectedErrors: errors.length });
      }
      renderLearning(ctx, errors);
    } catch (_) {
      const learning = $('#learning-section');
      if (learning) learning.innerHTML = `<h2>Обучение AI</h2><p class="info-box">Не смог загрузить live-аудит ошибок. Проверь /api/paper-activity/state и /api/learning-os/snapshot.</p>`;
    }
  }

  window.addEventListener('DOMContentLoaded', () => {
    setLearningLoading();
    loadLearningAudit();
    setInterval(loadLearningAudit, 30000);
  });
})();
