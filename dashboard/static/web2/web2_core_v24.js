(() => {
  'use strict';

  const nav = document.getElementById('nav');
  const content = document.getElementById('content');
  const refresh = document.getElementById('refresh');
  const systemLabel = document.getElementById('systemLabel');
  if (!nav || !content) return;

  const OWNER = 'web2_core_v24.js';
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));

  function readSettings() {
    try { return JSON.parse(localStorage.getItem('sharipovai-settings') || '{}'); }
    catch { return {}; }
  }

  function writeSettings(value) {
    localStorage.setItem('sharipovai-settings', JSON.stringify(value));
  }

  function language() {
    const value = String(document.documentElement.lang || readSettings().lang || 'ru').toLowerCase();
    return ['ru', 'en', 'uz'].includes(value) ? value : 'ru';
  }

  function text(ru, en, uz) {
    return language() === 'en' ? en : language() === 'uz' ? uz : ru;
  }

  function setActive(page) {
    nav.querySelectorAll('button[data-page]').forEach((button) => {
      button.classList.toggle('active', button.dataset.page === page);
    });
    window.SharipovAIPageCoordinator?.restoreLabels?.();
  }

  function renderChat() {
    const page = window.SharipovAIPageCoordinator?.activePage?.() || 'overview';
    if (page !== 'chat' || !window.SharipovAIPageCoordinator?.canRender?.(OWNER, page)) return;
    content.innerHTML = `<div class="title"><h1>${esc(text('ИИ-чат', 'AI chat', 'AI chat'))}</h1><p>${esc(text('Ответы системы с указанием источника данных', 'System answers with data attribution', 'Ma’lumot manbasi ko‘rsatilgan tizim javoblari'))}</p></div>
      <article class="panel wide"><small>SHARIPOVAI</small><h2>${esc(text('Диалог', 'Conversation', 'Suhbat'))}</h2>
        <div class="chat"><div id="messages" class="messages"><div class="bubble">${esc(text('Я готов. Спроси о рынке, риске, новостях или портфеле.', 'Ready. Ask about market, risk, news or portfolio.', 'Tayyorman. Bozor, xavf, yangiliklar yoki portfel haqida so‘rang.'))}</div></div>
        <form id="chatForm"><input id="msg" autocomplete="off" required><button class="action" type="submit">${esc(text('Отправить', 'Send', 'Yuborish'))}</button></form></div>
      </article>`;

    const form = document.getElementById('chatForm');
    form?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const input = document.getElementById('msg');
      const messages = document.getElementById('messages');
      const message = String(input?.value || '').trim();
      if (!message || !messages) return;
      messages.insertAdjacentHTML('beforeend', `<div class="bubble user">${esc(message)}</div>`);
      input.value = '';
      try {
        const response = await fetch('/api/chat/message', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message })
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        const source = data.source_ai ? ` · ${data.source_ai}` : '';
        messages.insertAdjacentHTML('beforeend', `<div class="bubble">${esc(data.reply || '—')}<small>${esc(source)}</small></div>`);
      } catch (error) {
        messages.insertAdjacentHTML('beforeend', `<div class="bubble negative">${esc(text('ИИ временно недоступен', 'AI is temporarily unavailable', 'AI vaqtincha mavjud emas'))}</div>`);
      }
    });
  }

  async function refreshHealth() {
    if (!systemLabel) return;
    try {
      const response = await fetch('/api/health', { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const ok = data.status === 'ok';
      systemLabel.textContent = ok ? text('Система отвечает', 'System online', 'Tizim ishlamoqda') : text('Система сообщает об ошибке', 'System reports an error', 'Tizim xato haqida xabar berdi');
    } catch {
      systemLabel.textContent = text('API недоступен', 'API unavailable', 'API mavjud emas');
    }
  }

  function applyLanguage(next) {
    const current = readSettings();
    const value = ['ru', 'en', 'uz'].includes(next) ? next : 'ru';
    document.documentElement.lang = value;
    writeSettings({ ...current, lang: value });
    document.querySelectorAll('[data-lang]').forEach((button) => button.classList.toggle('active', button.dataset.lang === value));
    document.getElementById('helloLabel').textContent = text('Привет, Самандар 👋', 'Hello, Samandar 👋', 'Salom, Samandar 👋');
    document.getElementById('subtitleLabel').textContent = text('SharipovAI — единый центр анализа, управления и контроля', 'SharipovAI — unified analysis and control center', 'SharipovAI — yagona tahlil va boshqaruv markazi');
    if (refresh) refresh.textContent = text('Обновить', 'Refresh', 'Yangilash');
    window.SharipovAIPageCoordinator?.restoreLabels?.();
    if ((window.SharipovAIPageCoordinator?.activePage?.() || '') === 'chat') renderChat();
    window.dispatchEvent(new CustomEvent('sharipovai:language', { detail: { language: value } }));
  }

  nav.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-page]');
    if (!button) return;
    setActive(button.dataset.page);
    if (button.dataset.page === 'chat') setTimeout(renderChat, 0);
  }, true);

  document.querySelector('.language-switcher')?.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-lang]');
    if (button) applyLanguage(button.dataset.lang);
  });

  refresh?.addEventListener('click', () => {
    refreshHealth();
    window.dispatchEvent(new CustomEvent('sharipovai:refresh'));
  });

  window.addEventListener('hashchange', () => {
    const page = decodeURIComponent(location.hash.slice(1));
    if (page) setActive(page);
  });

  window.addEventListener('DOMContentLoaded', () => {
    const initial = decodeURIComponent(location.hash.slice(1)) || nav.querySelector('button.active[data-page]')?.dataset.page || 'overview';
    setActive(initial);
    applyLanguage(readSettings().lang || 'ru');
    if (initial === 'chat') renderChat();
    refreshHealth();
  }, { once: true });
})();
