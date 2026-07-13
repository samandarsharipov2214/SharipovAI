(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const list = (...values) => values.find(Array.isArray) || [];
  const number = value => Number.isFinite(Number(value)) ? Number(value) : null;
  const money = (value,digits=1) => number(value) != null ? Number(value).toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits}) : '—';
  const signed = (value,digits=2) => { const n=number(value); return n==null?'—':`${n>0?'+':''}${n.toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits})}`; };
  const quantity = value => number(value) != null ? Number(value).toLocaleString('ru-RU',{maximumFractionDigits:8}) : '—';
  const price = value => { const n=number(value); if(n==null)return '—'; const d=Math.abs(n)>=100?1:Math.abs(n)>=10?2:4; return n.toLocaleString('ru-RU',{minimumFractionDigits:d,maximumFractionDigits:d}); };
  const percent = (value,digits=3) => number(value) != null ? `${Number(value).toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits})}%` : '—';
  const time = value => { if(!value)return '—'; const n=Number(value); const normalized=Number.isFinite(n)&&n>0&&n<1e12?n*1000:value; const d=new Date(normalized); return Number.isNaN(d.getTime())?'—':d.toLocaleString('ru-RU'); };
  const request = async url => { const r=await fetch(url,{cache:'no-store',credentials:'same-origin'}); if(!r.ok) throw new Error(String(r.status)); return r.json(); };
  const empty = text => `<div class="trade-empty">${esc(text)}</div>`;
  const card = (label,value,note='') => `<article class="x18-card"><span>${esc(label)}</span><b>${esc(value)}</b><small>${esc(note)}</small></article>`;
  const panel = (heading,body,wide='') => `<article class="x18-panel ${wide}"><small>SHARIPOVAI</small><h2>${esc(heading)}</h2>${body}</article>`;
  const title = (name,text) => `<div class="title"><h1>${esc(name)}</h1><p>${esc(text)}</p></div>`;
  const ui = {filter:'all',virtual:null,realItems:[],realNote:''};

  async function account(){
    const raw=await request('/api/exchange/account/snapshot');
    const explicitFailure=raw?.connected===false||raw?.verified===false||raw?.status==='error'||raw?.status==='unavailable'||raw?.ok===false;
    if(explicitFailure) throw new Error(raw?.message||raw?.error||'Подключение Bybit не подтверждено');
    const data=raw.snapshot||raw.account||raw.result||raw;
    const hasAccountEvidence=data&&typeof data==='object'&&[data.total_equity,data.totalEquity,data.equity,data.total_wallet_balance,data.totalWalletBalance,data.wallet_balance].some(v=>v!==undefined&&v!==null);
    const hasCollections=[data?.positions,raw?.positions,data?.orders,raw?.orders,data?.assets,data?.coins,data?.coin,raw?.assets].some(Array.isArray);
    if(!hasAccountEvidence&&!hasCollections&&raw?.connected!==true&&raw?.verified!==true) throw new Error('Ответ API не содержит подтверждённых данных счёта');
    return {data,positions:list(data.positions,raw.positions),orders:list(data.orders,raw.orders),trades:list(data.trades,data.executions,raw.trades,raw.executions),assets:list(data.assets,data.coins,data.coin,raw.assets)};
  }
  function virtualPayload(raw){ const state=raw?.state&&typeof raw.state==='object'?raw.state:raw||{}; return {state,summary:state.summary||raw?.summary||{},trades:list(state.trades,raw?.trades,state.orders,state.history)}; }
  function operationLabel(item){ const side=String(item.side||'').toUpperCase(); return side==='BUY'?'BUY · покупка':side==='SELL'?'SELL · продажа':side||'—'; }
  function entryReason(item){
    if(item.entry_reason_ru) return item.entry_reason_ru;
    const side=String(item.side||'').toUpperCase(), change=number(item.signal_change_24h_percent), symbol=item.symbol||item.asset||'актив';
    if(change==null) return 'Причина входа не сохранена в старой записи.';
    if(side==='BUY') return `Покупка ${symbol}: рост за 24 часа ${percent(change)} превысил порог 0,35%; открыта BUY по тренду.`;
    if(side==='SELL') return `Продажа ${symbol}: изменение за 24 часа ${percent(change)} по модулю превысило порог 0,35%; открыт виртуальный SELL по тренду.`;
    return 'Направление операции не определено.';
  }
  function tradeNumbers(item){
    const entry=number(item.entry_price)||0;
    const live=number(item.exit_price??item.current_price)??entry;
    const qty=number(item.quantity)??(entry>0?(number(item.notional)||100)/entry:0);
    const notional=number(item.notional)??entry*qty;
    const side=String(item.side||'').toUpperCase();
    const gross=number(item.gross_pnl)??((side==='SELL'?entry-live:live-entry)*qty);
    const entryFee=number(item.entry_fee)??0;
    const status=String(item.status||'').toUpperCase();
    const exitFee=status==='CLOSED'?(number(item.exit_fee)??Math.max(0,(number(item.fee)??0)-entryFee)):notional*0.001;
    const fees=status==='CLOSED'?(number(item.fee)??entryFee+exitFee):entryFee+exitFee;
    const net=number(item.net_pnl)??gross-fees;
    const rawMove=live-entry;
    const movePercent=entry?rawMove/entry*100:0;
    return {entry,live,qty,notional,side,status,gross,entryFee,exitFee,fees,net,rawMove,movePercent};
  }
  function tradeCard(item){
    const n=tradeNumbers(item), symbol=String(item.symbol||item.asset||'—'), open=n.status!=='CLOSED';
    const formula=`${n.side==='SELL'?'SELL: (цена входа − текущая/выходная цена) × количество':'BUY: (текущая/выходная цена − цена входа) × количество'} = ${signed(n.gross,4)} USDT. Комиссии: ${money(n.fees,2)} USDT. Чистый итог: ${signed(n.net,4)} USDT.`;
    const closing=open?'Позиция открыта: цена справа является текущей, а не ценой выхода.':`Позиция закрыта: ${item.close_reason_ru||'причина закрытия не сохранена'}.`;
    return `<article class="trade-card" data-status="${open?'open':'closed'}" data-side="${n.side.toLowerCase()}">
      <div class="trade-card-head"><div><div class="trade-card-title"><h3>${esc(symbol)}</h3><span class="status-chip ${n.side==='BUY'?'buy':'sell'}">${esc(operationLabel(item))}</span><span class="status-chip ${open?'open':'closed'}">${open?'ОТКРЫТА':'ЗАКРЫТА'}</span></div><div class="trade-card-subtitle">${esc(time(item.opened_at))}${open?'':' → '+esc(time(item.closed_at))}</div></div></div>
      <div class="trade-card-grid">
        <div class="trade-metric"><span>Размер позиции</span><b>${esc(money(n.notional,1))} USDT</b></div>
        <div class="trade-metric"><span>Количество</span><b>${esc(quantity(n.qty))} ${esc(symbol.split('/')[0])}</b></div>
        <div class="trade-metric"><span>Цена входа</span><b>${esc(price(n.entry))}</b></div>
        <div class="trade-metric"><span>${open?'Текущая цена':'Цена выхода'}</span><b>${esc(price(n.live))}</b></div>
        <div class="trade-metric"><span>Изменение рынка</span><b>${esc(signed(n.rawMove,1))} · ${esc(signed(n.movePercent,3))}%</b></div>
      </div>
      <div class="trade-breakdown">
        <div class="trade-metric"><span>Результат движения цены</span><b class="${n.gross>=0?'positive':'negative'}">${esc(signed(n.gross,2))} USDT</b></div>
        <div class="trade-metric"><span>Комиссии ${open?'вход + оценка выхода':'всего'}</span><b class="negative">−${esc(money(n.fees,2))} USDT</b></div>
        <div class="trade-metric total"><span>Чистый результат</span><b class="${n.net>=0?'positive':'negative'}">${esc(signed(n.net,2))} USDT</b></div>
      </div>
      <div class="trade-explanation"><p>${esc(entryReason(item))} ${esc(closing)}</p><details><summary>Показать формулу расчёта</summary><div class="trade-formula">${esc(formula)}</div></details></div>
      <div class="trade-card-foot"><span>Источник: ${esc(item.quote_source||item.last_quote_source||'—')}</span><span>Реальный ордер: нет</span></div>
    </article>`;
  }
  function filteredTrades(items){
    if(ui.filter==='open') return items.filter(x=>String(x.status||'').toUpperCase()==='OPEN');
    if(ui.filter==='closed') return items.filter(x=>String(x.status||'').toUpperCase()==='CLOSED');
    if(ui.filter==='buy') return items.filter(x=>String(x.side||'').toUpperCase()==='BUY');
    if(ui.filter==='sell') return items.filter(x=>String(x.side||'').toUpperCase()==='SELL');
    return items;
  }
  function tradeCards(items){ const filtered=filteredTrades(items).slice().reverse(); return filtered.length?`<div class="trade-list">${filtered.map(tradeCard).join('')}</div>`:empty('По выбранному фильтру операций нет.'); }
  function filters(){
    const options=[['all','Все'],['open','Открытые'],['closed','Закрытые'],['buy','BUY'],['sell','SELL']];
    return `<div class="section-actions">${options.map(([value,label])=>`<button class="action ${ui.filter===value?'primary':''}" data-trade-filter="${value}" type="button">${label}</button>`).join('')}<button id="tradeRefresh" class="action" type="button">Обновить</button></div>`;
  }
  function realRows(items){
    if(!items.length) return empty('Реальных исполнений нет. Реальная торговля заблокирована настройками безопасности.');
    return `<table class="x18-table"><thead><tr><th>Время</th><th>Пара</th><th>Сторона</th><th>Цена</th><th>Количество</th><th>Результат</th></tr></thead><tbody>${items.slice(0,200).map(x=>`<tr><td>${time(x.execTime||x.createdTime||x.time||x.created_at)}</td><td>${esc(x.symbol||'—')}</td><td>${esc(x.side||'—')}</td><td>${esc(price(x.execPrice??x.price))}</td><td>${esc(x.execQty??x.qty??x.size??'—')}</td><td>${esc(x.closedPnl??x.pnl??x.orderStatus??x.status??'—')}</td></tr>`).join('')}</tbody></table>`;
  }

  async function bybit(){
    const out=$('content'); if(!out)return; out.innerHTML=title('Bybit','Личный кабинет отделён от виртуального счёта')+empty('Загрузка…');
    try{
      const a=await account(), d=a.data, equity=d.total_equity??d.totalEquity??d.equity, available=d.total_available_balance??d.totalAvailableBalance??d.available_balance;
      out.innerHTML=title('Bybit','Фактические данные личного кабинета')+`<section class="x18-metrics">${card('Подключение','ПОДТВЕРЖДЕНО','Получен ответ личного API')}${card('Капитал',equity!=null?money(equity)+' USDT':'—')}${card('Доступно',available!=null?money(available)+' USDT':'—')}${card('Позиции',String(a.positions.length))}${card('Ордера',String(a.orders.length))}</section><section class="x18-grid">${panel('Активы',a.assets.length?`<table class="x18-table"><thead><tr><th>Актив</th><th>Баланс</th><th>Доступно</th></tr></thead><tbody>${a.assets.map(x=>`<tr><td>${esc(x.coin||x.asset||x.symbol||'—')}</td><td>${esc(money(x.walletBalance??x.balance))}</td><td>${esc(money(x.availableBalance??x.available))}</td></tr>`).join('')}</tbody></table>`:empty('Состав активов не передан.'),'wide')}${panel('Безопасность','<p>Вывод средств отключён. Реальные сделки требуют отдельного разрешения.</p>')}</section>`;
    } catch { out.innerHTML=title('Bybit','Личный API не настроен')+empty('Это не мешает рынку и виртуальному счёту. Для подключения нужен read-only ключ Bybit.'); }
  }
  function renderTrades(){
    const out=$('content'); if(!out||!ui.virtual)return;
    const {summary,items}=ui.virtual;
    out.innerHTML=title('Сделки','Каждая операция разложена на размер, движение цены, комиссии и чистый результат')+
      `<section class="x18-metrics">${card('Всего',String(summary.trade_count??items.length),'виртуальных операций')}${card('Открыто',String(summary.open_positions??items.filter(x=>String(x.status).toUpperCase()==='OPEN').length),'текущая цена, не выход')}${card('Закрыто',String(summary.closed_positions??items.filter(x=>String(x.status).toUpperCase()==='CLOSED').length),'завершённые сделки')}${card('Общий результат',money(summary.net_pnl)+' USDT','после комиссий')}${card('Комиссии',money(summary.total_fees)+' USDT','учтены в Net PnL')}${card('Реальные ордера',summary.real_orders_blocked===false?'РАЗРЕШЕНЫ':'ЗАБЛОКИРОВАНЫ',ui.realNote)}</section>`+
      `<article class="x18-panel wide"><div class="section-head"><div><small>VIRTUAL ACCOUNT</small><h2>Виртуальные операции</h2><p>OPEN означает, что справа показана текущая цена. Цена выхода появляется только после закрытия.</p></div>${filters()}</div><div class="summary-legend"><span><i class="price"></i>результат движения цены</span><span><i class="fee"></i>комиссии</span><span><i class="net"></i>чистый итог</span></div>${tradeCards(items)}</article>`+
      `<article class="x18-panel wide"><small>BYBIT</small><h2>Реальные исполнения</h2>${realRows(ui.realItems)}</article>`;
    bindTradeControls();
  }
  function bindTradeControls(){
    document.querySelectorAll('[data-trade-filter]').forEach(button=>button.addEventListener('click',()=>{ui.filter=button.dataset.tradeFilter||'all';renderTrades();}));
    $('tradeRefresh')?.addEventListener('click',()=>trades());
  }
  async function trades(){
    const out=$('content'); if(!out)return; out.innerHTML=title('Сделки','Загрузка понятного журнала операций')+empty('Загрузка…');
    const [virtualResult,realResult]=await Promise.allSettled([request('/api/virtual-account/trades'),account()]);
    if(virtualResult.status!=='fulfilled'){out.innerHTML=title('Сделки','Журнал временно недоступен')+empty('API виртуального счёта не вернул историю операций.');return;}
    const virtual=virtualPayload(virtualResult.value);
    ui.virtual={summary:virtual.summary,items:virtual.trades};
    ui.realItems=realResult.status==='fulfilled'?(realResult.value.trades.length?realResult.value.trades:realResult.value.orders):[];
    ui.realNote=realResult.status==='fulfilled'?'личный API отвечает':'личный API не настроен';
    renderTrades();
  }
  async function virtualAccount(){
    const out=$('content'); if(!out)return; out.innerHTML=title('Виртуальный счёт','Загрузка капитала и операций')+empty('Загрузка…');
    try{
      const raw=await request('/api/virtual-account/state');
      if(raw?.verified===false||raw?.status==='error'||raw?.status==='unavailable') throw new Error('Виртуальный счёт не подтверждён');
      const d=virtualPayload(raw), s=d.summary, items=d.trades;
      out.innerHTML=title('Виртуальный счёт','Виртуальны только деньги и ордера; котировки и расчёт PnL рыночные')+
        `<section class="x18-metrics">${card('Баланс',money(s.cash??s.balance)+' USDT','после списанных комиссий')}${card('Капитал',money(s.equity)+' USDT','баланс плюс открытые позиции')}${card('Общий результат',money(s.net_pnl)+' USDT','цена минус комиссии')}${card('Комиссии',money(s.total_fees)+' USDT','все операции')}${card('Открыто',String(s.open_positions??0),'текущие позиции')}${card('Закрыто',String(s.closed_positions??0),'завершённые сделки')}</section>`+
        `<article class="x18-panel wide"><div class="section-head"><div><small>VIRTUAL ACCOUNT</small><h2>Операции</h2><p>Расчёт каждой позиции можно раскрыть прямо в карточке.</p></div></div>${d.trades.length?`<div class="trade-list">${d.trades.slice().reverse().map(tradeCard).join('')}</div>`:empty('Операций пока нет.')}</article>`;
    } catch { out.innerHTML=title('Виртуальный счёт','Контур временно недоступен')+empty('Состояние виртуального счёта не подтверждено.'); }
  }
  function settings(){
    const out=$('content'); if(!out)return; let s={}; try{s=JSON.parse(localStorage.getItem('sharipovai-settings')||'{}')}catch{}
    out.innerHTML=title('Настройки','Язык, обновление и отображение')+`<section class="x18-grid">${panel('Основные',`<label>Язык<select id="x18lang"><option value="ru">Русский</option><option value="en">English</option><option value="uz">O‘zbek</option></select></label><label>Обновление<select id="x18refresh"><option>3</option><option>5</option><option>10</option><option>30</option><option>60</option></select></label><label>Пара<select id="x18symbol"><option>BTCUSDT</option><option>ETHUSDT</option><option>SOLUSDT</option><option>BNBUSDT</option><option>XRPUSDT</option><option>ADAUSDT</option></select></label>`)}${panel('Фильтры',`<label><input id="x18news" type="checkbox" ${s.verifiedNewsOnly!==false?'checked':''}> Только проверенные новости</label><label><input id="x18ai" type="checkbox" ${s.verifiedOnly?'checked':''}> Только подтверждённые ИИ</label><label><input id="x18compact" type="checkbox" ${s.compact?'checked':''}> Компактный режим</label>`)}${panel('Сохранение','<button class="action" id="x18save">Сохранить</button><button class="action" id="x18reset">Сбросить</button><p id="x18status"></p>','wide')}</section>`;
    $('x18lang').value=s.lang||'ru'; $('x18refresh').value=String(s.refreshSeconds||5); $('x18symbol').value=s.defaultSymbol||'BTCUSDT';
    $('x18save').onclick=()=>{const n={...s,lang:$('x18lang').value,refreshSeconds:Number($('x18refresh').value),defaultSymbol:$('x18symbol').value,verifiedNewsOnly:$('x18news').checked,verifiedOnly:$('x18ai').checked,compact:$('x18compact').checked};localStorage.setItem('sharipovai-settings',JSON.stringify(n));localStorage.setItem('sharipovai-market-symbol',n.defaultSymbol);$('x18status').textContent='Настройки сохранены.';document.querySelector(`[data-lang="${n.lang}"]`)?.click();};
    $('x18reset').onclick=()=>{localStorage.removeItem('sharipovai-settings');$('x18status').textContent='Настройки сброшены.';};
  }

  const pages={bybit,trades,virtual:virtualAccount,settings};
  document.addEventListener('click',event=>{const button=event.target.closest('#nav button[data-page]');if(!button||!pages[button.dataset.page])return;setTimeout(()=>pages[button.dataset.page](),30);});
  $('refresh')?.addEventListener('click',()=>{const page=document.querySelector('#nav button.active[data-page]')?.dataset.page;if(pages[page])pages[page]();});
})();
