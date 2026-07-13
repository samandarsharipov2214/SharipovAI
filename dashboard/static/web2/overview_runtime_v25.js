(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[char]));
  const arr = (...values) => values.find(Array.isArray) || [];
  const symbols = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','ADAUSDT'];
  const state = {
    virtual:null, bots:null, news:null, run:null, quotes:{}, health:null, fx:null, fxError:'',
    loadedAt:null, errors:{}, symbol:savedSymbol(), displayCurrency:savedCurrency(),
  };

  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === 'overview';
  const get = async (url) => { const response=await fetch(url,{credentials:'same-origin',cache:'no-store'}); if(!response.ok) throw new Error(String(response.status)); return response.json(); };
  const finite = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
  const money = (value, digits=1) => finite(value) != null ? Number(value).toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits}) : '—';
  const signed = (value, digits=2) => {
    const number=finite(value); if(number==null) return '—';
    const prefix=number>0?'+':'';
    return `${prefix}${number.toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits})}`;
  };
  const rubles = (value) => finite(value) != null ? Math.round(Number(value)).toLocaleString('ru-RU') : '—';
  const quantity = (value) => finite(value) != null ? Number(value).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:8}) : '—';
  const price = (value) => {
    const number=finite(value); if(number==null) return '—';
    const digits=Math.abs(number)>=100?1:Math.abs(number)>=10?2:4;
    return number.toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits});
  };
  const percent = (value, digits=2) => finite(value) != null ? `${Number(value).toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits})}%` : '—';
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
  function savedCurrency(){
    const candidate=String(localStorage.getItem('sharipovai-display-currency')||'RUB').toUpperCase();
    return candidate==='USDT'?'USDT':'RUB';
  }
  function fxRate(){
    const rate=finite(state.fx?.rub_per_usdt_estimate??state.fx?.rub_per_usd);
    return rate!=null&&rate>0?rate:null;
  }
  function displayAmount(value){
    const amount=finite(value); if(amount==null) return '—';
    const rate=fxRate();
    if(state.displayCurrency==='RUB'&&rate) return `≈ ${rubles(amount*rate)} ₽`;
    return `${money(amount)} USDT`;
  }
  function displayAmountNote(value, baseNote){
    const amount=finite(value), rate=fxRate();
    if(amount==null) return baseNote;
    if(state.displayCurrency==='RUB') return rate?`${money(amount)} USDT · ${baseNote}`:`${money(amount)} USDT · курс RUB временно недоступен`;
    return rate?`≈ ${rubles(amount*rate)} ₽ · ${baseNote}`:baseNote;
  }
  function fxStatus(){
    const rate=fxRate();
    if(!rate) return state.fxError?`Курс рублей временно недоступен: ${state.fxError}`:'Курс рублей загружается';
    const date=state.fx?.effective_date||'дата не передана';
    const stale=state.fx?.stale?' · сохранённый курс':'';
    return `1 USDT ≈ ${price(rate)} ₽ · ${state.fx?.source||'Банк России'} · ${date}${stale}`;
  }
  function virtualData(){
    const raw=state.virtual||{};
    const root=raw.state&&typeof raw.state==='object'?raw.state:raw;
    return {summary:root.summary||raw.summary||{},trades:arr(root.trades,raw.trades,root.orders,root.history)};
  }
  function botList(){ return arr(state.bots?.bots,state.bots?.items,state.bots?.agents,state.bots); }
  function newsList(){ return arr(state.news?.news?.items,state.news?.news,state.news?.items,state.news?.articles,state.news); }
  function freshBot(bot){ const age=finite(bot?.heartbeat_age_seconds); return age!=null&&age<90; }
  function actionLabel(trade){
    const side=String(trade.side||'').toUpperCase();
    return side==='BUY'?'BUY · покупка':side==='SELL'?'SELL · продажа':side||'—';
  }
  function entryReason(trade){
    if(trade.entry_reason_ru) return trade.entry_reason_ru;
    const side=String(trade.side||'').toUpperCase();
    const change=finite(trade.signal_change_24h_percent);
    const symbol=trade.symbol||trade.asset||'актив';
    if(change==null) return 'Причина входа не сохранена в старой записи.';
    if(side==='BUY') return `Покупка ${symbol}: рост за 24 часа ${percent(change,3)} превысил порог 0,35%; стратегия открыла BUY по тренду.`;
    if(side==='SELL') return `Продажа ${symbol}: изменение за 24 часа ${percent(change,3)} по модулю превысило порог 0,35%; стратегия открыла виртуальный SELL по тренду.`;
    return 'Направление операции не определено.';
  }
  function tradeNumbers(trade){
    const entry=finite(trade.entry_price)||0;
    const live=finite(trade.exit_price??trade.current_price)??entry;
    const qty=finite(trade.quantity)??(entry>0?(finite(trade.notional)||100)/entry:0);
    const notional=finite(trade.notional)??entry*qty;
    const side=String(trade.side||'').toUpperCase();
    const gross=finite(trade.gross_pnl)??((side==='SELL'?entry-live:live-entry)*qty);
    const entryFee=finite(trade.entry_fee)??0;
    const status=String(trade.status||'').toUpperCase();
    const exitFee=status==='CLOSED'?(finite(trade.exit_fee)??Math.max(0,(finite(trade.fee)??0)-entryFee)):notional*0.001;
    const fees=status==='CLOSED'?(finite(trade.fee)??entryFee+exitFee):entryFee+exitFee;
    const net=finite(trade.net_pnl)??gross-fees;
    const rawMove=live-entry;
    const movePercent=entry?rawMove/entry*100:0;
    return {entry,live,qty,notional,gross,entryFee,exitFee,fees,net,rawMove,movePercent,status,side};
  }
  function tradeCard(trade){
    const n=tradeNumbers(trade);
    const symbol=String(trade.symbol||trade.asset||'—');
    const statusOpen=n.status!=='CLOSED';
    const grossTone=n.gross>=0?'positive':'negative';
    const netTone=n.net>=0?'positive':'negative';
    const closeText=statusOpen?'Позиция ещё открыта. Текущая цена обновляется по рынку.':`Закрытие: ${trade.close_reason_ru||'причина не сохранена'}.`;
    const formula=`${n.side==='SELL'?'SELL: (вход − текущая цена) × количество':'BUY: (текущая цена − вход) × количество'} = ${signed(n.gross,4)} USDT; затем комиссии ${money(n.fees,2)} USDT; итог ${signed(n.net,4)} USDT.`;
    return `<article class="trade-card">
      <div class="trade-card-head"><div><div class="trade-card-title"><h3>${esc(symbol)}</h3><span class="status-chip ${n.side==='BUY'?'buy':'sell'}">${esc(actionLabel(trade))}</span><span class="status-chip ${statusOpen?'open':'closed'}">${statusOpen?'ОТКРЫТА':'ЗАКРЫТА'}</span></div><div class="trade-card-subtitle">Виртуальная позиция · реальные котировки · реальные ордера не отправлялись</div></div></div>
      <div class="trade-card-grid">
        <div class="trade-metric"><span>Размер позиции</span><b>${esc(money(n.notional,1))} USDT</b></div>
        <div class="trade-metric"><span>Количество</span><b>${esc(quantity(n.qty))} ${esc(symbol.split('/')[0])}</b></div>
        <div class="trade-metric"><span>Цена входа</span><b>${esc(price(n.entry))}</b></div>
        <div class="trade-metric"><span>${statusOpen?'Текущая цена':'Цена выхода'}</span><b>${esc(price(n.live))}</b></div>
        <div class="trade-metric"><span>Изменение цены</span><b>${esc(signed(n.rawMove,1))} · ${esc(signed(n.movePercent,3))}%</b></div>
      </div>
      <div class="trade-breakdown">
        <div class="trade-metric"><span>Результат движения цены</span><b class="${grossTone}">${esc(signed(n.gross,2))} USDT</b></div>
        <div class="trade-metric"><span>Комиссии ${statusOpen?'вход + оценка выхода':'всего'}</span><b class="negative">−${esc(money(n.fees,2))} USDT</b></div>
        <div class="trade-metric total"><span>Чистый результат</span><b class="${netTone}">${esc(signed(n.net,2))} USDT</b></div>
      </div>
      <div class="trade-explanation"><p>${esc(entryReason(trade))} ${esc(closeText)}</p><details><summary>Показать расчёт</summary><div class="trade-formula">${esc(formula)}</div></details></div>
    </article>`;
  }
  function quoteTable(){
    const rows=symbols.map(symbol=>{
      const quote=state.quotes[symbol]||{};
      const change=finite(quote.change_24h_percent);
      const tone=change!=null?(change>=0?'positive':'negative'):'';
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
    const open=finite(s.open_positions)??trades.filter(x=>String(x.status).toUpperCase()==='OPEN').length;
    const closed=finite(s.closed_positions)??trades.filter(x=>String(x.status).toUpperCase()==='CLOSED').length;
    const pnl=finite(s.net_pnl);
    const health=state.health||{};
    const components=arr(health.components);
    const healthy=components.filter(x=>x.status==='healthy').length;
    const unavailable=Object.keys(state.errors).length;
    const latest=trades.slice().reverse().slice(0,4);
    const tradeCards=latest.length?`<div class="trade-list overview-trade-list">${latest.map(tradeCard).join('')}</div>`:empty('Виртуальные операции пока не получены.');
    const newsRows=news.length?news.map(x=>`<div class="news-item"><b>${esc(x.title||x.headline||'Новость')}</b><small>${esc(x.source||x.publisher||'Источник не указан')}</small></div>`).join(''):empty('Подтверждённые новости пока не получены.');
    content.innerHTML=`<div class="title"><h1>Центр управления</h1><p>Капитал, рынок и операции без скрытых расчётов</p></div>
      <div class="status-actions"><label>Показывать капитал <select id="overviewDisplayCurrency"><option value="RUB" ${state.displayCurrency==='RUB'?'selected':''}>Рубли ₽</option><option value="USDT" ${state.displayCurrency==='USDT'?'selected':''}>USDT</option></select></label><span>${esc(fxStatus())}</span></div>
      <section class="metrics">
        ${card('Капитал',s.equity!=null?displayAmount(s.equity):'—',displayAmountNote(s.equity,'виртуальный счёт'))}
        ${card('Доступно',s.cash!=null?displayAmount(s.cash):'—',displayAmountNote(s.cash,'свободный капитал'))}
        ${card('Открытые позиции',String(open),'ещё не закрыты')}
        ${card('Закрытые сделки',String(closed),'завершённые операции')}
        ${card('Общий результат',pnl!=null?displayAmount(pnl):'—',displayAmountNote(pnl,'цена минус комиссии'),pnl!=null?(pnl>=0?'positive':'negative'):'')}
        ${card('ИИ онлайн',`${verified}/${bots.length}`,'активность до 90 секунд',verified?'positive':'')}
      </section>
      <section class="v10-grid">
        ${panel(`Рынок · ${state.symbol.replace('USDT','/USDT')}`,quote.price!=null?`${row('Цена',price(quote.price)+' USDT','positive')}${row('За 24 часа',percent(quote.change_24h_percent),Number(quote.change_24h_percent)>=0?'positive':'negative')}${row('Источник',quote.source||'Bybit')}${quoteTable()}`:quoteTable(),'wide')}
        <article class="panel wide"><div class="section-head"><div><small>SHARIPOVAI</small><h2>Последние виртуальные операции</h2><p>Сразу видно размер позиции, движение цены, комиссии и чистый результат.</p></div><div class="section-actions"><button id="overviewOpenTrades" class="action" type="button">Все сделки</button></div></div><div class="summary-legend"><span><i class="price"></i>результат цены</span><span><i class="fee"></i>комиссии</span><span><i class="net"></i>чистый итог</span></div>${tradeCards}</article>
        ${panel('Новости',newsRows)}
        ${panel('Состояние контуров',`${row('Компоненты в норме',components.length?`${healthy}/${components.length}`:'—')}${row('Недоступные запросы',String(unavailable),unavailable?'negative':'positive')}${row('Реальные ордера',s.real_orders_blocked===false?'РАЗРЕШЕНЫ':'ЗАБЛОКИРОВАНЫ',s.real_orders_blocked===false?'negative':'positive')}${row('Рыночный учёт PnL',s.market_price_accounting===true?'ПОДТВЕРЖДЁН':'НЕ ПОДТВЕРЖДЁН',s.market_price_accounting===true?'positive':'negative')}${row('Обновлено',state.loadedAt||'—')}`)}
      </section>`;
    bindOverviewControls();
  }

  function bindOverviewControls(){
    $('overviewDisplayCurrency')?.addEventListener('change',(event)=>{state.displayCurrency=event.target.value==='USDT'?'USDT':'RUB';localStorage.setItem('sharipovai-display-currency',state.displayCurrency);render();});
    $('overviewSymbol')?.addEventListener('change',(event)=>{state.symbol=symbols.includes(event.target.value)?event.target.value:'BTCUSDT';localStorage.setItem('sharipovai-market-symbol',state.symbol);render();});
    document.querySelectorAll('[data-overview-symbol]').forEach(rowElement=>rowElement.addEventListener('click',()=>{state.symbol=rowElement.dataset.overviewSymbol;localStorage.setItem('sharipovai-market-symbol',state.symbol);render();}));
    $('overviewOpenMarket')?.addEventListener('click',()=>{localStorage.setItem('sharipovai-market-symbol',state.symbol);document.querySelector('#nav button[data-page="market"]')?.click();});
    $('overviewOpenTrades')?.addEventListener('click',()=>document.querySelector('#nav button[data-page="trades"]')?.click());
  }

  async function load(){
    if(!active()) return;
    const entries=[['virtual','/api/virtual-account/state'],['bots','/api/ai-bots'],['news','/api/social-news'],['run','/api/run'],['health','/api/system/health']];
    const [coreResults,quoteResults,fxResult]=await Promise.all([
      Promise.allSettled(entries.map(([,url])=>get(url))),
      Promise.allSettled(symbols.map(symbol=>get(`/api/market/quote/${symbol}`))),
      get('/api/currency/usd-rub').then(value=>({ok:true,value})).catch(error=>({ok:false,error})),
    ]);
    state.errors={};
    coreResults.forEach((result,index)=>{const key=entries[index][0];if(result.status==='fulfilled')state[key]=result.value;else state.errors[key]=result.reason?.message||'недоступно';});
    quoteResults.forEach((result,index)=>{const symbol=symbols[index];if(result.status==='fulfilled')state.quotes[symbol]=result.value;else state.errors[`quote_${symbol}`]=result.reason?.message||'недоступно';});
    if(fxResult.ok){state.fx=fxResult.value;state.fxError='';}else{state.fxError=fxResult.error?.message||'недоступно';}
    state.loadedAt=new Date().toLocaleString('ru-RU');
    render();
  }

  document.addEventListener('click',(event)=>{const button=event.target.closest('#nav button[data-page="overview"]');if(button)setTimeout(()=>load().catch(()=>{}),0);});
  $('refresh')?.addEventListener('click',()=>{if(active())setTimeout(()=>load().catch(()=>{}),0);});
  window.addEventListener('DOMContentLoaded',()=>{if(active())load().catch(()=>{});});
  setInterval(()=>{if(active()&&!document.hidden)load().catch(()=>{});},10000);
})();
