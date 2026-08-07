(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const nav = $('nav');
  const content = $('content');
  const notice = $('notice');
  const refresh = $('refresh');
  if (!nav || !content || !refresh) return;

  const defaults = { lang: 'ru', compact: false, animations: true };
  let settings = defaults;
  try { settings = { ...defaults, ...JSON.parse(localStorage.getItem('sharipovai-settings') || '{}') }; } catch {}
  let lang = ['ru', 'en', 'uz'].includes(settings.lang) ? settings.lang : 'ru';
  let page = nav.querySelector('button.active[data-page]')?.dataset.page || 'overview';

  const labels = {
    ru: { overview:'Обзор',market:'Рынок',decision:'Решение ИИ',portfolio:'Портфель',trades:'Сделки',bots:'Центр ИИ',chat:'ИИ-чат',news:'Новости',risk:'Центр рисков',bybit:'Bybit',learning:'Центр обучения',control:'Главное управление',evidence:'Хранилище доказательств',virtual:'Виртуальный счёт',campaigns:'Кампании',reports:'Отчёты',settings:'Настройки','system-status':'Состояние системы',operations:'Эксплуатация',incidents:'Центр ошибок' },
    en: { overview:'Overview',market:'Market',decision:'AI decision',portfolio:'Portfolio',trades:'Trades',bots:'AI center',chat:'AI chat',news:'News',risk:'Risk center',bybit:'Bybit',learning:'Learning center',control:'Main control',evidence:'Evidence vault',virtual:'Virtual account',campaigns:'Campaigns',reports:'Reports',settings:'Settings','system-status':'System status',operations:'Operations',incidents:'Incident center' },
    uz: { overview:'Umumiy ko‘rinish',market:'Bozor',decision:'AI qarori',portfolio:'Portfel',trades:'Bitimlar',bots:'AI markazi',chat:'AI chat',news:'Yangiliklar',risk:'Xavf markazi',bybit:'Bybit',learning:'O‘qitish markazi',control:'Bosh boshqaruv',evidence:'Dalillar ombori',virtual:'Virtual hisob',campaigns:'Kampaniyalar',reports:'Hisobotlar',settings:'Sozlamalar','system-status':'Tizim holati',operations:'Ekspluatatsiya',incidents:'Xatolar markazi' },
  };
  const copy = {
    ru: { hello:'Привет, Самандар 👋', sub:'SharipovAI — единый канонический runtime', refresh:'Обновить', chat:'ИИ-чат', assistant:'Ассистент', prompt:'Спроси о рынке, решениях, риске или каноническом paper runtime.', send:'Отправить', unavailable:'ИИ временно недоступен' },
    en: { hello:'Hello, Samandar 👋', sub:'SharipovAI — one canonical runtime', refresh:'Refresh', chat:'AI chat', assistant:'Assistant', prompt:'Ask about market, decisions, risk, or the canonical paper runtime.', send:'Send', unavailable:'AI is temporarily unavailable' },
    uz: { hello:'Salom, Samandar 👋', sub:'SharipovAI — yagona canonical runtime', refresh:'Yangilash', chat:'AI chat', assistant:'Yordamchi', prompt:'Bozor, qarorlar, xavf yoki canonical paper runtime haqida so‘rang.', send:'Yuborish', unavailable:'AI vaqtincha mavjud emas' },
  };
  const uiMeta = {
    overview:['⌂','ОСНОВНОЕ'], market:['⌁',''], decision:['◇',''], portfolio:['◫',''], trades:['⇄',''], risk:['△',''], bots:['◎','ИИ'], chat:['✦',''], news:['≋',''], learning:['↗',''], evidence:['▣',''], control:['⌘','СИСТЕМА'], bybit:['B',''], virtual:['V',''], campaigns:['◌',''], reports:['▤',''], settings:['⚙',''],
  };

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const get = async (url) => {
    const response = await fetch(url, { credentials:'same-origin', cache:'no-store' });
    if (!response.ok) throw new Error(`${response.status}`);
    return response.json();
  };

  function saveSettings() {
    settings.lang = lang;
    localStorage.setItem('sharipovai-settings', JSON.stringify(settings));
  }

  function decorateNavigation() {
    nav.querySelectorAll('button[data-page]').forEach((button) => {
      const meta = uiMeta[button.dataset.page] || ['·',''];
      button.dataset.uiIcon = meta[0];
      if (meta[1]) {
        button.dataset.uiSectionStart = 'true';
        button.dataset.uiSection = meta[1];
      }
    });
    const aside = nav.closest('aside');
    if (!aside || aside.querySelector('.ui-mobile-nav-toggle')) return;
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'ui-mobile-nav-toggle';
    toggle.setAttribute('aria-controls', 'nav');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.textContent = '☰ Меню';
    toggle.addEventListener('click', () => {
      const open = aside.dataset.mobileOpen !== 'true';
      aside.dataset.mobileOpen = String(open);
      toggle.setAttribute('aria-expanded', String(open));
    });
    nav.before(toggle);
  }

  function ensurePageStatus() {
    let status = $('uiPageStatus');
    if (status) return status;
    status = document.createElement('div');
    status.id = 'uiPageStatus';
    status.className = 'ui-page-status';
    status.innerHTML = '<i></i><span></span>';
    content.before(status);
    return status;
  }

  function updatePageStatus() {
    const status = ensurePageStatus();
    const text = content.textContent || '';
    const noticeVisible = notice && !notice.classList.contains('hidden');
    let state = 'ready';
    let message = '';
    if (/загрузка|loading/i.test(text) && content.querySelectorAll('.card,.panel,.trade-card').length === 0) {
      state = 'loading'; message = 'Загрузка канонических данных…';
    } else if (noticeVisible && /не удалось|недоступ|error|failed/i.test(notice.textContent || '')) {
      state = 'error'; message = 'Канонический runtime недоступен. Данные не подменяются.';
    } else if (noticeVisible) {
      state = 'degraded'; message = 'Runtime сообщает о деградации. Показаны только подтверждённые данные.';
    }
    status.dataset.state = state;
    status.querySelector('span').textContent = message;
  }

  function applyLanguage() {
    const dictionary = labels[lang];
    const text = copy[lang];
    document.documentElement.lang = lang;
    nav.querySelectorAll('button[data-page]').forEach((button) => {
      if (dictionary[button.dataset.page]) button.textContent = dictionary[button.dataset.page];
    });
    if ($('helloLabel')) $('helloLabel').textContent = text.hello;
    if ($('subtitleLabel')) $('subtitleLabel').textContent = text.sub;
    refresh.textContent = text.refresh;
    document.querySelectorAll('[data-lang]').forEach((button) => button.classList.toggle('active', button.dataset.lang === lang));
    document.body.classList.toggle('compact', Boolean(settings.compact));
    document.body.classList.toggle('no-animations', !settings.animations);
    decorateNavigation();
    if (page === 'chat') renderChat();
  }

  function renderChat() {
    if (page !== 'chat') return;
    const text = copy[lang];
    content.innerHTML = `<div class="title"><h1>${esc(text.chat)}</h1><p>${esc(text.prompt)}</p></div><article class="panel wide"><small>SHARIPOVAI</small><h2>${esc(text.assistant)}</h2><div class="chat"><div id="messages" class="messages"><div class="bubble">${esc(text.prompt)}</div></div><form id="chatForm"><input id="msg" autocomplete="off"><button class="action">${esc(text.send)}</button></form></div></article>`;
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
        const response = await fetch('/api/chat/message', { method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ message }) });
        if (!response.ok) throw new Error(String(response.status));
        const payload = await response.json();
        messages.insertAdjacentHTML('beforeend', `<div class="bubble">${esc(payload.reply || '—')}</div>`);
      } catch {
        messages.insertAdjacentHTML('beforeend', `<div class="bubble">${esc(text.unavailable)}</div>`);
      }
    };
  }

  function statusLabel(status) {
    const value = String(status || 'unavailable').toUpperCase();
    return lang === 'en' ? `Canonical runtime: ${value}` : lang === 'uz' ? `Canonical runtime: ${value}` : `Канонический runtime: ${value}`;
  }

  async function loadHeaderStatus() {
    try {
      const truth = await get('/api/system/runtime-truth');
      const status = String(truth.status || 'unavailable').toLowerCase();
      const safety = truth.safety || {};
      const paper = truth.paper?.summary || {};
      if ($('systemLabel')) $('systemLabel').textContent = statusLabel(status);
      if ($('modeText')) {
        $('modeText').dataset.dynamic = '1';
        $('modeText').textContent = safety.real_orders_blocked ? 'CouncilAuthorizedPaperLoop · RiskService · real orders blocked' : 'UNSAFE: execution lock mismatch';
      }
      if (notice) {
        if (status === 'healthy') notice.classList.add('hidden');
        else {
          notice.textContent = `Runtime ${status}. Paper worker: ${paper.worker_running ? 'running' : 'stopped'}. Откройте «Состояние системы».`;
          notice.classList.remove('hidden');
        }
      }
    } catch (error) {
      if ($('systemLabel')) $('systemLabel').textContent = 'Канонический runtime недоступен';
      if ($('modeText')) $('modeText').textContent = 'Нет подтверждённого runtime truth';
      if (notice) {
        notice.textContent = `Не удалось получить canonical runtime truth: ${String(error?.message || error)}`;
        notice.classList.remove('hidden');
      }
    } finally {
      updatePageStatus();
    }
  }

  nav.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-page]');
    if (!button) return;
    nav.querySelectorAll('button[data-page]').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    page = button.dataset.page;
    nav.closest('aside')?.removeAttribute('data-mobile-open');
    nav.previousElementSibling?.classList.contains('ui-mobile-nav-toggle') && nav.previousElementSibling.setAttribute('aria-expanded', 'false');
    if (page === 'chat') renderChat();
    setTimeout(updatePageStatus, 80);
  });

  document.querySelectorAll('[data-lang]').forEach((button) => {
    button.addEventListener('click', () => {
      lang = ['ru','en','uz'].includes(button.dataset.lang) ? button.dataset.lang : 'ru';
      saveSettings();
      applyLanguage();
    });
  });

  new MutationObserver(() => updatePageStatus()).observe(content, { childList:true, subtree:true });
  refresh.addEventListener('click', () => { loadHeaderStatus().catch(() => {}); });
  applyLanguage();
  updatePageStatus();
  loadHeaderStatus().catch(() => {});
  setInterval(() => { if (!document.hidden) loadHeaderStatus().catch(() => {}); }, 30000);
})();
