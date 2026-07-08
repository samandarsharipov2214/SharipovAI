(() => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const fmt = (value) => Number(value || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function addMessage(role, text) {
    const log = $('#ai-chat-log');
    if (!log) return;
    const item = document.createElement('div');
    item.className = `mini-message ${role === 'user' ? 'user-message' : 'assistant-message'}`;
    item.innerHTML = `<div class="mini-avatar">${role === 'user' ? 'Вы' : 'SA'}</div><div class="mini-bubble"><b>${role === 'user' ? 'Самандар' : 'SharipovAI'}</b><p></p></div>`;
    item.querySelector('p').textContent = text;
    log.appendChild(item);
    log.scrollTop = log.scrollHeight;
  }

  function setText(selector, value) {
    const el = $(selector);
    if (el) el.textContent = value;
  }

  function renderTrades(trades) {
    const table = document.querySelector('.mini-table tbody');
    if (!table) return;
    const rows = (trades || []).slice(-6).reverse();
    table.innerHTML = '';
    if (!rows.length) {
      table.innerHTML = '<tr><td>Сделок пока нет</td><td>0.00</td></tr>';
      return;
    }
    rows.forEach((trade) => {
      const pnl = Number(trade.pnl_usdt || 0);
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${trade.asset || trade.symbol || 'BTC/USDT'} ${trade.side || ''}</td><td class="${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${fmt(pnl)}</td>`;
      table.appendChild(tr);
    });
  }

  function renderState(state) {
    if (!state) return;
    const pnl = Number(state.pnl || 0);
    setText('#portfolio-equity', `${fmt(state.equity)} USDT`);
    setText('#portfolio-pnl', `${fmt(pnl)} USDT`);
    setText('#hero-risk', String(state.risk_level || 'LOW'));
    setText('#hero-decision', String(state.decision || 'WATCH'));
    renderTrades(state.trades || []);
  }

  async function loadDemoState() {
    try {
      const response = await fetch('/api/demo/state', { cache: 'no-store' });
      if (!response.ok) return;
      const payload = await response.json();
      renderState(payload.state);
    } catch (_) {}
  }

  async function runDemoCommand(command) {
    const response = await fetch('/api/demo/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({ message: command })
    });
    if (!response.ok) throw new Error('demo chat failed');
    return response.json();
  }

  async function submitCommand(command) {
    const input = $('#ai-command-input');
    const value = String(command || input?.value || '').trim();
    if (!value) {
      addMessage('ai', 'Напиши команду: «купи BTC», «продай», «поставь баланс 20000», «покажи портфель» или «анализ рынка».');
      return;
    }
    addMessage('user', value);
    if (input) input.value = '';
    try {
      const payload = await runDemoCommand(value);
      renderState(payload.state);
      addMessage('ai', payload.reply || 'Команда выполнена в demo account.');
    } catch (_) {
      addMessage('ai', 'Не смог выполнить demo-команду. Сервер ещё деплоится или API недоступен.');
    }
  }

  function installLiveHandlers() {
    const form = $('#ai-command-form');
    if (form) {
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        submitCommand();
      }, true);
    }
    $$('[data-prompt]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        submitCommand(button.dataset.prompt || button.textContent || 'портфель');
      }, true);
    });

    const riskCard = $('.risk-panel');
    if (riskCard && !$('#demo-balance-input')) {
      const box = document.createElement('div');
      box.className = 'info-box';
      box.innerHTML = '<b>Демо-баланс</b><br><input id="demo-balance-input" type="number" min="1" value="10000" style="width:100%;margin-top:10px;border-radius:14px;padding:12px;background:#06111f;color:white;border:1px solid #1e90ff44"><button class="save-button" type="button" id="set-demo-balance">Установить demo balance</button>';
      riskCard.appendChild(box);
      $('#set-demo-balance')?.addEventListener('click', () => {
        const amount = $('#demo-balance-input')?.value || '10000';
        submitCommand(`поставь баланс ${amount}`);
      });
    }
  }

  window.addEventListener('DOMContentLoaded', () => {
    installLiveHandlers();
    loadDemoState();
  });
})();
