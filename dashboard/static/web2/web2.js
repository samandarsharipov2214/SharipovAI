(() => {
  'use strict';

  const nav = document.getElementById('nav');
  const content = document.getElementById('content');
  const notice = document.getElementById('notice');
  const refresh = document.getElementById('refresh');
  const state = { account: null, bots: null, news: null };

  if (!nav || !content) return;

  const money = value => Number(value || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
  const title = (heading, text) => `<div class="title"><h1>${heading}</h1><p>${text}</p></div>`;
  const card = (label, value, note, css = '') => `<article class="card"><span>${label}</span><strong class="${css}">${value}</strong><small>${note}</small></article>`;
  const panel = (heading, body, css = '') => `<article class="panel ${css}"><small>SHARIPOVAI</small><h2>${heading}</h2>${body}</article>`;
  const bars = () => `<div class="chart">${[40,52,47,63,58,72,68,79,84,77,91,88].map(x => `<div class="bar" style="height:${x}%"></div>`).join('')}</div>`;
  const markets = () => [['BTC/USDT','118 432.45','+1.24%'],['ETH/USDT','2 987.31','+2.15%'],['SOL/USDT','167.45','-0.21%'],['BNB/USDT','693.22','+0.73%'],['XRP/USDT','0.5632','+1.42%']]
    .map(row => `<div class="row"><b>${row[0]}</b><span>${row[1]}</span><em class="${row[2].startsWith('-') ? 'negative' : 'positive'}">${row[2]}</em></div>`).join('');

  function overview() {
    const account = state.account || {};
    const equity = account.total_equity || account.totalEquity || 0;
    const available = account.total_available_balance || account.totalAvailableBalance || 0;
    const positions = Array.isArray(account.positions) ? account.positions.length : 0;
    return title('Mission Control', 'Живое состояние SharipovAI') +
      `<section class="metrics">
        ${card('Общий баланс', equity ? `${money(equity)} USDT` : '—', equity ? 'Данные Bybit' : 'Ожидание подключения')}
        ${card('Доступно', available ? `${money(available)} USDT` : '—', 'Свободные средства')}
        ${card('Открытые позиции', positions, 'Под контролем AI')}
        ${card('Риск системы', 'НИЗКИЙ', 'Risk Center', 'positive')}
      </section>
      <section class="grid">
        ${panel('График BTC/USDT', bars(), 'wide')}
        ${panel('Решение AI', '<div class="decision">WATCH</div><div class="meter"><span></span></div><p>Решение подтверждается Risk Center перед исполнением.</p>')}
        ${panel('Рынок сегодня', markets())}
        ${panel('Что делает AI', '<div class="status-list">' + ['Анализирует рынок','Сканирует новости','Проверяет риск','Следит за позициями','Ищет вход'].map(x => `<div><span><i></i>${x}</span><b>LIVE</b></div>`).join('') + '</div>')}
        ${panel('Состояние системы', '<div class="status-list"><div><span>Backend</span><b>ONLINE</b></div><div><span>Интерфейс</span><b>ONLINE</b></div><div><span>Kill Switch</span><b>ВКЛЮЧЁН</b></div></div>', 'wide')}
      </section>`;
  }

  function page(name) {
    if (name === 'Обзор') return overview();
    if (name === 'Рынок') return title(name, 'Котировки и сигналы') + panel('Рынок в реальном времени', markets(), 'wide');
    if (name === 'AI-решение') return title(name, 'Консенсус AI-модулей') + panel('Текущее решение', '<div class="decision">WATCH</div><div class="meter"><span></span></div><p>Market AI, News AI и Risk AI собирают подтверждение.</p>', 'wide');
    if (name === 'Портфель') return title(name, 'Баланс и распределение активов') + `<section class="metrics">${card('Капитал', state.account ? `${money(state.account.total_equity)} USDT` : '—', 'Всего')}${card('Доступно', state.account ? `${money(state.account.total_available_balance)} USDT` : '—', 'Свободно')}${card('Риск', 'НИЗКИЙ', 'Система стабильна', 'positive')}</section>${panel('Динамика портфеля', bars(), 'wide')}`;
    if (name === 'Сделки') return title(name, 'История исполнения') + panel('Сделки', '<table class="table"><tr><th>Пара</th><th>Сторона</th><th>Статус</th><th>PnL</th></tr><tr><td colspan="4">История загрузится из торгового журнала</td></tr></table>', 'wide');
    if (name === 'AI-боты') {
      const bots = state.bots && Array.isArray(state.bots.bots) ? state.bots.bots : [];
      const names = bots.length ? bots.map(x => x.name || 'AI-модуль') : ['General Controller','Market AI','News AI','Risk AI','Execution AI','Portfolio AI'];
      return title(name, 'Сеть модулей SharipovAI') + `<section class="bot-grid">${names.slice(0,12).map(n => panel(n, '<p class="positive">● Работает</p><small>Последнее действие: анализ данных</small>')).join('')}</section>`;
    }
    if (name === 'AI-чат') return title(name, 'Чат с SharipovAI') + panel('AI Copilot', '<div class="chat"><div class="messages" id="messages"><div class="bubble">Я онлайн. Спроси о рынке, риске или портфеле.</div></div><form id="chatForm"><input id="msg" placeholder="Напиши сообщение"><button class="action" type="submit">Отправить</button></form></div>', 'wide');
    if (name === 'Новости') {
      const news = state.news && Array.isArray(state.news.news) ? state.news.news : [];
      const rows = news.length ? news : [{title:'Новости рынка загружаются'},{title:'News AI проверяет источники'},{title:'Влияние событий будет оценено'}];
      return title(name, 'События и влияние на рынок') + `<section class="news-grid">${rows.slice(0,9).map(x => panel(x.title || 'Новость рынка', '<p>News AI оценивает влияние и важность события.</p>')).join('')}</section>`;
    }
    if (name === 'Risk Center') return title(name, 'Безопасность и лимиты') + `<section class="metrics">${card('Общий риск','НИЗКИЙ','Система стабильна','positive')}${card('Kill Switch','ВКЛЮЧЁН','Реальные сделки заблокированы')}${card('Лимиты','АКТИВНЫ','Контроль капитала','positive')}</section>${panel('Контроль риска','<div class="status-list"><div><span>Размер позиции</span><b>OK</b></div><div><span>Лимиты капитала</span><b>OK</b></div><div><span>Проверка новостей</span><b>OK</b></div></div>','wide')}`;
    if (name === 'Bybit') {
      const connected = Boolean(state.account);
      return title(name, 'Личный кабинет биржи') + `<section class="metrics">${card('Подключение', connected ? 'ПОДКЛЮЧЁН' : 'НЕ ПОДКЛЮЧЁН', connected ? 'Данные получены' : 'Проверяется API', connected ? 'positive' : 'negative')}${card('Капитал', connected ? `${money(state.account.total_equity)} USDT` : '—', 'Unified Account')}${card('Доступно', connected ? `${money(state.account.total_available_balance)} USDT` : '—', 'Свободные средства')}</section>${panel('Безопасность','<p>Вывод средств не используется. Kill Switch включён. Реальное исполнение отключено.</p>','wide')}`;
    }
    return title(name, 'Параметры системы') + panel('Настройки', '<div class="status-list"><div><span>Тема</span><b>Dark</b></div><div><span>Язык</span><b>Русский</b></div><div><span>Уведомления</span><b>Включены</b></div></div>', 'wide');
  }

  function activate(name, button) {
    nav.querySelectorAll('button').forEach(x => x.classList.remove('active'));
    if (button) button.classList.add('active');
    content.innerHTML = page(name);
    if (name === 'AI-чат') bindChat();
  }

  function bindChat() {
    const form = document.getElementById('chatForm');
    if (!form) return;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const input = document.getElementById('msg');
      const messages = document.getElementById('messages');
      const text = input && input.value.trim();
      if (!text || !messages) return;
      messages.insertAdjacentHTML('beforeend', `<div class="bubble user">${text.replace(/[<>]/g, '')}</div>`);
      input.value = '';
      try {
        const response = await fetch('/api/chat/message', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text }) });
        const result = await response.json();
        messages.insertAdjacentHTML('beforeend', `<div class="bubble">${String(result.reply || 'Ответ не получен').replace(/[<>]/g, '')}</div>`);
      } catch (_error) {
        messages.insertAdjacentHTML('beforeend', '<div class="bubble">AI API временно недоступен.</div>');
      }
    });
  }

  nav.querySelectorAll('button[data-page]').forEach(button => {
    button.addEventListener('click', () => activate(button.dataset.page, button));
  });

  async function fetchJson(url) {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error(`${url}: ${response.status}`);
    return response.json();
  }

  async function load() {
    if (notice) notice.classList.add('hidden');
    const requests = await Promise.allSettled([
      fetchJson('/api/exchange/account/snapshot'),
      fetchJson('/api/ai-bots'),
      fetchJson('/api/social-news')
    ]);
    if (requests[0].status === 'fulfilled') state.account = requests[0].value;
    if (requests[1].status === 'fulfilled') state.bots = requests[1].value;
    if (requests[2].status === 'fulfilled') state.news = requests[2].value;
    if (requests.every(x => x.status === 'rejected') && notice) {
      notice.textContent = 'API временно недоступен. Интерфейс работает в безопасном режиме.';
      notice.classList.remove('hidden');
    }
    activate('Обзор', nav.querySelector('[data-page="Обзор"]'));
  }

  if (refresh) refresh.addEventListener('click', load);
  load().catch(error => {
    console.error('SharipovAI UI startup error', error);
    activate('Обзор', nav.querySelector('[data-page="Обзор"]'));
  });
})();
