(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const symbols = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','ADAUSDT'];
  const state = { truth:null, news:null, quotes:{}, fx:null, fxError:'', errors:{}, loadedAt:null, symbol:savedSymbol(), displayCurrency:savedCurrency() };
  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === 'overview';
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const get = async (url) => { const response = await fetch(url,{credentials:'same-origin',cache:'no-store'}); if(!response.ok) throw new Error(`${response.status}`); return response.json(); };
  const finite = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
  const array = (value) => Array.isArray(value) ? value : [];
  const money = (value,digits=2) => finite(value) == null ? '—' : Number(value).toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits});
  const signed = (value,digits=2) => { const n=finite(value); return n==null?'—':`${n>0?'+':''}${n.toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits})}`; };
  const percent = (value,digits=2) => finite(value)==null?'—':`${Number(value).toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits})}%`;
  const price = (value) => { const n=finite(value); if(n==null)return '—'; const digits=Math.abs(n)>=100?1:Math.abs(n)>=10?2:4; return n.toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits}); };
  const card = (label,value,note='',tone='') => `<article class="card"><span>${esc(label)}</span><strong class="${esc(tone)}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
  const row = (label,value,tone='') => `<div class="v10-row"><span>${esc(label)}</span><b class="${esc(tone)}">${esc(value)}</b></div>`;
  const panel = (title,body,wide='') => `<article class="panel ${wide}"><small>CANONICAL TRUTH</small><h2>${esc(title)}</h2>${body}</article>`;
  const empty = (text) => `<div class="empty">${esc(text)}</div>`;

  function savedSymbol(){
    const value=String(localStorage.getItem('sharipovai-market-symbol')||'BTCUSDT').replace(/[^A-Za-z0-9]/g,'').toUpperCase();
    return symbols.includes(value)?value:'BTCUSDT';
  }
  function savedCurrency(){ return String(localStorage.getItem('sharipovai-display-currency')||'USDT').toUpperCase()==='RUB'?'RUB':'USDT'; }
  function fxRate(){ const rate=finite(state.fx?.rub_per_usdt_estimate??state.fx?.rub_per_usd); return rate!=null&&rate>0?rate:null; }
  function displayAmount(value){
    const amount=finite(value); if(amount==null)return '—';
    const rate=fxRate();
    if(state.displayCurrency==='RUB'&&rate)return `≈ ${Math.round(amount*rate).toLocaleString('ru-RU')} ₽`;
    return `${money(amount,2)} USDT`;
  }
  function displayNote(value,note){
    const amount=finite(value),rate=fxRate(); if(amount==null)return note;
    if(state.displayCurrency==='RUB')return rate?`${money(amount,2)} USDT · ${note}`:`${money(amount,2)} USDT · курс RUB недоступен`;
    return rate?`≈ ${Math.round(amount*rate).toLocaleString('ru-RU')} ₽ · ${note}`:note;
  }

  function paper(){ return state.truth?.paper || {}; }
  function summary(){ return paper().summary || {}; }
  function trades(){ return array(paper().trades || paper().state?.trades); }
  function organs(){ return state.truth?.organs || {}; }
  function news(){
    const raw=state.news||{};
    return array(raw.news?.items||raw.news||raw.items||raw.articles).slice(0,5);
  }

  function tradeCard(trade){
    const side=String(trade.side||'').toUpperCase();
    const status=String(trade.status||'').toUpperCase()||'UNKNOWN';
    const net=finite(trade.net_pnl);
    const tone=net==null?'':net>=0?'positive':'negative';
    const symbol=trade.symbol||trade.asset||'—';
    return `<article class="trade-card"><div class="trade-card-head"><div><div class="trade-card-title"><h3>${esc(symbol)}</h3><span class="status-chip ${side==='BUY'?'buy':'sell'}">${esc(side||'—')}</span><span class="status-chip ${status==='CLOSED'?'closed':'open'}">${esc(status)}</span></div><div class="trade-card-subtitle">CouncilAuthorizedPaperLoop · реальный ордер не отправлялся</div></div></div><div class="trade-card-grid"><div class="trade-metric"><span>Размер</span><b>${esc(money(trade.notional,2))} USDT</b></div><div class="trade-metric"><span>Цена входа</span><b>${esc(price(trade.entry_price))}</b></div><div class="trade-metric"><span>Цена выхода / текущая</span><b>${esc(price(trade.exit_price??trade.current_price))}</b></div><div class="trade-metric"><span>Комиссии</span><b>${esc(money(trade.fee??trade.total_fees,4))} USDT</b></div><div class="trade-metric total"><span>Net PnL</span><b class="${tone}">${esc(signed(net,4))} USDT</b></div></div><div class="trade-explanation"><p>${esc(trade.entry_reason_ru||trade.reason||'Причина хранится в каноническом журнале решения.')}</p></div></article>`;
  }

  function quoteTable(){
    const rows=symbols.map((symbol)=>{
      const quote=state.quotes[symbol]||{};
      const change=finite(quote.change_24h_percent);
      return `<tr data-overview-symbol="${symbol}" class="${symbol===state.symbol?'selected':''}"><td><b>${esc(symbol.replace('USDT','/USDT'))}</b></td><td>${esc(price(quote.price))} USDT</td><td class="${change!=null?(change>=0?'positive':'negative'):''}">${esc(percent(change))}</td><td>${esc(quote.source||'—')}</td></tr>`;
    }).join('');
    return `<div class="status-actions"><label>Пара <select id="overviewSymbol">${symbols.map((symbol)=>`<option value="${symbol}" ${symbol===state.symbol?'selected':''}>${symbol.replace('USDT','/USDT')}</option>`).join('')}</select></label><button id="overviewOpenMarket" class="action" type="button">Рыночный терминал</button></div><table class="v10-table"><thead><tr><th>Пара</th><th>Цена</th><th>24 часа</th><th>Источник</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function render(){
    if(!active())return;
    const content=$('content'); if(!content)return;
    const truth=state.truth||{};
    const s=summary();
    const organ=organs();
    const counts=organ.counts||{};
    const runtimeStatus=String(truth.status||'unavailable').toUpperCase();
    const runtimeTone=runtimeStatus==='HEALTHY'?'positive':'negative';
    const source=truth.source_of_truth?.paper||'не подтверждён';
    const latest=trades().slice().reverse().slice(0,4);
    const latestHtml=latest.length?`<div class="trade-list overview-trade-list">${latest.map(tradeCard).join('')}</div>`:empty('Канонический paper runtime пока не сохранил сделок.');
    const newsRows=news().length?news().map((item)=>`<div class="news-item"><b>${esc(item.title||item.headline||'Новость')}</b><small>${esc(item.source||item.publisher||'Источник не указан')}</small></div>`).join(''):empty('Подтверждённые новости пока не получены.');
    const quote=state.quotes[state.symbol]||{};
    const unavailable=Object.keys(state.errors).length;

    content.innerHTML=`<div class="title"><h1>Канонический центр управления</h1><p>Один источник paper-состояния, один RiskService, явные блокировки и доказательства</p></div>
      <div class="status-actions"><label>Капитал <select id="overviewDisplayCurrency"><option value="USDT" ${state.displayCurrency==='USDT'?'selected':''}>USDT</option><option value="RUB" ${state.displayCurrency==='RUB'?'selected':''}>Рубли ₽</option></select></label><span>Источник: ${esc(source)} · ${esc(state.loadedAt||'не обновлено')}</span></div>
      <section class="metrics">
        ${card('Runtime truth',runtimeStatus,'не равен доступности HTTP',runtimeTone)}
        ${card('Equity',displayAmount(s.equity),displayNote(s.equity,'канонический paper runtime'))}
        ${card('Cash',displayAmount(s.cash),displayNote(s.cash,'свободный виртуальный капитал'))}
        ${card('Открытые позиции',String(s.open_positions??0),'CouncilAuthorizedPaperLoop')}
        ${card('Сделки',String(s.trade_count??0),'полная история в ProjectDatabase')}
        ${card('Net PnL',displayAmount(s.net_pnl),displayNote(s.net_pnl,'realized + unrealized'),finite(s.net_pnl)!=null?(Number(s.net_pnl)>=0?'positive':'negative'):'')}
      </section>
      <section class="v10-grid">
        ${panel(`Рынок · ${state.symbol.replace('USDT','/USDT')}`,`${row('Цена',quote.price!=null?price(quote.price)+' USDT':'—',quote.price!=null?'positive':'')}${row('За 24 часа',percent(quote.change_24h_percent),Number(quote.change_24h_percent)>=0?'positive':'negative')}${row('Источник',quote.source||'—')}${quoteTable()}`,'wide')}
        <article class="panel wide"><div class="section-head"><div><small>CANONICAL PAPER</small><h2>Последние операции</h2><p>Только журнал CouncilAuthorizedPaperLoop. Legacy PaperActivityEngine не используется.</p></div><div class="section-actions"><button id="overviewOpenTrades" class="action" type="button">Все сделки</button></div></div>${latestHtml}</article>
        ${panel('Новости',newsRows)}
        ${panel('Проверяемая реальность',`${row('Органы healthy',String(counts.healthy??0),(counts.healthy??0)?'positive':'')}${row('Органы degraded',String(counts.degraded??0),(counts.degraded??0)?'negative':'')}${row('Органы blocked',String(counts.blocked??0),(counts.blocked??0)?'negative':'positive')}${row('Paper worker',s.worker_running?'RUNNING':'STOPPED',s.worker_running?'positive':'negative')}${row('ProjectDatabase',s.database_backed?'BACKED':'NOT CONFIRMED',s.database_backed?'positive':'negative')}${row('Real orders',truth.safety?.real_orders_blocked?'BLOCKED':'UNSAFE',truth.safety?.real_orders_blocked?'positive':'negative')}${row('Ошибки загрузки',String(unavailable),unavailable?'negative':'positive')}`)}
      </section>`;
    bind();
  }

  function bind(){
    $('overviewDisplayCurrency')?.addEventListener('change',(event)=>{state.displayCurrency=event.target.value==='RUB'?'RUB':'USDT';localStorage.setItem('sharipovai-display-currency',state.displayCurrency);render();});
    $('overviewSymbol')?.addEventListener('change',(event)=>{state.symbol=symbols.includes(event.target.value)?event.target.value:'BTCUSDT';localStorage.setItem('sharipovai-market-symbol',state.symbol);render();});
    document.querySelectorAll('[data-overview-symbol]').forEach((element)=>element.addEventListener('click',()=>{state.symbol=element.dataset.overviewSymbol;localStorage.setItem('sharipovai-market-symbol',state.symbol);render();}));
    $('overviewOpenMarket')?.addEventListener('click',()=>document.querySelector('#nav button[data-page="market"]')?.click());
    $('overviewOpenTrades')?.addEventListener('click',()=>document.querySelector('#nav button[data-page="trades"]')?.click());
  }

  async function load(){
    if(!active())return;
    const entries=[['truth','/api/system/runtime-truth'],['news','/api/social-news']];
    const [core,quotes,fx]=await Promise.all([
      Promise.allSettled(entries.map(([,url])=>get(url))),
      Promise.allSettled(symbols.map((symbol)=>get(`/api/market/quote/${symbol}`))),
      get('/api/currency/usd-rub').then((value)=>({ok:true,value})).catch((error)=>({ok:false,error})),
    ]);
    state.errors={};
    core.forEach((result,index)=>{const key=entries[index][0];if(result.status==='fulfilled')state[key]=result.value;else state.errors[key]=result.reason?.message||'недоступно';});
    quotes.forEach((result,index)=>{const symbol=symbols[index];if(result.status==='fulfilled')state.quotes[symbol]=result.value;else state.errors[`quote_${symbol}`]=result.reason?.message||'недоступно';});
    if(fx.ok){state.fx=fx.value;state.fxError='';}else state.fxError=fx.error?.message||'недоступно';
    state.loadedAt=new Date().toLocaleString('ru-RU');
    render();
  }

  document.addEventListener('click',(event)=>{if(event.target.closest('#nav button[data-page="overview"]'))setTimeout(()=>load().catch(()=>{}),0);});
  $('refresh')?.addEventListener('click',()=>{if(active())setTimeout(()=>load().catch(()=>{}),0);});
  window.addEventListener('DOMContentLoaded',()=>{if(active())load().catch(()=>{});});
  setInterval(()=>{if(active()&&!document.hidden)load().catch(()=>{});},10000);
})();
