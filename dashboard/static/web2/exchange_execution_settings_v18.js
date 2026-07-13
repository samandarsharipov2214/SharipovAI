(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const list = (...values) => values.find(Array.isArray) || [];
  const rawNumber = value => Number.isFinite(Number(value)) ? Number(value) : null;
  const money = value => rawNumber(value) != null ? Number(value).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1}) : '—';
  const pnl = value => rawNumber(value) != null ? Number(value).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2}) : '—';
  const price = value => {
    const number=rawNumber(value); if(number==null) return '—';
    const digits=Math.abs(number)>=100?1:Math.abs(number)>=10?2:4;
    return number.toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits});
  };
  const percent = value => rawNumber(value) != null ? `${Number(value).toLocaleString('ru-RU',{minimumFractionDigits:3,maximumFractionDigits:3})}%` : '—';
  const time = value => {
    if(!value) return '—';
    const numeric=Number(value);
    const normalized=Number.isFinite(numeric) && numeric>0 && numeric<1e12 ? numeric*1000 : value;
    const d=new Date(normalized);
    return Number.isNaN(d.getTime())?'—':d.toLocaleString('ru-RU');
  };
  const request = async url => { const r=await fetch(url,{cache:'no-store',credentials:'same-origin'}); if(!r.ok) throw new Error(String(r.status)); return r.json(); };
  const empty = text => `<div class="x18-empty">${esc(text)}</div>`;
  const card = (label,value,note='') => `<article class="x18-card"><span>${esc(label)}</span><b>${esc(value)}</b><small>${esc(note)}</small></article>`;
  const panel = (title,body,wide='') => `<article class="x18-panel ${wide}"><small>SHARIPOVAI</small><h2>${esc(title)}</h2>${body}</article>`;
  const title = (name,text) => `<div class="title"><h1>${esc(name)}</h1><p>${esc(text)}</p></div>`;

  async function account(){
    const raw=await request('/api/exchange/account/snapshot');
    const explicitFailure = raw?.connected === false || raw?.verified === false || raw?.status === 'error' || raw?.status === 'unavailable' || raw?.ok === false;
    if(explicitFailure) throw new Error(raw?.message || raw?.error || 'Подключение Bybit не подтверждено');
    const data=raw.snapshot||raw.account||raw.result||raw;
    const hasAccountEvidence = data && typeof data === 'object' && [data.total_equity,data.totalEquity,data.equity,data.total_wallet_balance,data.totalWalletBalance,data.wallet_balance].some(v => v !== undefined && v !== null);
    const hasCollections = [data?.positions,raw?.positions,data?.orders,raw?.orders,data?.assets,data?.coins,data?.coin,raw?.assets].some(Array.isArray);
    if(!hasAccountEvidence && !hasCollections && raw?.connected !== true && raw?.verified !== true) throw new Error('Ответ API не содержит подтверждённых данных счёта');
    return {data,positions:list(data.positions,raw.positions),orders:list(data.orders,raw.orders),trades:list(data.trades,data.executions,raw.trades,raw.executions),assets:list(data.assets,data.coins,data.coin,raw.assets)};
  }

  function virtualPayload(raw){
    const state=raw?.state && typeof raw.state==='object' ? raw.state : raw || {};
    return {state,summary:state.summary||raw?.summary||{},trades:list(state.trades,raw?.trades,state.orders,state.history)};
  }
  function operationLabel(item){
    const side=String(item.side||'').toUpperCase();
    return side==='BUY'?'BUY · покупка':side==='SELL'?'SELL · продажа':side||'—';
  }
  function entryReason(item){
    if(item.entry_reason_ru) return item.entry_reason_ru;
    const side=String(item.side||'').toUpperCase();
    const change=rawNumber(item.signal_change_24h_percent);
    const symbol=item.symbol||item.asset||'актив';
    if(change==null) return 'Причина входа не сохранена в старой записи.';
    if(side==='BUY') return `Покупка ${symbol}: рост за 24 часа ${percent(change)} превысил порог 0,35%; открыта BUY по тренду.`;
    if(side==='SELL') return `Продажа ${symbol}: изменение за 24 часа ${percent(change)} по модулю превысило порог 0,35%; открыт виртуальный SELL по тренду.`;
    return 'Направление операции не определено.';
  }
  function closeReason(item){
    if(String(item.status||'').toUpperCase()!=='CLOSED') return 'Позиция ещё открыта.';
    return item.close_reason_ru||'Причина закрытия не сохранена.';
  }

  function virtualRows(items){
    if(!items.length) return empty('Виртуальные операции пока не получены.');
    return `<table class="x18-table"><thead><tr><th>Открыта</th><th>Закрыта</th><th>Пара</th><th>Операция</th><th>Статус</th><th>Вход</th><th>Текущая / выход</th><th>Net PnL</th><th>Комиссия</th><th>Почему открыта</th><th>Почему закрыта</th><th>Источник</th></tr></thead><tbody>${items.slice().reverse().slice(0,200).map(x=>`<tr><td>${time(x.opened_at||x.time||x.created_at)}</td><td>${x.closed_at?time(x.closed_at):'—'}</td><td>${esc(x.symbol||x.asset||'—')}</td><td>${esc(operationLabel(x))}</td><td>${esc(x.status||'—')}</td><td>${esc(price(x.entry_price))}</td><td>${esc(price(x.exit_price??x.current_price))}</td><td class="${Number(x.net_pnl)>=0?'positive':'negative'}">${esc(pnl(x.net_pnl))} USDT</td><td>${esc(pnl(x.fee))} USDT</td><td>${esc(entryReason(x))}</td><td>${esc(closeReason(x))}</td><td>${esc(x.quote_source||x.last_quote_source||'—')}</td></tr>`).join('')}</tbody></table>`;
  }

  function realRows(items){
    if(!items.length) return empty('Реальных исполнений нет. Реальная торговля заблокирована настройками безопасности.');
    return `<table class="x18-table"><thead><tr><th>Время</th><th>Пара</th><th>Сторона</th><th>Цена</th><th>Количество</th><th>Результат</th></tr></thead><tbody>${items.slice(0,200).map(x=>`<tr><td>${time(x.execTime||x.createdTime||x.time||x.created_at)}</td><td>${esc(x.symbol||'—')}</td><td>${esc(x.side||'—')}</td><td>${esc(price(x.execPrice??x.price))}</td><td>${esc(x.execQty??x.qty??x.size??'—')}</td><td>${esc(x.closedPnl??x.pnl??x.orderStatus??x.status??'—')}</td></tr>`).join('')}</tbody></table>`;
  }

  async function bybit(){
    const out=$('content'); if(!out)return; out.innerHTML=title('Bybit','Проверка личного кабинета и состояния подключения')+empty('Загрузка…');
    try{
      const a=await account(), d=a.data;
      const equity=d.total_equity??d.totalEquity??d.equity;
      const available=d.total_available_balance??d.totalAvailableBalance??d.available_balance;
      out.innerHTML=title('Bybit','Фактические данные личного кабинета')+`<section class="x18-metrics">${card('Подключение','ПОДТВЕРЖДЕНО','Получен проверенный ответ личного API')}${card('Капитал',equity!=null?money(equity)+' USDT':'—')}${card('Доступно',available!=null?money(available)+' USDT':'—')}${card('Позиции',String(a.positions.length))}${card('Ордера',String(a.orders.length))}</section><section class="x18-grid">${panel('Активы',a.assets.length?`<table class="x18-table"><thead><tr><th>Актив</th><th>Баланс</th><th>Доступно</th></tr></thead><tbody>${a.assets.map(x=>`<tr><td>${esc(x.coin||x.asset||x.symbol||'—')}</td><td>${esc(money(x.walletBalance??x.balance))}</td><td>${esc(money(x.availableBalance??x.available))}</td></tr>`).join('')}</tbody></table>`:empty('Состав активов не передан.'),'wide')}${panel('Безопасность','<p>Данные доступа не отображаются. Вывод средств отключён. Реальные сделки требуют отдельного разрешения.</p>')}</section>`;
    } catch { out.innerHTML=title('Bybit','Подключение не подтверждено')+empty('Личный API Bybit не вернул подтверждённые данные счёта. Виртуальные сделки доступны в разделах «Сделки» и «Виртуальный счёт».'); }
  }

  async function trades(){
    const out=$('content'); if(!out)return; out.innerHTML=title('Сделки','Виртуальные операции и реальные исполнения показаны раздельно')+empty('Загрузка…');
    const [virtualResult,realResult]=await Promise.allSettled([request('/api/virtual-account/trades'),account()]);
    if(virtualResult.status!=='fulfilled'){
      out.innerHTML=title('Сделки','Журнал виртуальных операций недоступен')+empty('API виртуального счёта не вернул историю операций.');
      return;
    }
    const virtual=virtualPayload(virtualResult.value), summary=virtual.summary, items=virtual.trades;
    const realItems=realResult.status==='fulfilled'?(realResult.value.trades.length?realResult.value.trades:realResult.value.orders):[];
    const realNote=realResult.status==='fulfilled'?'Личный API Bybit отвечает':'Личный API Bybit не подключён; реальные ордера заблокированы';
    out.innerHTML=title('Сделки','Для каждой операции показано направление, цена, результат и объяснение решения')+
      `<section class="x18-metrics">${card('Всего виртуальных',String(summary.trade_count??items.length))}${card('BUY · покупки',String(summary.buy_count??items.filter(x=>String(x.side).toUpperCase()==='BUY').length))}${card('SELL · продажи',String(summary.sell_count??items.filter(x=>String(x.side).toUpperCase()==='SELL').length))}${card('Открыто',String(summary.open_positions??items.filter(x=>String(x.status).toUpperCase()==='OPEN').length))}${card('Закрыто',String(summary.closed_positions??items.filter(x=>String(x.status).toUpperCase()==='CLOSED').length))}${card('Net PnL',money(summary.net_pnl)+' USDT')}${card('Комиссии',money(summary.total_fees)+' USDT')}${card('Реальные ордера',summary.real_orders_blocked===false?'РАЗРЕШЕНЫ':'ЗАБЛОКИРОВАНЫ',realNote)}</section>`+
      `<section class="x18-grid">${panel('Виртуальные операции с объяснениями',virtualRows(items),'wide')}${panel('Реальные исполнения Bybit',realRows(realItems),'wide')}</section>`;
  }

  async function virtualAccount(){
    const out=$('content'); if(!out)return; out.innerHTML=title('Виртуальный счёт','Проверка стратегий без риска капиталом')+empty('Загрузка…');
    try{
      const raw=await request('/api/virtual-account/state');
      if(raw?.verified === false || raw?.status === 'error' || raw?.status === 'unavailable') throw new Error('Виртуальный счёт не подтверждён');
      const d=virtualPayload(raw), s=d.summary, items=d.trades;
      out.innerHTML=title('Виртуальный счёт','Исполнение виртуальное; котировки, комиссии и PnL рыночные')+`<section class="x18-metrics">${card('Баланс',money(s.cash??s.balance)+' USDT')}${card('Капитал',money(s.equity)+' USDT')}${card('Net PnL',money(s.net_pnl)+' USDT')}${card('Комиссии',money(s.total_fees)+' USDT')}${card('Открыто',String(s.open_positions??0))}${card('Закрыто',String(s.closed_positions??0))}</section>${panel('Все виртуальные операции с объяснениями',virtualRows(items),'wide')}`;
    } catch { out.innerHTML=title('Виртуальный счёт','Контур симуляции недоступен')+empty('Состояние виртуального счёта не подтверждено.'); }
  }

  function settings(){
    const out=$('content'); if(!out)return; let s={}; try{s=JSON.parse(localStorage.getItem('sharipovai-settings')||'{}')}catch{}
    out.innerHTML=title('Настройки','Язык, обновление, рынок, новости и ИИ')+`<section class="x18-grid">${panel('Основные',`<label>Язык<select id="x18lang"><option value="ru">Русский</option><option value="en">English</option><option value="uz">O‘zbek</option></select></label><label>Обновление<select id="x18refresh"><option>3</option><option>5</option><option>10</option><option>30</option><option>60</option></select></label><label>Пара<select id="x18symbol"><option>BTCUSDT</option><option>ETHUSDT</option><option>SOLUSDT</option><option>BNBUSDT</option><option>XRPUSDT</option><option>ADAUSDT</option></select></label>`)}${panel('Фильтры',`<label><input id="x18news" type="checkbox" ${s.verifiedNewsOnly!==false?'checked':''}> Только проверенные новости</label><label><input id="x18ai" type="checkbox" ${s.verifiedOnly?'checked':''}> Только подтверждённые ИИ</label><label><input id="x18compact" type="checkbox" ${s.compact?'checked':''}> Компактный режим</label>`)}${panel('Сохранение','<button class="action" id="x18save">Сохранить</button><button class="action" id="x18reset">Сбросить</button><p id="x18status"></p>','wide')}</section>`;
    $('x18lang').value=s.lang||'ru'; $('x18refresh').value=String(s.refreshSeconds||5); $('x18symbol').value=s.defaultSymbol||'BTCUSDT';
    $('x18save').onclick=()=>{const n={...s,lang:$('x18lang').value,refreshSeconds:Number($('x18refresh').value),defaultSymbol:$('x18symbol').value,verifiedNewsOnly:$('x18news').checked,verifiedOnly:$('x18ai').checked,compact:$('x18compact').checked};localStorage.setItem('sharipovai-settings',JSON.stringify(n));localStorage.setItem('sharipovai-market-symbol',n.defaultSymbol);$('x18status').textContent='Настройки сохранены.';document.querySelector(`[data-lang="${n.lang}"]`)?.click();};
    $('x18reset').onclick=()=>{localStorage.removeItem('sharipovai-settings');$('x18status').textContent='Настройки сброшены.';};
  }

  const pages={bybit,trades,virtual:virtualAccount,settings};
  document.addEventListener('click',e=>{const b=e.target.closest('#nav button[data-page]');if(!b||!pages[b.dataset.page])return;setTimeout(()=>pages[b.dataset.page](),30);});
})();
