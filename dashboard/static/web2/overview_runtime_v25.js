(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const num = (value, digits=4) => Number.isFinite(Number(value)) ? Number(value).toLocaleString('ru-RU',{maximumFractionDigits:digits}) : '—';
  const arr = (...values) => values.find(Array.isArray) || [];
  const state = { virtual:null, bots:null, news:null, run:null, quote:null, health:null, loadedAt:null, errors:{} };

  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === 'overview';
  const get = async (url) => { const response=await fetch(url,{credentials:'same-origin',cache:'no-store'}); if(!response.ok) throw new Error(String(response.status)); return response.json(); };
  const card = (label,value,note='',tone='') => `<article class="card"><span>${esc(label)}</span><strong class="${esc(tone)}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
  const panel = (heading,body,wide='') => `<article class="panel ${wide}"><small>SHARIPOVAI</small><h2>${esc(heading)}</h2>${body}</article>`;
  const empty = (text) => `<div class="empty">${esc(text)}</div>`;
  const row = (label,value,tone='') => `<div class="v10-row"><span>${esc(label)}</span><b class="${esc(tone)}">${esc(value)}</b></div>`;

  function virtualData(){
    const raw=state.virtual||{};
    const root=raw.state&&typeof raw.state==='object'?raw.state:raw;
    return {summary:root.summary||raw.summary||{},trades:arr(root.trades,raw.trades,root.orders,root.history)};
  }
  function botList(){ return arr(state.bots?.bots,state.bots?.items,state.bots?.agents,state.bots); }
  function newsList(){ return arr(state.news?.news?.items,state.news?.news,state.news?.items,state.news?.articles,state.news); }
  function freshBot(bot){ const age=Number(bot?.heartbeat_age_seconds); return Number.isFinite(age)&&age<90; }

  function render(){
    if(!active()) return;
    const content=$('content'); if(!content) return;
    const virtual=virtualData(), s=virtual.summary, trades=virtual.trades;
    const bots=botList(), verified=bots.filter(freshBot).length;
    const news=newsList().slice(0,5);
    const quote=state.quote||{};
    const open=Number(s.open_positions??trades.filter(x=>String(x.status).toUpperCase()==='OPEN').length)||0;
    const closed=Number(s.closed_positions??trades.filter(x=>String(x.status).toUpperCase()==='CLOSED').length)||0;
    const pnl=Number(s.net_pnl);
    const health=state.health||{};
    const components=arr(health.components);
    const healthy=components.filter(x=>x.status==='healthy').length;
    const unavailable=Object.keys(state.errors).length;
    const latest=trades.slice().reverse().slice(0,5);
    const tradeRows=latest.length?`<table class="v10-table"><thead><tr><th>Пара</th><th>Сторона</th><th>Статус</th><th>Net PnL</th><th>Причина</th></tr></thead><tbody>${latest.map(x=>`<tr><td>${esc(x.symbol||x.asset||'—')}</td><td>${esc(x.side||'—')}</td><td>${esc(x.status||'—')}</td><td>${esc(num(x.net_pnl))}</td><td>${esc(x.close_reason_ru||x.reason_ru||'—')}</td></tr>`).join('')}</tbody></table>`:empty('Виртуальные операции пока не получены.');
    const newsRows=news.length?news.map(x=>`<div class="news-item"><b>${esc(x.title||x.headline||'Новость')}</b><small>${esc(x.source||x.publisher||'Источник не указан')}</small></div>`).join(''):empty('Подтверждённые новости пока не получены.');
    content.innerHTML=`<div class="title"><h1>Центр управления</h1><p>Рабочая сводка по виртуальному счёту, рынку, ИИ и источникам</p></div>
      <section class="metrics">
        ${card('Капитал',s.equity!=null?num(s.equity)+' USDT':'—','Виртуальный счёт · рыночный PnL')}
        ${card('Доступно',s.cash!=null?num(s.cash)+' USDT':'—','Свободный виртуальный капитал')}
        ${card('Открытые позиции',String(open),'По подтверждённым котировкам')}
        ${card('Закрытые сделки',String(closed),'Фактический журнал')}
        ${card('Net PnL',Number.isFinite(pnl)?num(pnl)+' USDT':'—','С учётом комиссий',Number.isFinite(pnl)?(pnl>=0?'positive':'negative'):'')}
        ${card('ИИ с подтверждением',`${verified}/${bots.length}`,'Сигнал до 90 секунд',verified?'positive':'')}
      </section>
      <section class="v10-grid">
        ${panel('Рынок',quote.price!=null?`${row('BTCUSDT',num(quote.price)+' USDT','positive')}${row('Источник',quote.source||'Bybit')}${row('Получено',quote.received_at||quote.timestamp||'—')}`:empty('Котировка BTCUSDT не получена.'))}
        ${panel('Последние виртуальные сделки',tradeRows,'wide')}
        ${panel('Новости',newsRows)}
        ${panel('Состояние контуров',`${row('Компоненты в норме',components.length?`${healthy}/${components.length}`:'API состояния не передал список')}${row('Недоступные запросы',String(unavailable),unavailable?'negative':'positive')}${row('Реальные ордера',s.real_orders_blocked===false?'РАЗРЕШЕНЫ':'ЗАБЛОКИРОВАНЫ',s.real_orders_blocked===false?'negative':'positive')}${row('Рыночный учёт PnL',s.market_price_accounting===true?'ПОДТВЕРЖДЁН':'НЕ ПОДТВЕРЖДЁН',s.market_price_accounting===true?'positive':'negative')}${row('Обновлено',state.loadedAt||'—')}`)}
      </section>`;
  }

  async function load(){
    if(!active()) return;
    const entries=[
      ['virtual','/api/virtual-account/state'],['bots','/api/ai-bots'],['news','/api/social-news'],
      ['run','/api/run'],['quote','/api/market/quote/BTCUSDT'],['health','/api/system/health'],
    ];
    const results=await Promise.allSettled(entries.map(([,url])=>get(url)));
    state.errors={};
    results.forEach((result,index)=>{ const key=entries[index][0]; if(result.status==='fulfilled') state[key]=result.value; else state.errors[key]=result.reason?.message||'недоступно'; });
    state.loadedAt=new Date().toLocaleString('ru-RU');
    render();
  }

  document.addEventListener('click',(event)=>{
    const button=event.target.closest('#nav button[data-page="overview"]');
    if(button) setTimeout(()=>load().catch(()=>{}),0);
  });
  $('refresh')?.addEventListener('click',()=>{ if(active()) setTimeout(()=>load().catch(()=>{}),0); });
  window.addEventListener('DOMContentLoaded',()=>{ if(active()) load().catch(()=>{}); });
  setInterval(()=>{ if(active()&&!document.hidden) load().catch(()=>{}); },10000);
})();
