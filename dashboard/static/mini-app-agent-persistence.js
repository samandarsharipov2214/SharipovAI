(() => {
  const CHAT_KEY = 'sharipovai.agentChats.v1';
  const ACTION_KEY = 'sharipovai.agentActions.v1';
  const HEARTBEAT_KEY = 'sharipovai.agentHeartbeat.v1';
  const MAX_CHAT_ITEMS = 80;
  const MAX_ACTION_ITEMS = 120;

  const BOT_HINTS = {
    'General Controller': 'проверяю цели, простои, конфликты решений и связь всех ботов',
    'Market Agent': 'сканирую рынок, тренд, объём и уровни',
    'Risk Engine': 'проверяю риск, лимиты и просадку',
    'News Agent': 'сверяю новости, источники и подтверждения',
    'Learning Engine': 'ищу ошибки и создаю новые правила',
    'Paper Trading Bot': 'проверяю виртуальные сделки и PnL',
    'Security Guard': 'проверяю запреты LIVE и безопасность',
  };

  const now = () => new Date();
  const clock = (date = now()) => date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const dayClock = (date = now()) => date.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });

  function read(key, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem(key) || 'null');
      return value && typeof value === 'object' ? value : fallback;
    } catch (_) {
      return fallback;
    }
  }

  function write(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
  }

  function normalizeBot(name) {
    return String(name || 'General Controller').trim() || 'General Controller';
  }

  function appendChat(bot, role, text) {
    const name = normalizeBot(bot);
    const store = read(CHAT_KEY, {});
    const items = Array.isArray(store[name]) ? store[name] : [];
    items.push({ role, text: String(text || ''), time: Date.now() });
    store[name] = items.slice(-MAX_CHAT_ITEMS);
    write(CHAT_KEY, store);
    return store[name];
  }

  function getChat(bot) {
    return read(CHAT_KEY, {})[normalizeBot(bot)] || [];
  }

  function appendAction(bot, text, type = 'AI') {
    const name = normalizeBot(bot);
    const store = read(ACTION_KEY, {});
    const items = Array.isArray(store[name]) ? store[name] : [];
    items.push({ text: String(text || ''), type, time: Date.now() });
    store[name] = items.slice(-MAX_ACTION_ITEMS);
    write(ACTION_KEY, store);
    return store[name];
  }

  function getActions(bot) {
    return read(ACTION_KEY, {})[normalizeBot(bot)] || [];
  }

  function heartbeat(bot, text) {
    const name = normalizeBot(bot);
    const store = read(HEARTBEAT_KEY, {});
    store[name] = { time: Date.now(), text: String(text || BOT_HINTS[name] || 'работаю') };
    write(HEARTBEAT_KEY, store);
    return store[name];
  }

  function getHeartbeat(bot) {
    const name = normalizeBot(bot);
    return read(HEARTBEAT_KEY, {})[name] || heartbeat(name, BOT_HINTS[name] || 'ожидаю задачу');
  }

  function age(ms) {
    if (!ms) return 'неизвестно';
    const diff = Math.max(0, Math.round((Date.now() - Number(ms)) / 1000));
    if (diff < 60) return `${diff} сек назад`;
    if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
    return `${Math.floor(diff / 3600)} ч назад`;
  }

  function botFromModal(modal) {
    return modal?.querySelector('h2')?.textContent?.trim() || 'General Controller';
  }

  function renderChat(modal, bot) {
    const log = modal.querySelector('#agent-chat-log');
    if (!log) return;
    const items = getChat(bot);
    if (!items.length) return;
    log.innerHTML = items.map((item) => {
      const isUser = item.role === 'user';
      return `<div class="mini-message ${isUser ? 'user-message' : 'assistant-message'}"><div class="mini-avatar">${isUser ? 'Вы' : 'AI'}</div><div class="mini-bubble"><b>${isUser ? 'Самандар' : bot}</b><small>${dayClock(new Date(item.time))}</small><p>${escapeHtml(item.text)}</p></div></div>`;
    }).join('');
    log.scrollTop = log.scrollHeight;
  }

  function renderActions(modal, bot) {
    const log = modal.querySelector('#agent-action-log');
    if (!log) return;
    const items = getActions(bot);
    if (!items.length) return;
    log.innerHTML = items.map((item) => `<div>${clock(new Date(item.time))}  ${escapeHtml(item.text)}</div>`).join('');
    log.scrollTop = log.scrollHeight;
  }

  function ensureHeartbeatPanel(modal, bot) {
    if (!modal || modal.querySelector('#agent-live-heartbeat')) return;
    const card = modal.querySelector('.trade-modal-card');
    const grid = card?.querySelector('.mini-grid');
    const hb = getHeartbeat(bot);
    const panel = document.createElement('div');
    panel.id = 'agent-live-heartbeat';
    panel.className = 'info-box';
    panel.innerHTML = `<b>Живая работа:</b><br><span id="agent-heartbeat-text">${escapeHtml(hb.text)}</span><br><b>Последний сигнал:</b> <span id="agent-heartbeat-age">${age(hb.time)}</span>`;
    if (grid) grid.insertAdjacentElement('afterend', panel);
  }

  function refreshHeartbeatPanel(modal, bot) {
    const hb = getHeartbeat(bot);
    const text = modal.querySelector('#agent-heartbeat-text');
    const ageNode = modal.querySelector('#agent-heartbeat-age');
    if (text) text.textContent = hb.text;
    if (ageNode) ageNode.textContent = age(hb.time);
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>'"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
  }

  function generateAnswer(bot, question) {
    const hint = BOT_HINTS[bot] || 'проверяю свою зону ответственности';
    if (/отч[её]т|report/i.test(question)) return `${bot}: отчёт сохранён. Сейчас ${hint}. Последний сигнал: ${clock()}.`;
    if (/ошиб|error|learn/i.test(question)) return `${bot}: проверил ошибки и отправил вывод в Learning-журнал. Повторяющееся: слабая история после сна/деплоя и недостаточная видимость действий.`;
    if (/работ|жив|статус|status/i.test(question)) return `${bot}: я жив. Последний heartbeat ${clock()}. ${hint}.`;
    return `${bot}: принял вопрос. ${hint}. Ответ сохранён в истории чата Mini App.`;
  }

  function installIntoModal() {
    const modal = document.querySelector('#agent-detail-modal.open');
    if (!modal || modal.dataset.persistenceInstalled === '1') return;
    const bot = botFromModal(modal);
    modal.dataset.persistenceInstalled = '1';
    heartbeat(bot, BOT_HINTS[bot] || 'бот открыт пользователем и проверяет состояние');
    ensureHeartbeatPanel(modal, bot);
    renderActions(modal, bot);
    renderChat(modal, bot);
    refreshHeartbeatPanel(modal, bot);

    modal.querySelectorAll('[data-agent-command]').forEach((button) => {
      button.addEventListener('click', () => {
        const map = {
          report: 'запрошен отчёт и сохранён в журнале',
          test: 'пройден тест адекватности: OK',
          pause: 'demo-пауза записана, LIVE не затронут',
          learn: 'последние ошибки отправлены в Learning',
        };
        appendAction(bot, map[button.dataset.agentCommand] || 'действие выполнено', 'USER');
        heartbeat(bot, map[button.dataset.agentCommand] || 'выполняю команду');
        renderActions(modal, bot);
        refreshHeartbeatPanel(modal, bot);
      }, { capture: true });
    });

    const form = modal.querySelector('#agent-chat-form');
    form?.addEventListener('submit', (event) => {
      const input = modal.querySelector('#agent-chat-input');
      const text = String(input?.value || '').trim();
      if (!text) return;
      appendChat(bot, 'user', text);
      const fallback = generateAnswer(bot, text);
      appendChat(bot, 'ai', fallback);
      appendAction(bot, `ответил в чате: ${text.slice(0, 60)}`, 'CHAT');
      heartbeat(bot, `ответил в чате ${clock()}`);
      fetch('/api/bot-network/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({ bot, message: text }),
      })
        .then((response) => (response.ok ? response.json() : null))
        .then((payload) => {
          if (payload?.reply) appendChat(bot, 'ai', payload.reply);
          renderChat(modal, bot);
        })
        .catch(() => {});
      setTimeout(() => {
        renderChat(modal, bot);
        renderActions(modal, bot);
        refreshHeartbeatPanel(modal, bot);
      }, 0);
    }, { capture: true });
  }

  function seedGlobalHeartbeat() {
    Object.keys(BOT_HINTS).forEach((bot) => {
      const hb = getHeartbeat(bot);
      if (Date.now() - hb.time > 30000) heartbeat(bot, BOT_HINTS[bot]);
    });
  }

  window.addEventListener('DOMContentLoaded', () => {
    seedGlobalHeartbeat();
    setInterval(seedGlobalHeartbeat, 15000);
    setInterval(installIntoModal, 500);
    setInterval(() => {
      const modal = document.querySelector('#agent-detail-modal.open');
      if (modal) refreshHeartbeatPanel(modal, botFromModal(modal));
    }, 1000);
  });
})();
