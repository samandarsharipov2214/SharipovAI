(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const list = (...values) => values.find(Array.isArray) || [];
  const number = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('ru-RU',{maximumFractionDigits:8}) : '—';
  const time = value => { if(!value) return '—'; const d=new Date(value); return Number.isNaN(d.getTime())?'—':d.toLocaleString('ru-RU'); };
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

  async function bybit(){
    const out=$('content'); if(!out)return; out.innerHTML=title('Bybit','Проверка личного кабинета и состояния подключения')+empty('Загрузка…');
    try{
      const a=await account(), d=a.data;
      const equity=d.total_equity??d.totalEquity??d.equity;
      const available=d.total_available_balance??d.totalAvailableBalance??d.available_balance;
      out.innerHTML=title('Bybit','Фактические данные личного кабинета')+`<section class="x18-metrics">${card('Подключение','ПОДТВЕРЖДЕНО','Получен проверенный ответ личного API')}${card('Капитал',equity!=null?number(equity)+' USDT':'—')}${card('Доступно',available!=null?number(available)+' USDT':'—')}${card('Позиции',String(a.positions.length))}${card('Ордера',String(a.orders.length))}</section><section class="x18-grid">${panel('Активы',a.assets.length?`<table class="x18-table"><thead><tr><th>Актив</th><th>Баланс</th><th>Доступно</th></tr></thead><tbody>${a.assets.map(x=>`<tr><td>${esc(x.coin||x.asset||x.symbol||'—')}</td><td>${esc(x.walletBalance??x.balance??'—')}</td><td>${esc(x.availableBalance??x.available??'—')}</td></tr>`).join('')}</tbody></table>`:empty('Состав активов не передан.'),'wide')}${panel('Безопасность','<p>Данные доступа не отображаются. Вывод средств должен быть отключён. Синтетический баланс запрещён.</p>')}</section>`;
    } catch { out.innerHTML=title('Bybit','Подключение не подтверждено')+empty('Личный API Bybit не вернул подтверждённые данные счёта.'); }
  }

  async function trades(){
    const out=$('content'); if(!out)return; out.innerHTML=title('Сделки','Реальный журнал исполнения')+empty('Загрузка…');
    try{
      const a=await account(), items=a.trades.length?a.trades:a.orders;
      const rows=items.length?`<table class="x18-table"><thead><tr><th>Время</th><th>Пара</th><th>Сторона</th><th>Цена</th><th>Количество</th><th>Результат</th></tr></thead><tbody>${items.slice(0,200).map(x=>`<tr><td>${time(x.execTime||x.createdTime||x.time||x.created_at)}</td><td>${esc(x.symbol||'—')}</td><td>${esc(x.side||'—')}</td><td>${esc(x.execPrice??x.price??'—')}</td><td>${esc(x.execQty??x.qty??x.size??'—')}</td><td>${esc(x.closedPnl??x.pnl??x.orderStatus??x.status??'—')}</td></tr>`).join('')}</tbody></table>`:empty('Подтверждённые исполнения не получены.');
      out.innerHTML=title('Сделки','Операции из личного кабинета без демонстрационных записей')+`<section class="x18-metrics">${card('Записей',String(items.length))}${card('Источник','Bybit')}${card('Обновлено',new Date().toLocaleTimeString('ru-RU'))}</section>${panel('История исполнения',rows,'wide')}`;
    } catch { out.innerHTML=title('Сделки','Журнал недоступен')+empty('Биржа не вернула подтверждённую историю операций.'); }
  }

  async function virtualAccount(){
    const out=$('content'); if(!out)return; out.innerHTML=title('Виртуальный счёт','Проверка стратегий без риска капиталом')+empty('Загрузка…');
    try{
      const d=await request('/api/virtual-account/state');
      if(d?.verified === false || d?.status === 'error' || d?.status === 'unavailable') throw new Error('Виртуальный счёт не подтверждён');
      const items=list(d.trades,d.orders,d.history);
      out.innerHTML=title('Виртуальный счёт','Симуляция на реальных рыночных данных')+`<section class="x18-metrics">${card('Баланс',d.balance!=null?number(d.balance)+' USDT':d.equity!=null?number(d.equity)+' USDT':'—')}${card('PnL',d.pnl!=null?number(d.pnl)+' USDT':'—')}${card('Просадка',d.drawdown_percent!=null?number(d.drawdown_percent)+'%':'—')}${card('Сделки',String(items.length||d.trade_count||0))}</section>${panel('Операции',items.length?`<table class="x18-table"><thead><tr><th>Время</th><th>Актив</th><th>Сторона</th><th>Результат</th></tr></thead><tbody>${items.slice(0,100).map(x=>`<tr><td>${time(x.time||x.created_at)}</td><td>${esc(x.symbol||x.asset||'—')}</td><td>${esc(x.side||'—')}</td><td>${esc(x.net_pnl??x.pnl??x.status??'—')}</td></tr>`).join('')}</tbody></table>`:empty('Операции пока не получены.'),'wide')}`;
    } catch { out.innerHTML=title('Виртуальный счёт','Контур симуляции недоступен')+empty('Состояние виртуального счёта не подтверждено.'); }
  }

  function settings(){
    const out=$('content'); if(!out)return; let s={}; try{s=JSON.parse(localStorage.getItem('sharipovai-settings')||'{}')}catch{}
    out.innerHTML=title('Настройки','Язык, обновление, рынок, новости и ИИ')+`<section class="x18-grid">${panel('Основные',`<label>Язык<select id="x18lang"><option value="ru">Русский</option><option value="en">English</option><option value="uz">O‘zbek</option></select></label><label>Обновление<select id="x18refresh"><option>3</option><option>5</option><option>10</option><option>30</option><option>60</option></select></label><label>Пара<select id="x18symbol"><option>BTCUSDT</option><option>ETHUSDT</option><option>SOLUSDT</option><option>BNBUSDT</option><option>XRPUSDT</option></select></label>`)}${panel('Фильтры',`<label><input id="x18news" type="checkbox" ${s.verifiedNewsOnly!==false?'checked':''}> Только проверенные новости</label><label><input id="x18ai" type="checkbox" ${s.verifiedOnly?'checked':''}> Только подтверждённые ИИ</label><label><input id="x18compact" type="checkbox" ${s.compact?'checked':''}> Компактный режим</label>`)}${panel('Сохранение','<button class="action" id="x18save">Сохранить</button><button class="action" id="x18reset">Сбросить</button><p id="x18status"></p>','wide')}</section>`;
    $('x18lang').value=s.lang||'ru'; $('x18refresh').value=String(s.refreshSeconds||5); $('x18symbol').value=s.defaultSymbol||'BTCUSDT';
    $('x18save').onclick=()=>{const n={...s,lang:$('x18lang').value,refreshSeconds:Number($('x18refresh').value),defaultSymbol:$('x18symbol').value,verifiedNewsOnly:$('x18news').checked,verifiedOnly:$('x18ai').checked,compact:$('x18compact').checked};localStorage.setItem('sharipovai-settings',JSON.stringify(n));$('x18status').textContent='Настройки сохранены.';document.querySelector(`[data-lang="${n.lang}"]`)?.click();};
    $('x18reset').onclick=()=>{localStorage.removeItem('sharipovai-settings');$('x18status').textContent='Настройки сброшены.';};
  }

  const pages={bybit,trades,virtual:virtualAccount,settings};
  document.addEventListener('click',e=>{const b=e.target.closest('#nav button[data-page]');if(!b||!pages[b.dataset.page])return;setTimeout(()=>pages[b.dataset.page](),30);});
})();