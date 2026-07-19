(() => {
  'use strict';

  const SELECTOR = '[data-phase11-production]';
  const BASE_DELAY = 5000;
  const MAX_DELAY = 60000;
  const THEME_KEY = 'sharipovai-theme';
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

  const safeTheme = value => value === 'light' || value === 'dark' ? value : null;

  const preferredTheme = () => {
    try {
      const stored = safeTheme(localStorage.getItem(THEME_KEY));
      if (stored) return stored;
    } catch (_) {
      // Storage may be disabled; system preference remains authoritative.
    }
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches
      ? 'light'
      : 'dark';
  };

  const applyTheme = theme => {
    const selected = safeTheme(theme) || preferredTheme();
    document.documentElement.dataset.theme = selected;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', selected === 'light' ? '#f4f7fb' : '#06111d');
    try {
      localStorage.setItem(THEME_KEY, selected);
    } catch (_) {
      // Theme persistence is optional; rendering remains functional.
    }
  };

  const metric = (label, value, detail, state = '') => {
    const article = node('article', 'p11-metric');
    const title = node('span', '', label);
    const strong = node('strong', state, value);
    const small = node('small', '', detail);
    article.append(title, strong, small);
    return article;
  };

  const formatTime = timestamp => {
    const value = Number(timestamp);
    return Number.isFinite(value) && value > 0
      ? new Date(value).toLocaleString()
      : 'No audit timestamp';
  };

  const render = data => {
    const root = document.querySelector(SELECTOR);
    if (!root) return;
    const blockers = Array.isArray(data.blockers) ? data.blockers : [];
    const warnings = Array.isArray(data.warnings) ? data.warnings : [];
    const ready = data.readiness === 'ready_for_bounded_testnet_preflight' && blockers.length === 0;
    const panel = node('section', 'p11-card');
    panel.setAttribute('aria-labelledby', 'p11-title');

    const header = node('div', 'p11-head');
    const title = node('div');
    title.append(node('small', '', 'PHASE 11'), node('h2', '', 'Production Overview'));
    title.querySelector('h2').id = 'p11-title';
    const theme = node('button', 'p11-theme', '◐');
    theme.type = 'button';
    theme.setAttribute('aria-label', 'Переключить светлую и тёмную тему');
    theme.addEventListener('click', () => {
      applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
    });
    header.append(title, theme);

    const grid = node('div', 'p11-grid');
    grid.append(
      metric('Готовность', String(data.readiness || 'blocked'), ready ? 'Preflight may continue' : 'Blocked until evidence is clean', ready ? 'good' : 'bad'),
      metric('Блокеры', String(blockers.length), blockers.length ? blockers.join(', ') : 'No critical blockers', blockers.length ? 'bad' : 'good'),
      metric('Предупреждения', String(warnings.length), warnings.length ? warnings.join(', ') : 'No warnings'),
      metric('Scaling authority', String(Number(data.active_scaling_authorities || 0)), 'Valid and unexpired authorities only'),
      metric('Audit evidence', data.audit_sha256 ? String(data.audit_sha256).slice(0, 12) : '—', 'SHA-256 prefix'),
      metric('Последний аудит', formatTime(data.audit_created_at_ms), `Cache age ${Number(data.cache_age_ms || 0)} ms`)
    );

    const status = node('p', 'p11-lock', 'Mainnet: OFF · Automatic campaign launch: OFF');
    status.setAttribute('aria-live', 'polite');
    const updated = node(
      'p',
      'p11-updated',
      lastSuccessfulAt ? `Dashboard updated ${new Date(lastSuccessfulAt).toLocaleTimeString()}` : 'Waiting for audit evidence'
    );
    updated.setAttribute('aria-live', 'polite');
    panel.append(header, grid, status, updated);
    root.replaceChildren(panel);
  };

  const renderError = message => {
    const root = document.querySelector(SELECTOR);
    if (!root) return;
    const panel = node('section', 'p11-card p11-error');
    panel.setAttribute('role', 'status');
    panel.setAttribute('aria-live', 'polite');
    panel.append(
      node('h2', '', 'Production Overview'),
      node('p', 'bad', `Audit data unavailable: ${message}`),
      node('p', 'p11-lock', 'Missing dashboard data is treated as blocked, never as ready.')
    );
    root.replaceChildren(panel);
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
      const response = await fetch('/api/production/phase11/overview', {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
        signal: controller.signal
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      failures = 0;
      lastSuccessfulAt = Date.now();
      render(data);
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

  applyTheme(preferredTheme());
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
