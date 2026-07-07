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

function setState(message) {
  setText('#system-message', message);
  const dot = qs('#heartbeat-dot');
  if (dot) dot.classList.add('pulse-fast');
}

async function runAnalysis() {
  const button = qs('#run-analysis');
  if (button) button.disabled = true;
  setState('AI анализирует рынок, новости, риск и виртуальный портфель...');
  try {
    const response = await fetch('/api/run');
    const data = await response.json();
    const decision = String(data.decision || 'NO_DECISION');
    const translated = { BUY: 'ПОКУПАТЬ BTC', SELL: 'ПРОДАВАТЬ', WATCH: 'НАБЛЮДАТЬ', IGNORE: 'ИГНОРИРОВАТЬ', NO_DECISION: 'НЕТ РЕШЕНИЯ' }[decision] || decision;
    setText('#hero-decision', translated);
    setText('#hero-confidence', `${Number(data.confidence || 0).toFixed(1)}%`);
    setText('#hero-risk', String(data.risk_level || 'LOW'));
    setText('#portfolio-equity', `${fmt(data.paper_equity)} USDT`);
    setText('#portfolio-cash', `${fmt(data.paper_cash)} USDT`);
    setText('#portfolio-pnl', `${fmt(data.paper_pnl)} USDT`);
    setText('#system-message', 'Анализ завершен. Интерфейс обновлен.');
    setText('#last-update', new Date().toLocaleTimeString('ru-RU'));
  } catch (error) {
    setState('Ошибка анализа. Система сохранила безопасное состояние.');
  } finally {
    if (button) button.disabled = false;
  }
}

async function runStressLab(scenario = 'btc_drop_20') {
  setState('Стресс-лаборатория моделирует рыночный удар...');
  try {
    const response = await fetch('/api/stress-lab/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario })
    });
    const data = await response.json();
    setText('#stress-scenario', data.scenario || scenario);
    setText('#stress-before', `${fmt(data.capital_before)} USDT`);
    setText('#stress-after', `${fmt(data.capital_after)} USDT`);
    setText('#stress-loss', `-${fmt(data.loss_amount)} USDT (${Number(data.loss_percent || 0).toFixed(1)}%)`);
    const measures = qs('#stress-measures');
    if (measures) {
      measures.innerHTML = '';
      (data.protective_measures || []).forEach((item) => {
        const li = document.createElement('li');
        li.textContent = item;
        measures.appendChild(li);
      });
    }
    setText('#stress-result', data.result || 'Защита капитала активирована');
    setState('Стресс-тест завершен. Защитные меры рассчитаны.');
  } catch (error) {
    setState('Стресс-тест не выполнен. Реальные средства не затронуты.');
  }
}

function updateClock() {
  qsa('[data-clock]').forEach((el) => { el.textContent = new Date().toLocaleTimeString('ru-RU'); });
}

window.addEventListener('DOMContentLoaded', () => {
  qs('#run-analysis')?.addEventListener('click', runAnalysis);
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
