(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const arr = (...values) => values.find(Array.isArray) || [];
  const symbols = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','ADAUSDT'];
  const state = { virtual:null, bots:null, news:null, run:null, quotes:{}, health:null, loadedAt:null, errors:{}, symbol:savedSymbol() };

  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === 'overview';
  const get = async (url) => { const response=await fetch(url,{credentials:'same-origin',cache:'no-store'}); if(!response.ok) throw new Error(String(response.status)); return response.json(); };
  const money = (value) => Number.isFinite(Number(value)) ? Number(value).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1}) : '—';
  const resultMoney = (value) => Number.isFinite(Number(value)) ? Number(value).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1}) : '—';
  const price = (value) => {
    const number=Number(value); if(!Number.isFinite(number)) return '—';
    const digits=Math.abs(number)>=100?1:Math.abs(number)>=10?2:4;
    return number.toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits});
  };
  const percent = (value) => Number.isFinite(Number(value)) ? `${Number(value).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})}%` : '—';
  const card = (label,value,note='',tone='') => `<article class="card"><span>${esc(label)}</span><strong class="${esc(tone)}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
  const panel = (heading,body,wide='') => `<article class="panel ${wide}"><small>SHARIPOVAI</small><h2>${esc(heading)}</h2>${body}</article>`;
  const empty = (text) => `<div class="empty">${esc(text)}</div>`;
  const row = (label,value,tone='') => `<div class="v10-row"><span>${esc(label)}</span><b class="${esc(tone)}">${esc(value)}</b></div>`;

  function savedSymbol(){
    let candidate=localStorage.getItem('sharipovai-market-symbol')||'';
    try{candidate ||= JSON.parse(localStorage.getItem('sharipovai-settings')||'{}').defaultSymbol||'';}catch{}
    candidate=String(candidate).replace(/[^A-Za-z0-9]/g,'').toUpperCase();
    return symbols.includes(candidate)?candidate:'BTCUSDT';
  }
  function virtualData(){
    const raw=state.virtual||{};
    const root=raw.state&&typeof raw.state==='object'?raw.state:raw;
    return {summary:root.summary||raw.summary||{},trades:arr(root.trades,raw.trades,root.orders,root.history)};
  }
  function botList(){ return arr(state.bots?.bots,state.bots?.items,state.bots?.agents,state.bots); }
  function newsList(){ return arr(state.news?.news?.items,state.news?.news,state.news?.items,state.news?.articles,state.news); }
  function freshBot(bot){ const age=Number(bot?.heartbeat_age_seconds); return Number.isFinite(age)&&age<90; }
  function actionLabel(trade){
    const side=String(trade.side||'').toUpperCase();
    return side==='BUY'?'BUY · покупка':side==='SELL'?'SELL · продажа':side||'—';
  }
  function fallbackEntryReason(trade){
    if(trade.entry_reason_ru) return trade.entry_reason_ru;
    const side=String(trade.side||'').toUpperCase();
    const change=Number(trade.signal_change_24h_percent);
    const symbol=trade.symbol||trade.asset||'актив';
    if(!Number.isFinite(change)) return 'Причина входа не сохранена в старой записи.';
    if(side==='BUY') return `Покупка ${symbol}: рост за 24 часа ${percent(change)} превысил порог 0,35%; стратегия открыла BUY по тренду.`;
    if(side==='SELL') return `Продажа ${symbol}: изменение за 24 часа ${percent(change)} по модулю превысило порог 0,35%; стратегия открыла виртуальный SELL по тренду.`;
    return 'Направление операции не определено.';
  }
  function operationReason(trade){
    if(trade.operation_explanation_ru) return trade.operation_explanation_ru;
    const entry=fallbackEntryReason(trade);
    const closed=String(trade.status||'').toUpperCase()==='CLOSED';
    return closed?`${entry} Закрытие: ${trade.close_reason_ru||'причина закрытия не сохранена'}.`:`${entry} Позиция ещё открыта.`;
  }
  function quoteTable(){
    const rows=symbols.map(symbol=>{
      const quote=state.quotes[symbol]||{};
      const change=Number(quote.change_24h_percent);
      const tone=Number.isFinite(change)?(change>=0?'positive':'negative'):'';
      return `<tr data-overview-symbol="${symbol}" class="${symbol===state.symbol?'selected':''}"><td><b>${esc(symbol.replace('USDT','/USDT'))}</b></td><td>${esc(price(quote.price))} USDT</td><td class="${tone}">${esc(percent(change))}</td><td>${esc(quote.source||'—')}</td></tr>`;
    }).join('');
    return `<div class="status-actions"><label>Валюта <select id="overviewSymbol">${symbols.map(symbol=>`<option value="${symbol}" ${symbol===state.symbol?'selected':''}>${symbol.replace('USDT','/USDT')}</option>`).join('')}</select></label><button id="overviewOpenMarket" class="action" type="button">Открыть рыночный терминал</button></div><table class="v10-table"><thead><tr><th>Пара</th><th>Цена</th><th>24 часа</th><th>Источник</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function render(){
    if(!active()) return;
    const content=$('content'); if(!content) return;
    const virtual=virtualData(), s=virtual.summary, trades=virtual.trades;
    const bots=botList(), verified=bots.filter(freshBot).length;
    const news=newsList().slice(0,5);
    const quote=state.quotes[state.symbol]||{};
    const open=Number(s.open_positions??trades.filter(x=>String(x.status).toUpperCase()==='OPEN').length)||0;
    const closed=Number(s.closed_positions??trades.filter(x=>String(x.status).toUpperCase()==='CLOSED').length)||0;
    const pnl=Number(s.net_pnl);
    const health=state.health||{};
    const components=arr(health.components);
    const healthy=components.filter(x=>x.status==='healthy').length;
    const unavailable=Object.keys(state.errors).length;
    const latest=trades.slice().reverse().slice(0,8);
    const tradeRows=latest.length?`<table class="v10-table"><thead><tr><th>Пара</th><th>Операция</th><th>Статус</th><th>Вход</th><th>Текущая / выход</th><th>Net PnL</th><th>Почему ИИ открыл или закрыл</th></tr></thead><tbody>${latest.map(x=>`<tr><td>${esc(x.symbol||x.asset||'—')}</td><td>${esc(actionLabel(x))}</td><td>${esc(x.status||'—')}</td><td>${esc(price(x.entry_price))}</td><td>${esc(price(x.exit_price??x.current_price))}</td><td class="${Number(x.net_pnl)>=0?'positive':'negative'}">${esc(resultMoney(x.net_pnl))} USDT</td><td>${esc(operationReason(x))}</td></tr>`).join('')}</tbody></table>`:empty('Виртуальные операции пока не получены.');
    const newsRows=news.length?news.map(x=>`<div class="news-item"><b>${esc(x.title||x.headline||'Новость')}</b><small>${esc(x.source||x.publisher||'Источник не указан')}</small></div>`).join(''):empty('Подтверждённые новости пока не получены.');
    content.innerHTML=`<div class="title"><h1>Центр управления</h1><p>Рабочая сводка по виртуальному счёту, рынку, ИИ и источникам</p></div>
      <section class="metrics">
        ${card('Капитал',s.equity!=null?money(s.equity)+' USDT':'—','Виртуальный счёт · рыночный PnL')}
        ${card('Доступно',s.cash!=null?money(s.cash)+' USDT':'—','Свободный виртуальный капитал')}
        ${card('Открытые позиции',String(open),'По подтверждённым котировкам')}
        ${card('Закрытые сделки',String(closed),'Фактический журнал')}
        ${card('Net PnL',Number.isFinite(pnl)?resultMoney(pnl)+' USDT':'—','С учётом комиссий',Number.isFinite(pnl)?(pnl>=0?'positive':'negative'):'')}
        ${card('ИИ с подтверждением',`${verified}/${bots.length}`,'Сигнал до 90 секунд',verified?'positive':'')}
      </section>
      <section class="v10-grid">
        ${panel(`Рынок · ${state.symbol.replace('USDT','/USDT')}`,quote.price!=null?`${row('Цена',price(quote.price)+' USDT','positive')}${row('24 часа',percent(quote.change_24h_percent),Number(quote.change_24h_percent)>=0?'positive':'negative')}${row('Источник',quote.source||'Bybit')}${row('Получено',quote.received_at||quote.timestamp||'—')}${quoteTable()}`:quoteTable(),'wide')}
        ${panel('Последние виртуальные операции',tradeRows,'wide')}
        ${panel('Новости',newsRows)}
        ${panel('Состояние контуров',`${row('Компоненты в норме',components.length?`${healthy}/${components.length}`:'API состояния не передал список')}${row('Недоступные запросы',String(unavailable),unavailable?'negative':'positive')}${row('Реальные ордера',s.real_orders_blocked===false?'РАЗРЕШЕНЫ':'ЗАБЛОКИРОВАНЫ',s.real_orders_blocked===false?'negative':'positive')}${row('Рыночный учёт PnL',s.market_price_accounting===true?'ПОДТВЕРЖДЁН':'НЕ ПОДТВЕРЖДЁН',s.market_price_accounting===true?'positive':'negative')}${row('Обновлено',state.loadedAt||'—')}`)}
      </section>`;
    bindOverviewControls();
  }

  function bindOverviewControls(){
    $('overviewSymbol')?.addEventListener('change',(event)=>{
      state.symbol=symbols.includes(event.target.value)?event.target.value:'BTCUSDT';
      localStorage.setItem('sharipovai-market-symbol',state.symbol);
      render();
    });
    document.querySelectorAll('[data-overview-symbol]').forEach(rowElement=>rowElement.addEventListener('click',()=>{
      state.symbol=rowElement.dataset.overviewSymbol;
      localStorage.setItem('sharipovai-market-symbol',state.symbol);
      render();
    }));
    $('overviewOpenMarket')?.addEventListener('click',()=>{
      localStorage.setItem('sharipovai-market-symbol',state.symbol);
      document.querySelector('#nav button[data-page="market"]')?.click();
    });
  }

  async function load(){
    if(!active()) return;
    const entries=[
      ['virtual','/api/virtual-account/state'],['bots','/api/ai-bots'],['news','/api/social-news'],
      ['run','/api/run'],['health','/api/system/health'],
    ];
    const [coreResults,quoteResults]=await Promise.all([
      Promise.allSettled(entries.map(([,url])=>get(url))),
      Promise.allSettled(symbols.map(symbol=>get(`/api/market/quote/${symbol}`))),
    ]);
    state.errors={};
    coreResults.forEach((result,index)=>{const key=entries[index][0];if(result.status==='fulfilled')state[key]=result.value;else state.errors[key]=result.reason?.message||'недоступно';});
    quoteResults.forEach((result,index)=>{const symbol=symbols[index];if(result.status==='fulfilled')state.quotes[symbol]=result.value;else state.errors[`quote_${symbol}`]=result.reason?.message||'недоступно';});
    state.loadedAt=new Date().toLocaleString('ru-RU');
    render();
  }

  document.addEventListener('click',(event)=>{const button=event.target.closest('#nav button[data-page="overview"]');if(button)setTimeout(()=>load().catch(()=>{}),0);});
  $('refresh')?.addEventListener('click',()=>{if(active())setTimeout(()=>load().catch(()=>{}),0);});
  window.addEventListener('DOMContentLoaded',()=>{if(active())load().catch(()=>{});});
  setInterval(()=>{if(active()&&!document.hidden)load().catch(()=>{});},10000);
})();
