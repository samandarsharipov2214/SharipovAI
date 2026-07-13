(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const nav = $('nav');
  const content = $('content');
  const notice = $('notice');
  const refresh = $('refresh');
  if (!nav || !content || !refresh) return;

  const defaults = {
    lang: 'ru', refreshSeconds: 5, compact: false, animations: true,
    verifiedOnly: false, defaultSymbol: 'BTCUSDT', defaultInterval: '15',
    sound: false, desktopNotifications: false,
  };
  let settings = defaults;
  try {
    settings = { ...defaults, ...JSON.parse(localStorage.getItem('sharipovai-settings') || '{}') };
  } catch {
    settings = { ...defaults };
  }
  let lang = ['ru', 'en', 'uz'].includes(settings.lang) ? settings.lang : 'ru';
  let page = document.querySelector('#nav button.active[data-page]')?.dataset.page || 'overview';

  const labels = {
    ru: {
      overview: 'Обзор', market: 'Рынок', decision: 'Решение ИИ', portfolio: 'Портфель',
      trades: 'Сделки', bots: 'Центр ИИ', chat: 'ИИ-чат', news: 'Новости', risk: 'Центр рисков',
      bybit: 'Bybit', learning: 'Центр обучения', control: 'Главное управление',
      evidence: 'Хранилище доказательств', virtual: 'Виртуальный счёт', reports: 'Отчёты',
      settings: 'Настройки', 'system-status': 'Состояние системы', operations: 'Эксплуатация',
      incidents: 'Центр ошибок',
    },
    en: {
      overview: 'Overview', market: 'Market', decision: 'AI decision', portfolio: 'Portfolio',
      trades: 'Trades', bots: 'AI center', chat: 'AI chat', news: 'News', risk: 'Risk center',
      bybit: 'Bybit', learning: 'Learning center', control: 'Main control', evidence: 'Evidence vault',
      virtual: 'Virtual account', reports: 'Reports', settings: 'Settings',
      'system-status': 'System status', operations: 'Operations', incidents: 'Incident center',
    },
    uz: {
      overview: 'Umumiy ko‘rinish', market: 'Bozor', decision: 'AI qarori', portfolio: 'Portfel',
      trades: 'Bitimlar', bots: 'AI markazi', chat: 'AI chat', news: 'Yangiliklar', risk: 'Xavf markazi',
      bybit: 'Bybit', learning: 'O‘qitish markazi', control: 'Bosh boshqaruv',
      evidence: 'Dalillar ombori', virtual: 'Virtual hisob', reports: 'Hisobotlar', settings: 'Sozlamalar',
      'system-status': 'Tizim holati', operations: 'Ekspluatatsiya', incidents: 'Xatolar markazi',
    },
  };
  const text = {
    ru: { hello: 'Привет, Самандар 👋', sub: 'SharipovAI — единый центр анализа, управления и контроля', refresh: 'Обновить', active: 'Режим ИИ активен', safe: 'Безопасное исполнение' },
    en: { hello: 'Hello, Samandar 👋', sub: 'SharipovAI — unified analysis, control and monitoring center', refresh: 'Refresh', active: 'AI mode active', safe: 'Safe execution' },
    uz: { hello: 'Salom, Samandar 👋', sub: 'SharipovAI — tahlil, boshqaruv va nazorat markazi', refresh: 'Yangilash', active: 'AI rejimi faol', safe: 'Xavfsiz ijro' },
  };

  const headerChecks = [
    { key: 'health', url: '/api/health', required: true },
    { key: 'run', url: '/api/run', required: true },
    { key: 'bots', url: '/api/ai-bots', required: true },
    { key: 'news', url: '/api/social-news', required: true },
    { key: 'learning', url: '/api/learning-os/status', required: true },
    { key: 'evidence', url: '/api/evidence-vault/recent', required: true },
    { key: 'virtual', url: '/api/virtual-account/state', required: true },
    { key: 'reports', url: '/api/ai-control-center/daily-report', required: true },
    { key: 'account', url: '/api/exchange/account/status', required: false },
  ];

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
  const tr = (ru, en, uz) => lang === 'en' ? en : lang === 'uz' ? uz : ru;

  function saveSettings() {
    settings.lang = lang;
    localStorage.setItem('sharipovai-settings', JSON.stringify(settings));
  }

  function applyLanguage() {
    const dictionary = labels[lang];
    document.documentElement.lang = lang;
    nav.querySelectorAll('button[data-page]').forEach((button) => {
      const label = dictionary[button.dataset.page];
      if (label) button.textContent = label;
    });
    const copy = text[lang];
    if ($('helloLabel')) $('helloLabel').textContent = copy.hello;
    if ($('subtitleLabel')) $('subtitleLabel').textContent = copy.sub;
    refresh.textContent = copy.refresh;
    if ($('aiModeLabel')) $('aiModeLabel').textContent = copy.active;
    if ($('modeText') && !$('modeText').dataset.dynamic) $('modeText').textContent = copy.safe;
    document.querySelectorAll('[data-lang]').forEach((button) => button.classList.toggle('active', button.dataset.lang === lang));
    document.body.classList.toggle('compact', Boolean(settings.compact));
    document.body.classList.toggle('no-animations', !settings.animations);
    if (page === 'chat') renderChat();
  }

  function renderChat() {
    if (page !== 'chat') return;
    content.innerHTML = `<div class="title"><h1>${esc(tr('ИИ-чат', 'AI chat', 'AI chat'))}</h1><p>${esc(tr('Диалог с SharipovAI', 'Conversation with SharipovAI', 'SharipovAI bilan suhbat'))}</p></div><article class="panel wide"><small>SHARIPOVAI</small><h2>${esc(tr('Ассистент', 'Assistant', 'Yordamchi'))}</h2><div class="chat"><div id="messages" class="messages"><div class="bubble">${esc(tr('Я онлайн. Спроси о рынке, виртуальном счёте или состоянии системы.', 'I am online. Ask about the market, virtual account, or system status.', 'Men onlaynman. Bozor, virtual hisob yoki tizim holati haqida so‘rang.'))}</div></div><form id="chatForm"><input id="msg" autocomplete="off"><button class="action">${esc(tr('Отправить', 'Send', 'Yuborish'))}</button></form></div></article>`;
    bindChat();
  }

  function bindChat() {
    const form = $('chatForm');
    if (!form) return;
    form.onsubmit = async (event) => {
      event.preventDefault();
      const input = $('msg');
      const messages = $('messages');
      const message = String(input?.value || '').trim();
      if (!message || !messages) return;
      messages.insertAdjacentHTML('beforeend', `<div class="bubble user">${esc(message)}</div>`);
      input.value = '';
      try {
        const response = await fetch('/api/chat/message', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message }),
        });
        if (!response.ok) throw new Error(String(response.status));
        const payload = await response.json();
        messages.insertAdjacentHTML('beforeend', `<div class="bubble">${esc(payload.reply || '—')}</div>`);
      } catch {
        messages.insertAdjacentHTML('beforeend', `<div class="bubble">${esc(tr('ИИ временно недоступен', 'AI is temporarily unavailable', 'AI vaqtincha mavjud emas'))}</div>`);
      }
    };
  }

  async function get(url) {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error(`${url}: ${response.status}`);
    return response.json();
  }

  function payloadHealthy(data) {
    const status = String(data?.status || '').toLowerCase();
    return !['error', 'unavailable', 'failed', 'offline'].includes(status);
  }

  async function loadHeaderStatus() {
    const results = await Promise.allSettled(headerChecks.map((check) => get(check.url)));
    const inspected = headerChecks.map((check, index) => {
      const result = results[index];
      const data = result.status === 'fulfilled' ? result.value : null;
      return { ...check, data, responded: result.status === 'fulfilled', healthy: result.status === 'fulfilled' && payloadHealthy(data) };
    });
    const core = inspected.filter((item) => item.required);
    const coreOk = core.filter((item) => item.healthy).length;
    const account = inspected.find((item) => item.key === 'account');
    const accountConnected = Boolean(account?.healthy && account?.data?.credentials_configured && account?.data?.connected);

    if ($('systemLabel')) {
      $('systemLabel').textContent = coreOk
        ? tr(`Система работает · ${coreOk}/${core.length} основных API`, `System online · ${coreOk}/${core.length} core APIs`, `Tizim ishlamoqda · ${coreOk}/${core.length} asosiy API`)
        : tr('Основные API недоступны', 'Core APIs unavailable', 'Asosiy API mavjud emas');
    }
    if ($('modeText')) {
      $('modeText').dataset.dynamic = '1';
      $('modeText').textContent = accountConnected
        ? tr('Bybit read-only · реальные ордера заблокированы', 'Bybit read-only · real orders blocked', 'Bybit read-only · real orderlar bloklangan')
        : tr('Виртуальная торговля · публичные котировки Bybit', 'Virtual trading · public Bybit quotes', 'Virtual savdo · Bybit ommaviy kotirovkalari');
    }
    if (notice) {
      if (coreOk < core.length) {
        notice.textContent = tr(`Недоступны основные источники (${coreOk}/${core.length}). Откройте «Состояние системы» для деталей.`, `Core sources unavailable (${coreOk}/${core.length}). Open System status for details.`, `Asosiy manbalar mavjud emas (${coreOk}/${core.length}). Tafsilotlar uchun Tizim holatini oching.`);
        notice.classList.remove('hidden');
      } else {
        notice.classList.add('hidden');
      }
    }
  }

  nav.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-page]');
    if (!button) return;
    nav.querySelectorAll('button[data-page]').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    page = button.dataset.page;
    if (page === 'chat') renderChat();
  });

  document.querySelectorAll('[data-lang]').forEach((button) => {
    button.addEventListener('click', () => {
      lang = ['ru', 'en', 'uz'].includes(button.dataset.lang) ? button.dataset.lang : 'ru';
      saveSettings();
      applyLanguage();
    });
  });

  refresh.addEventListener('click', () => { loadHeaderStatus().catch(() => {}); });
  window.addEventListener('storage', (event) => {
    if (event.key !== 'sharipovai-settings') return;
    try { settings = { ...defaults, ...JSON.parse(event.newValue || '{}') }; } catch { settings = { ...defaults }; }
    lang = ['ru', 'en', 'uz'].includes(settings.lang) ? settings.lang : 'ru';
    applyLanguage();
  });

  applyLanguage();
  loadHeaderStatus().catch(() => {});
  setInterval(() => { loadHeaderStatus().catch(() => {}); }, 30000);
})();
