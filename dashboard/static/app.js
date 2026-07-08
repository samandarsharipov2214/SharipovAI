const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => Array.from(document.querySelectorAll(selector));
const CHAT_KEY = 'sharipovai_chat_history_v1';

function fmt(value) {
  const number = Number(value || 0);
  return number.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function clockText() {
  return new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function dateText() {
  return new Date().toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
    weekday: 'long'
  });
}

function setText(selector, value) {
  const el = qs(selector);
  if (el) el.textContent = value;
}

function setState(message, title = 'AI активен') {
  setText('#ai-status-title', title);
  setText('#system-message', message);
  setText('#top-ai-status', title.replace('AI ', '').toUpperCase());
  setText('#top-last-update', clockText());
  const dot = qs('#heartbeat-dot');
  if (dot) dot.classList.add('pulse-fast');
}

function loadMessages() {
  try {
    return JSON.parse(localStorage.getItem(CHAT_KEY) || '[]');
  } catch (_) {
    return [];
  }
}

function saveMessages(messages) {
  localStorage.setItem(CHAT_KEY, JSON.stringify(messages.slice(-80)));
}

function createMessage(author, text, time = clockText()) {
  const isUser = author === 'user';
  const item = document.createElement('div');
  item.className = `ai-message ${isUser ? 'user-message' : 'assistant-message'}`;
  const name = isUser ? 'Самандар' : 'SharipovAI';
  const avatar = isUser ? 'SA' : 'AI';
  item.innerHTML = `
    <div class="message-avatar">${avatar}</div>
    <div class="message-bubble">
      <div class="message-meta"><b>${name}</b><time>${time}</time></div>
      <p></p>
    </div>
  `;
  item.querySelector('p').textContent = text;
  return item;
}

function renderChat() {
  const log = qs('#ai-chat-log');
  if (!log) return;
  let messages = loadMessages();
  if (!messages.length) {
    messages = [{ author: 'ai', text: 'Привет, Самандар. Я онлайн. Нажми «Запустить AI» или дай команду текстом/голосом.', time: clockText() }];
    saveMessages(messages);
  }
  log.innerHTML = '';
  messages.forEach((msg) => log.appendChild(createMessage(msg.author, msg.text, msg.time)));
  log.scrollTop = log.scrollHeight;
}

function addMessage(author, text) {
  const log = qs('#ai-chat-log');
  if (!log) return;
  const time = clockText();
  log.appendChild(createMessage(author, text, time));
  log.scrollTop = log.scrollHeight;
  const messages = loadMessages();
  messages.push({ author, text, time });
  saveMessages(messages);
}

function clearChat() {
  localStorage.removeItem(CHAT_KEY);
  renderChat();
}

function tradeText(data) {
  const decision = String(data.decision || 'NO_DECISION').toUpperCase();
  const positions = Number(data.open_positions || 0);
  if (decision === 'BUY' && positions > 0) {
    return {
      action: 'Куплено 0.0100 BTC',
      details: 'Виртуальная покупка BTCUSDT по 50 000 USDT. Это Paper Trading, реальные деньги не использованы.',
      reply: 'Я завершил анализ и открыл виртуальную позицию BTC в Paper Trading. Риск проверен, реальные деньги не затронуты.'
    };
  }
  return {
    action: 'Сделка не открыта',
    details: 'AI не получил достаточно безопасный сигнал для виртуальной покупки.',
    reply: 'Я завершил анализ. Сейчас безопаснее наблюдать, поэтому виртуальная сделка не открыта.'
  };
}

function setModuleActivity(state) {
  qsa('.system-strip > div small').forEach((small, index) => {
    const status = state === 'running' ? (index < 3 ? 'Running' : 'Waiting') : 'Success';
    small.textContent = `${status} · ${clockText()}`;
  });
}

async function runAnalysis(source = 'button') {
  const button = qs('#run-analysis');
  if (button) button.disabled = true;
  setModuleActivity('running');
  setState('AI анализирует рынок, новости, риск и виртуальный портфель...', 'AI думает');
  setText('#ai-live-label', 'AI анализирует');
  try {
    const response = await fetch('/api/run');
    const data = await response.json();
    const decision = String(data.decision || 'NO_DECISION');
    const translated = { BUY: 'ПОКУПАТЬ БИТКОЙН', SELL: 'ПРОДАВАТЬ', WATCH: 'НАБЛЮДАТЬ', IGNORE: 'ИГНОРИРОВАТЬ', NO_DECISION: 'НЕТ РЕШЕНИЯ' }[decision] || decision;
    const trade = tradeText(data);
    setText('#hero-decision', translated);
    setText('#hero-confidence', `${Number(data.confidence || 0).toFixed(1)}%`);
    setText('#hero-risk', String(data.risk_level || 'LOW'));
    setText('#hero-consensus', `${String(data.consensus || 'WEAK')} ${Number(data.consensus_agreement || 0).toFixed(1)}%`);
    setText('#portfolio-equity', `${fmt(data.paper_equity)} USDT`);
    setText('#portfolio-cash', `${fmt(data.paper_cash)} USDT`);
    setText('#portfolio-pnl', `${fmt(data.paper_pnl)} USDT`);
    setText('#open-positions', String(data.open_positions || 0));
    setText('#trade-action', trade.action);
    setText('#trade-details', trade.details);
    setText('#last-update', clockText());
    setText('#last-action', 'Анализ завершен');
    setText('#decision-reason', data.reason || 'AI сформировал решение на основе сигналов агентов.');
    setState('Анализ завершен. Paper Trading обновлен.', 'AI работает');
    setText('#ai-live-label', 'AI работает');
    setModuleActivity('success');
    if (source !== 'silent') addMessage('ai', trade.reply);
  } catch (_) {
    setState('Ошибка анализа. Система сохранила безопасное состояние.', 'AI защита');
    addMessage('ai', 'Не смог выполнить анализ. Проверь сервер и перезапусти команду.');
  } finally {
    if (button) button.disabled = false;
  }
}

