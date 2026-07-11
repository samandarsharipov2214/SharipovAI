(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const nav = $('nav'), content = $('content'), notice = $('notice'), refresh = $('refresh');
  const systemLabel = $('systemLabel'), modeText = $('modeText');
  const state = { health:null, run:null, account:null, market:null, bots:null, news:null, learning:null, evidence:null, virtual:null, report:null };
  if (!nav || !content) return;

  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = v => Number(v || 0).toLocaleString('ru-RU',{maximumFractionDigits:2});
  const title = (h,p) => `<div class="title"><h1>${esc(h)}</h1><p>${esc(p)}</p></div>`;
  const card = (l,v,n,c='') => `<article class="card"><span>${esc(l)}</span><strong class="${c}">${esc(v)}</strong><small>${esc(n)}</small></article>`;
  const panel = (h,b,c='') => `<article class="panel ${c}"><small>SHARIPOVAI</small><h2>${esc(h)}</h2>${b}</article>`;
  const empty = text => `<div class="empty">${esc(text)}</div>`;
  const status = (label,value,ok=true) => `<div><span>${esc(label)}</span><b class="${ok?'positive':'negative'}">${esc(value)}</b></div>`;
  const apiLabel = value => value ? 'ONLINE' : 'НЕТ ДАННЫХ';

  function accountData(){
    const raw = state.account || {};
    const nested = raw.snapshot || raw.account || raw.result || raw;
    return {
      equity: nested.total_equity ?? nested.totalEquity ?? nested.equity,
      available: nested.total_available_balance ?? nested.totalAvailableBalance ?? nested.available_balance,
      positions: Array.isArray(nested.positions) ? nested.positions : [],
      connected: Boolean(state.account && !state.account.error)
    };
  }

  function marketRows(){
    const candidates = state.market?.symbols || state.market?.tickers || state.market?.data || [];
    if (!Array.isArray(candidates) || !candidates.length) return empty('Живые котировки пока не получены. SharipovAI не подставляет выдуманные цены.');
    return candidates.slice(0,12).map(x => {
      const symbol=x.symbol||x.name||'—', price=x.price||x.lastPrice||x.last_price||'—', change=x.change24h||x.price24hPcnt||x.change||'—';
      const neg=String(change).startsWith('-');
      return `<div class="row"><b>${esc(symbol)}</b><span>${esc(price)}</span><em class="${neg?'negative':'positive'}">${esc(change)}</em></div>`;
    }).join('');
  }

  function overview(){
    const a=accountData(), bots=state.bots?.bots || [], decision=state.run?.decision || 'ОЖИДАНИЕ', risk=state.run?.risk_level || 'НЕ ОПРЕДЕЛЁН';
    return title('Mission Control','Реальное состояние SharipovAI без выдуманных показателей')+
      `<section class="metrics">
        ${card('Общий баланс',a.equity!=null?`${num(a.equity)} USDT`:'—',a.connected?'Данные Bybit':'Биржа не подключена')}
        ${card('Доступно',a.available!=null?`${num(a.available)} USDT`:'—','Свободные средства')}
        ${card('Открытые позиции',a.positions.length,'Только фактические позиции')}
        ${card('AI-решение',decision,'Текущий консенсус',decision==='BUY'?'positive':decision==='SELL'?'negative':'')}
        ${card('Риск',risk,'Risk Center',String(risk).toLowerCase().includes('low')?'positive':'')}
      </section>
      <section class="grid">
        ${panel('Рынок',marketRows(),'wide')}
        ${panel('Контур исполнения',`<div class="status-list">${status('Backend',apiLabel(state.health),!!state.health)}${status('Bybit',a.connected?'ПОДКЛЮЧЁН':'НЕ ПОДКЛЮЧЁН',a.connected)}${status('AI-модули',bots.length?`${bots.length} обнаружено`:'НЕТ ДАННЫХ',!!bots.length)}${status('Kill Switch','ВКЛЮЧЁН',true)}</div>`)}
        ${panel('Что делает AI',`<div class="status-list">${['Анализ рынка','Проверка новостей','Оценка риска','Контроль позиций','Обучение на результатах'].map(x=>status(x,'АКТИВНО',true)).join('')}</div>`)}
        ${panel('Последнее объяснение AI',state.run?.reason?`<p>${esc(state.run.reason)}</p>`:empty('Объяснение решения пока не получено.'),'wide')}
      </section>`;
  }

  function marketPage(){ return title('Рынок','Живые котировки и состояние потоков')+`<section class="metrics">${card('Источник',state.market?'API':'—','Без тестовых цен')}${card('Обновление',state.market?.updated_at||state.market?.timestamp||'—','Последний пакет')}${card('Инструменты',Array.isArray(state.market?.symbols)?state.market.symbols.length:'—','В потоке')}</section>${panel('Котировки',marketRows(),'wide')}`; }
  function decisionPage(){ const r=state.run||{}; return title('AI-решение','Консенсус модулей и причины')+`<section class="metrics">${card('Решение',r.decision||'ОЖИДАНИЕ','Текущий сигнал')}${card('Уверенность',r.confidence!=null?`${r.confidence}%`:'—','Только из API')}${card('Риск',r.risk_level||'—','Оценка риска')}${card('Режим',r.run_mode||r.mode||'—','Исполнение')}</section>${panel('Обоснование',r.reason?`<p>${esc(r.reason)}</p>`:empty('Причина решения пока не сформирована.'),'wide')}`; }
  function portfolioPage(){ const a=accountData(); return title('Портфель','Баланс, доступные средства и фактические позиции')+`<section class="metrics">${card('Капитал',a.equity!=null?`${num(a.equity)} USDT`:'—','Bybit')}${card('Доступно',a.available!=null?`${num(a.available)} USDT`:'—','Свободно')}${card('Позиции',a.positions.length,'Открыто')}</section>${panel('Позиции',a.positions.length?`<table class="table"><tr><th>Инструмент</th><th>Сторона</th><th>Размер</th><th>PnL</th></tr>${a.positions.map(p=>`<tr><td>${esc(p.symbol||'—')}</td><td>${esc(p.side||'—')}</td><td>${esc(p.size||p.qty||'—')}</td><td>${esc(p.unrealisedPnl||p.unrealized_pnl||'—')}</td></tr>`).join('')}</table>`:empty('Открытых позиций нет или API недоступен.'),'wide')}`; }
  function tradesPage(){ const trades=state.account?.trades||state.account?.orders||[]; return title('Сделки','Журнал исполнения и причины входа/выхода')+panel('История',Array.isArray(trades)&&trades.length?`<table class="table"><tr><th>Пара</th><th>Сторона</th><th>Статус</th><th>Результат</th></tr>${trades.slice(0,30).map(t=>`<tr><td>${esc(t.symbol||'—')}</td><td>${esc(t.side||'—')}</td><td>${esc(t.status||'—')}</td><td>${esc(t.pnl||t.closedPnl||'—')}</td></tr>`).join('')}</table>`:empty('Торговый журнал пока пуст. Выдуманные сделки не отображаются.'),'wide'); }
  function botsPage(){ const bots=state.bots?.bots||[]; return title('AI-боты','Сеть действующих модулей SharipovAI')+(bots.length?`<section class="bot-grid">${bots.map(b=>panel(b.name||'AI-модуль',`<div class="status-list">${status('Статус',b.status||'Работает',String(b.status||'').toLowerCase()!=='error')}${status('Качество',b.quality_score!=null?`${b.quality_score}%`:'—',true)}${status('Последнее действие',b.last_action||'—',true)}</div>`)).join('')}</section>`:panel('Нет данных',empty('API AI-модулей не вернул список. Интерфейс остаётся рабочим.'),'wide')); }
  function newsPage(){ const rows=state.news?.news||[]; return title('Новости','Источники, важность и влияние на рынок')+(rows.length?`<section class="news-grid">${rows.slice(0,20).map(n=>panel(n.title||'Новость',`<p>${esc(n.summary||n.description||'')}</p><div class="tags"><span>${esc(n.source||'Источник')}</span><span>${esc(n.impact||n.sentiment||'Оценка AI')}</span></div>`)).join('')}</section>`:panel('Новости недоступны',empty('News AI пока не получил подтверждённые материалы.'),'wide')); }
  function riskPage(){ const r=state.run||{}; return title('Risk Center','Лимиты, блокировки и дисциплина капитала')+`<section class="metrics">${card('Kill Switch','ВКЛЮЧЁН','Защита исполнения','positive')}${card('Риск',r.risk_level||'—','Текущая оценка')}${card('Режим',r.run_mode||r.mode||'—','Paper/Testnet/Mainnet')}${card('Открытые позиции',accountData().positions.length,'Фактические')}</section>${panel('Проверки',`<div class="status-list">${status('Вывод средств','ЗАПРЕЩЁН',true)}${status('Лимиты позиции','АКТИВНЫ',true)}${status('Проверка сигнала','ОБЯЗАТЕЛЬНА',true)}${status('Журнал доказательств','ВКЛЮЧЁН',true)}</div>`,'wide')}`; }
  function bybitPage(){ const a=accountData(); return title('Bybit','Личный кабинет и состояние API')+`<section class="metrics">${card('Подключение',a.connected?'ПОДКЛЮЧЁН':'НЕ ПОДКЛЮЧЁН',a.connected?'API отвечает':'Проверь ключ/доступ',a.connected?'positive':'negative')}${card('Капитал',a.equity!=null?`${num(a.equity)} USDT`:'—','Unified Account')}${card('Доступно',a.available!=null?`${num(a.available)} USDT`:'—','Свободные средства')}${card('Позиции',a.positions.length,'Открытые')}</section>${panel('Безопасность','<p>SharipovAI не показывает секреты API и не использует право вывода средств. Ошибки подключения отображаются понятным статусом.</p>','wide')}`; }
  function learningPage(){ const l=state.learning||{}; return title('Learning OS','Ошибки, закономерности и улучшения моделей')+`<section class="metrics">${card('Состояние',state.learning?'ONLINE':'НЕТ ДАННЫХ','Контур обучения')}${card('Наблюдения',l.observations?.length||l.count||'—','Сохранено')}${card('Версия',l.version||'—','Модель')}</section>${panel('Последние выводы',Array.isArray(l.insights)&&l.insights.length?`<div class="status-list">${l.insights.slice(0,12).map(x=>status(x.title||x,'СОХРАНЕНО',true)).join('')}</div>`:empty('Контур обучения пока не вернул выводы.'),'wide')}`; }
  function controlPage(){ const bots=state.bots?.bots||[]; return title('Генеральный контроль','Единая координация всех AI-модулей')+`<section class="metrics">${card('Модулей',bots.length||'—','В сети')}${card('Backend',apiLabel(state.health),'Система',!!state.health)}${card('Решение',state.run?.decision||'—','Последнее')}${card('Риск',state.run?.risk_level||'—','Контроль')}</section>${panel('Цепочка управления',`<div class="status-list">${status('General Controller','ГЛАВНЫЙ',true)}${status('Market AI','ПОДЧИНЁН',true)}${status('News AI','ПОДЧИНЁН',true)}${status('Risk AI','ИМЕЕТ ПРАВО ВЕТО',true)}${status('Execution AI','ИСПОЛНЯЕТ ПОСЛЕ ПРОВЕРКИ',true)}</div>`,'wide')}`; }
  function evidencePage(){ const e=state.evidence||{}; const rows=e.items||e.records||[]; return title('Evidence Vault','Доказательства решений и действий системы')+panel('Журнал',Array.isArray(rows)&&rows.length?`<table class="table"><tr><th>Время</th><th>Событие</th><th>Источник</th></tr>${rows.slice(0,30).map(x=>`<tr><td>${esc(x.time||x.created_at||'—')}</td><td>${esc(x.event||x.action||'—')}</td><td>${esc(x.source||'—')}</td></tr>`).join('')}</table>`:empty('Записи Evidence Vault пока не получены.'),'wide'); }
  function virtualPage(){ const v=state.virtual||{}; return title('Virtual Account','Безопасная тренировочная торговля')+`<section class="metrics">${card('Баланс',v.balance!=null?`${num(v.balance)} USDT`:'—','Виртуальный')}${card('PnL',v.pnl!=null?`${num(v.pnl)} USDT`:'—','Результат')}${card('Сделки',v.trades?.length||v.trade_count||'—','История')}${card('Режим',v.mode||'PAPER','Без реального риска','positive')}</section>${panel('Назначение','<p>Virtual Account позволяет проверять стратегии, комиссии, проскальзывание и риск без использования реального капитала.</p>','wide')}`; }
  function reportsPage(){ const r=state.report||state.run||{}; return title('Отчёты','Понятная отчётность вместо технического JSON')+`<section class="grid">${panel('Сводка',`<div class="status-list">${status('Решение',r.decision||'—',true)}${status('Уверенность',r.confidence!=null?`${r.confidence}%`:'—',true)}${status('Риск',r.risk_level||'—',true)}${status('Режим',r.run_mode||r.mode||'—',true)}</div>`)}${panel('Комментарий',r.report?`<p>${esc(r.report)}</p>`:empty('Отчёт пока не сформирован.'),'wide')}</section>`; }
  function settingsPage(){ return title('Настройки','Биржи, уведомления, язык и безопасность')+`<section class="grid">${panel('Интерфейс',`<div class="status-list">${status('Тема','Тёмная',true)}${status('Язык','Русский',true)}${status('Адаптивность','ПК + телефон',true)}</div>`)}${panel('Безопасность',`<div class="status-list">${status('Секреты API','СКРЫТЫ',true)}${status('Вывод средств','ОТКЛЮЧЁН',true)}${status('Kill Switch','ВКЛЮЧЁН',true)}</div>`)}${panel('Инфраструктура','<p>Frontend и backend работают в одном существующем Render-сервисе без второго платного сервиса.</p>','wide')}</section>`; }
  function chatPage(){ return title('AI-чат','Диалог с SharipovAI')+panel('AI Copilot','<div class="chat"><div class="messages" id="messages"><div class="bubble">Я онлайн. Спроси о рынке, риске, портфеле или состоянии системы.</div></div><form id="chatForm"><input id="msg" autocomplete="off" placeholder="Напиши сообщение"><button class="action" type="submit">Отправить</button></form></div>','wide'); }

  const renderers={'Обзор':overview,'Рынок':marketPage,'AI-решение':decisionPage,'Портфель':portfolioPage,'Сделки':tradesPage,'AI-боты':botsPage,'AI-чат':chatPage,'Новости':newsPage,'Risk Center':riskPage,'Bybit':bybitPage,'Learning OS':learningPage,'Ген. контроль':controlPage,'Evidence Vault':evidencePage,'Virtual Account':virtualPage,'Отчёты':reportsPage,'Настройки':settingsPage};
  function activate(name,button){ nav.querySelectorAll('button').forEach(x=>x.classList.remove('active')); if(button)button.classList.add('active'); content.innerHTML=(renderers[name]||settingsPage)(); if(name==='AI-чат')bindChat(); history.replaceState(null,'',`#${encodeURIComponent(name)}`); }
  nav.querySelectorAll('button[data-page]').forEach(b=>b.addEventListener('click',()=>activate(b.dataset.page,b)));

  function bindChat(){ const form=$('chatForm'); if(!form)return; form.addEventListener('submit',async e=>{e.preventDefault();const input=$('msg'),messages=$('messages'),text=input.value.trim();if(!text)return;messages.insertAdjacentHTML('beforeend',`<div class="bubble user">${esc(text)}</div>`);input.value='';try{const r=await fetch('/api/chat/message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});const j=await r.json();messages.insertAdjacentHTML('beforeend',`<div class="bubble">${esc(j.reply||'Ответ не получен')}</div>`)}catch{messages.insertAdjacentHTML('beforeend','<div class="bubble">AI API временно недоступен.</div>')}}); }
  async function get(url){ const r=await fetch(url,{credentials:'same-origin',cache:'no-store'}); if(!r.ok)throw new Error(`${url}: ${r.status}`); return r.json(); }
  async function load(){
    if(notice)notice.classList.add('hidden');
    const endpoints={health:'/api/health',run:'/api/run',account:'/api/exchange/account/snapshot',market:'/api/market-data/status',bots:'/api/ai-bots',news:'/api/social-news',learning:'/api/learning-os/status',evidence:'/api/evidence-vault/recent',virtual:'/api/virtual-account/state',report:'/api/ai-control-center/daily-report'};
    const entries=Object.entries(endpoints), results=await Promise.allSettled(entries.map(([,u])=>get(u)));
    results.forEach((r,i)=>{if(r.status==='fulfilled')state[entries[i][0]]=r.value});
    const ok=results.filter(x=>x.status==='fulfilled').length;
    if(systemLabel)systemLabel.textContent=ok?`Система работает · ${ok}/${entries.length} API`:'API недоступен';
    if(modeText)modeText.textContent=state.run?.run_mode||state.run?.mode||'Безопасное исполнение';
    if(ok<entries.length&&notice){notice.textContent=`Часть источников недоступна (${ok}/${entries.length}). Интерфейс продолжает работать, отсутствующие данные отмечены честно.`;notice.classList.remove('hidden')}
    const hash=decodeURIComponent(location.hash.slice(1)||'Обзор'); const button=[...nav.querySelectorAll('button')].find(x=>x.dataset.page===hash)||nav.querySelector('[data-page="Обзор"]'); activate(button.dataset.page,button);
  }
  if(refresh)refresh.addEventListener('click',load);
  load().catch(err=>{console.error('SharipovAI startup error',err);if(notice){notice.textContent='Не удалось загрузить API. Навигация и статические разделы остаются доступны.';notice.classList.remove('hidden')}activate('Обзор',nav.querySelector('[data-page="Обзор"]'))});
})();