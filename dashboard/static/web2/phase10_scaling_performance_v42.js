(() => {
  'use strict';

  const SELECTOR = '[data-phase10-scaling-performance]';
  const BASE_DELAY = 10000;
  const MAX_DELAY = 60000;
  let timer = null;
  let controller = null;
  let failures = 0;
  let lastSuccessfulAt = 0;

  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  };

  const money = value => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toFixed(2) : '—';
  };

  const integer = value => {
    const parsed = Number(value);
    return Number.isInteger(parsed) && parsed >= 0 ? String(parsed) : '—';
  };

  const metric = (label, value, detail) => {
    const article = node('article', 'phase10-metric');
    article.append(node('small', '', label), node('strong', '', value), node('span', '', detail));
    return article;
  };

  const render = payload => {
    const root = document.querySelector(SELECTOR);
    if (!root) return;
    const active = (payload.activations || []).find(item => item.currently_valid === true);
    const latest = payload.latestMonthly || null;
    const panel = node('section', 'phase10-panel');
    panel.setAttribute('aria-labelledby', 'phase10-title');
    const header = node('header', 'phase10-header');
    const titleBlock = node('div');
    titleBlock.append(node('small', '', 'PHASE 10'), node('h2', '', 'Scaling & Performance'));
    titleBlock.querySelector('h2').id = 'phase10-title';
    const badge = node(
      'span',
      `phase10-badge ${active ? 'active' : 'locked'}`,
      active ? 'ACTIVE TESTNET SCALE' : 'SCALING LOCKED'
    );
    header.append(titleBlock, badge);

    const grid = node('div', 'phase10-grid');
    grid.append(
      metric(
        'Authorized notional',
        `${money(active && active.authorized_notional_usdt)} USDT`,
        active ? String(active.scope || 'Unknown scope') : 'No valid authority'
      ),
      metric(
        'Monthly net PnL',
        `${money(latest && latest.net_pnl_usdt)} USDT`,
        latest ? String(latest.month || 'Unknown month') : 'No immutable report'
      ),
      metric(
        'Monthly fees',
        `${money(latest && latest.fees_usdt)} USDT`,
        `${integer(latest && latest.matched_fill_count)} matched fills`
      ),
      metric(
        'Maximum drawdown',
        `${money(latest && latest.maximum_drawdown_bps)} bps`,
        latest && latest.drawdown_alert ? 'CRITICAL ALERT' : 'Within available evidence'
      )
    );
    const truth = node(
      'p',
      'phase10-truth',
      'Mainnet remains unavailable. Missing or expired authority never becomes an active scale.'
    );
    const updated = node(
      'p',
      'phase10-updated',
      lastSuccessfulAt ? `Updated ${new Date(lastSuccessfulAt).toLocaleTimeString()}` : 'Waiting for evidence'
    );
    updated.setAttribute('aria-live', 'polite');
    panel.append(header, grid, truth, updated);
    root.replaceChildren(panel);
  };

  const renderError = message => {
    const root = document.querySelector(SELECTOR);
    if (!root) return;
    const panel = node('section', 'phase10-panel phase10-error');
    panel.setAttribute('role', 'status');
    panel.setAttribute('aria-live', 'polite');
    panel.append(
      node('h2', '', 'Scaling & Performance'),
      node('p', '', `Evidence unavailable: ${message}`),
      node('p', 'phase10-truth', 'The interface does not substitute missing values.')
    );
    root.replaceChildren(panel);
  };

  const fetchJson = async (url, signal) => {
    const response = await fetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
      signal
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  };

  const schedule = () => {
    clearTimeout(timer);
    const delay = Math.min(MAX_DELAY, BASE_DELAY * Math.max(1, 2 ** failures));
    timer = window.setTimeout(load, delay);
  };

  async function load() {
    if (document.hidden || !navigator.onLine || !document.querySelector(SELECTOR)) {
      schedule();
      return;
    }
    controller?.abort();
    controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const [activationPayload, performancePayload] = await Promise.all([
        fetchJson('/api/campaigns/phase10/activations?limit=20', controller.signal),
        fetchJson('/api/performance/phase10/overview?snapshot_limit=20&report_limit=12', controller.signal)
      ]);
      failures = 0;
      lastSuccessfulAt = Date.now();
      render({
        activations: activationPayload.activations || [],
        latestMonthly: performancePayload.latest_monthly_report || null
      });
    } catch (error) {
      if (error && error.name !== 'AbortError') failures += 1;
      renderError(error && error.name === 'AbortError' ? 'request timeout' : String(error && error.message || error));
    } finally {
      clearTimeout(timeout);
      schedule();
    }
  }

  const start = () => {
    clearTimeout(timer);
    load();
  };

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) start();
  });
  window.addEventListener('online', start);
  window.addEventListener('offline', () => renderError('device is offline'));
  window.addEventListener('pagehide', () => {
    clearTimeout(timer);
    controller?.abort();
  });
  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, { once: true })
    : start();
})();
