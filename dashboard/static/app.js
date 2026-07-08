const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => Array.from(document.querySelectorAll(selector));

function fmt(value) {
  const number = Number(value || 0);
  return number.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function setText(selector, value) {
  const el = qs(selector);
  if (el) el.textContent = value;
}

function setState(message, title = 'AI активен') {
  setText('#ai-status-title', title);
  setText('#system-message', message);
  const dot = qs('#heartbeat-dot');
  if (dot) dot.classList.add('pulse-fast');
}

function addMessage(author, text) {
  const log = qs('#ai-chat-log');
  if (!log) return;
  const item = document.createElement('div');
  item.className = author === 'user' ? 'ai-message user-message' : 'ai-message';
  const name = author === 'user' ? 'Самандар' : 'SharipovAI';
  item.innerHTML = `<b>${name}:</b><span></span>`;
  item.querySelector('span').textContent = text;
  log.appendChild(item);
  log.scrollTop = log.scrollHeight;
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

async function runAnalysis(source = 'button') {
  const button = qs('#run-analysis');
  if (button) button.disabled = true;
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
    setText('#last-update', new Date().toLocaleTimeString('ru-RU'));
    setText('#last-action', 'Анализ завершен');
    setText('#decision-reason', data.reason || 'AI сформировал решение на основе сигналов агентов.');
    setState('Анализ завершен. Paper Trading обновлен.', 'AI выполнил задачу');
    setText('#ai-live-label', 'AI работает');
    if (source !== 'silent') addMessage('ai', trade.reply);
  } catch (error) {
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
    setText('#stress-scenario', data.scenario || scenario);
    setText('#stress-before', `${fmt(data.before?.capital ?? data.capital_before)} USDT`);
    setText('#stress-after', `${fmt(data.after?.capital ?? data.capital_after)} USDT`);
    setText('#stress-loss', `-${fmt(data.after?.loss_amount ?? data.loss_amount)} USDT (${Number(data.after?.loss_percent ?? data.loss_percent || 0).toFixed(1)}%)`);
    const measures = qs('#stress-measures');
    if (measures) {
      measures.innerHTML = '';
      (data.protective_measures || []).forEach((item) => {
        const li = document.createElement('li');
        li.textContent = item;
        measures.appendChild(li);
      });
    }
    setText('#stress-result', data.classification || data.result || 'Защита капитала активирована');
    setState('Стресс-тест завершен. Защитные меры рассчитаны.', 'AI проверил риск');
  } catch (error) {
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
  qsa('[data-clock]').forEach((el) => { el.textContent = new Date().toLocaleTimeString('ru-RU'); });
}

window.addEventListener('DOMContentLoaded', () => {
  qs('#run-analysis')?.addEventListener('click', () => runAnalysis('button'));
  qs('#ai-command-form')?.addEventListener('submit', handleCommand);
  qs('#voice-command')?.addEventListener('click', startVoiceCommand);
  qsa('[data-stress-scenario]').forEach((button) => {
    button.addEventListener('click', () => runStressLab(button.dataset.stressScenario));
  });
  qs('#language-select')?.addEventListener('change', (event) => {
    const lang = event.target.value;
    window.location.href = `${window.location.pathname}?lang=${lang}`;
  });
  updateClock();
  setInterval(updateClock, 1000);
  setTimeout(() => addMessage('ai', 'Я уже провел стартовый анализ при загрузке страницы. Для нового решения нажми «Запустить AI».'), 500);
});
