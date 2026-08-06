(() => {
  'use strict';

  const VERSION = 45;
  const PAGE_OWNERS = new Map([
    ['overview', 'overview_runtime_v44.js'],
    ['market', 'tradingview_market_v32.js'],
    ['decision', 'canonical_pages_v45.js'],
    ['portfolio', 'canonical_pages_v45.js'],
    ['trades', 'canonical_pages_v45.js'],
    ['bots', 'ai_center_v44.js'],
    ['chat', 'web2_shell_v44.js'],
    ['news', 'news_center_v12.js'],
    ['risk', 'canonical_pages_v45.js'],
    ['bybit', 'canonical_pages_v45.js'],
    ['learning', 'canonical_pages_v45.js'],
    ['control', 'canonical_pages_v45.js'],
    ['evidence', 'canonical_pages_v45.js'],
    ['virtual', 'canonical_pages_v45.js'],
    ['campaigns', 'campaign_operations_v36.js'],
    ['reports', 'canonical_pages_v45.js'],
    ['settings', 'canonical_pages_v45.js'],
    ['system-status', 'system_status_v44.js'],
    ['operations', 'operations_center_v20.js'],
    ['incidents', 'incident_center_v21.js'],
  ]);

  const PAGE_LABELS = {
    ru: {
      overview: 'Обзор', market: 'Рынок', decision: 'Решение ИИ', portfolio: 'Портфель',
      trades: 'Сделки', bots: 'Центр ИИ', chat: 'ИИ-чат', news: 'Новости', risk: 'Центр рисков',
      bybit: 'Bybit', learning: 'Центр обучения', control: 'Главное управление',
      evidence: 'Хранилище доказательств', virtual: 'Виртуальный счёт', campaigns: 'Кампании', reports: 'Отчёты',
      settings: 'Настройки', 'system-status': 'Состояние системы', operations: 'Эксплуатация', incidents: 'Центр ошибок',
    },
    en: {
      overview: 'Overview', market: 'Market', decision: 'AI decision', portfolio: 'Portfolio',
      trades: 'Trades', bots: 'AI center', chat: 'AI chat', news: 'News', risk: 'Risk center',
      bybit: 'Bybit', learning: 'Learning center', control: 'Main control', evidence: 'Evidence vault',
      virtual: 'Virtual account', campaigns: 'Campaigns', reports: 'Reports', settings: 'Settings',
      'system-status': 'System status', operations: 'Operations', incidents: 'Incident center',
    },
    uz: {
      overview: 'Umumiy ko‘rinish', market: 'Bozor', decision: 'AI qarori', portfolio: 'Portfel',
      trades: 'Bitimlar', bots: 'AI markazi', chat: 'AI chat', news: 'Yangiliklar', risk: 'Xavf markazi',
      bybit: 'Bybit', learning: 'O‘qitish markazi', control: 'Bosh boshqaruv', evidence: 'Dalillar ombori',
      virtual: 'Virtual hisob', campaigns: 'Kampaniyalar', reports: 'Hisobotlar', settings: 'Sozlamalar',
      'system-status': 'Tizim holati', operations: 'Ekspluatasiya', incidents: 'Xatolar markazi',
    },
  };

  function activePage() {
    return document.querySelector('#nav button.active[data-page]')?.dataset.page || 'overview';
  }

  function scriptFromStack(stack) {
    const value = String(stack || '');
    for (const filename of new Set(PAGE_OWNERS.values())) {
      if (value.includes(filename)) return filename;
    }
    return '';
  }

  function writeAllowed(stack) {
    const value = String(stack || '');
    if (value.includes('sections_v10.js') || value.includes('market_terminal_v13.js')) return false;
    const activeOwner = PAGE_OWNERS.get(activePage());
    const callerOwner = scriptFromStack(value);
    if (activeOwner) return callerOwner === activeOwner || value.includes('navigation_coordinator_v44.js');
    return !callerOwner;
  }

  function installContentOwnership() {
    const content = document.getElementById('content');
    if (!content || content.dataset.navigationOwnership === `v${VERSION}`) return;
    const descriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
    if (!descriptor?.get || !descriptor?.set) return;
    Object.defineProperty(content, 'innerHTML', {
      configurable: true,
      enumerable: descriptor.enumerable,
      get() { return descriptor.get.call(this); },
      set(value) { if (writeAllowed(new Error().stack || '')) descriptor.set.call(this, value); },
    });
    content.dataset.navigationOwnership = `v${VERSION}`;
  }

  function currentLanguage() {
    const value = String(document.documentElement.lang || 'ru').toLowerCase();
    return PAGE_LABELS[value] ? value : 'ru';
  }

  function restoreLabelsAndAria() {
    const nav = document.getElementById('nav');
    if (!nav) return;
    const labels = PAGE_LABELS[currentLanguage()];
    const active = activePage();
    nav.querySelectorAll('button[data-page]').forEach((button) => {
      const page = button.dataset.page;
      if (labels[page] && button.textContent !== labels[page]) button.textContent = labels[page];
      if (page === active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
  }

  function installLabelGuard() {
    const nav = document.getElementById('nav');
    if (!nav || nav.dataset.labelGuard === `v${VERSION}`) return;
    const observer = new MutationObserver(restoreLabelsAndAria);
    observer.observe(nav, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['class', 'data-page'] });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    nav.dataset.labelGuard = `v${VERSION}`;
    restoreLabelsAndAria();
  }

  function installHashNavigation() {
    const nav = document.getElementById('nav');
    if (!nav || nav.dataset.hashNavigation === `v${VERSION}`) return;
    nav.dataset.hashNavigation = `v${VERSION}`;
    nav.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-page]');
      if (!button) return;
      const nextHash = `#${button.dataset.page}`;
      if (location.hash !== nextHash) history.replaceState(null, '', nextHash);
      queueMicrotask(restoreLabelsAndAria);
    }, true);
    const restoreHash = () => {
      const page = decodeURIComponent(location.hash.slice(1));
      if (!page) return;
      const escaped = globalThis.CSS?.escape ? CSS.escape(page) : page.replace(/[^a-z0-9-]/gi, '');
      const button = nav.querySelector(`button[data-page="${escaped}"]`);
      if (button && !button.classList.contains('active')) button.click();
    };
    window.addEventListener('hashchange', restoreHash);
    setTimeout(restoreHash, 0);
  }

  function install() {
    installContentOwnership();
    installLabelGuard();
    installHashNavigation();
  }

  window.SharipovAIPageCoordinator = Object.freeze({
    activePage,
    ownerFor: (page) => PAGE_OWNERS.get(page) || '',
    writeAllowed,
    version: VERSION,
  });

  install();
  window.addEventListener('DOMContentLoaded', install, { once: true });
})();