async function runStressLab(scenario = 'btc_drop_20') {
  setState('Стресс-лаборатория моделирует рыночный удар...', 'AI проверяет риск');
  try {
    const response = await fetch('/api/stress-lab/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario })
    });
    const data = await response.json();
    const before = data.before?.capital ?? data.capital_before;
    const after = data.after?.capital ?? data.capital_after;
    const loss = data.after?.loss_amount ?? data.loss_amount;
    const lossPercent = data.after?.loss_percent ?? data.loss_percent || 0;
    setText('#stress-scenario', data.scenario || scenario);
    setText('#stress-before', `${fmt(before)} USDT`);
    setText('#stress-after', `${fmt(after)} USDT`);
    setText('#stress-loss', `-${fmt(loss)} USDT (${Number(lossPercent).toFixed(1)}%)`);
    setText('#stress-saved', `${fmt(after)} USDT`);
    const measures = qs('#stress-measures');
    if (measures) {
      measures.innerHTML = '';
      (data.protective_measures || []).forEach((measure) => {
        const li = document.createElement('li');
        li.textContent = measure;
        measures.appendChild(li);
      });
    }
    setText('#stress-result', data.classification || data.result || 'Защита капитала активирована');
    setState('Стресс-тест завершен. Защитные меры рассчитаны.', 'AI проверил риск');
    addMessage('ai', `Стресс-тест завершен. Потеряно ${fmt(loss)} USDT, сохранено ${fmt(after)} USDT.`);
  } catch (_) {
    setState('Стресс-тест не выполнен. Реальные средства не затронуты.', 'AI защита');
  }
}

function handleCommand(event) {
  event.preventDefault();
  const input = qs('#ai-command-input');
  const command = String(input?.value || '').trim();
  if (!command) {
    addMessage('ai', 'Напиши команду. Например: «проанализируй BTC и купи виртуально, если риск низкий».');
    return;
  }
  addMessage('user', command);
  if (input) input.value = '';
  const normalized = command.toLowerCase();
  if (normalized.includes('стресс') || normalized.includes('падени') || normalized.includes('crash')) {
    addMessage('ai', 'Запускаю стресс-тест BTC −20% и проверяю защиту капитала.');
    runStressLab('btc_drop_20');
    return;
  }
  addMessage('ai', 'Принял команду. Запускаю анализ и безопасное Paper Trading действие.');
  runAnalysis('command');
}

function startVoiceCommand() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    addMessage('ai', 'Голосовой ввод не поддерживается этим браузером. Напиши команду текстом.');
    return;
  }
  const recognition = new SpeechRecognition();
  recognition.lang = 'ru-RU';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  setState('Слушаю голосовую команду...', 'AI слушает');
  recognition.onresult = (event) => {
    const text = event.results[0][0].transcript;
    const input = qs('#ai-command-input');
    if (input) input.value = text;
    addMessage('user', text);
    addMessage('ai', 'Голосовая команда принята. Запускаю анализ.');
    runAnalysis('voice');
  };
  recognition.onerror = () => {
    addMessage('ai', 'Не смог распознать голос. Попробуй еще раз или напиши команду текстом.');
    setState('Голосовая команда не распознана.', 'AI активен');
  };
  recognition.start();
}

function updateClock() {
  const time = clockText();
  qsa('[data-clock]').forEach((el) => { el.textContent = time; });
  setText('#top-date', dateText());
}

window.addEventListener('DOMContentLoaded', () => {
  renderChat();
  qs('#run-analysis')?.addEventListener('click', () => runAnalysis('button'));
  qs('#ai-command-form')?.addEventListener('submit', handleCommand);
  qs('#voice-command')?.addEventListener('click', startVoiceCommand);
  qs('#clear-chat')?.addEventListener('click', clearChat);
  qsa('[data-stress-scenario]').forEach((button) => {
    button.addEventListener('click', () => runStressLab(button.dataset.stressScenario));
  });
  qs('#language-select')?.addEventListener('change', (event) => {
    const lang = event.target.value;
    window.location.href = `${window.location.pathname}?lang=${lang}`;
  });
  updateClock();
  setInterval(updateClock, 1000);
});
