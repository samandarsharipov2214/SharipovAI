(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = (v, d=2) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('ru-RU',{maximumFractionDigits:d}) : '—';
  const arr = (...v) => v.find(Array.isArray) || [];
  const get = async (url) => { const r=await fetch(url,{credentials:'same-origin',cache:'no-store'}); if(!r.ok) throw new Error(String(r.status)); return r.json(); };
  const state = { account:null, run:null, virtual:null, report:null, errors:{}, loadedAt:null };

  function virtualData(){
    const raw=state.virtual||{};
    const root=raw.state&&typeof raw.state==='object'?raw.state:raw;
    const summary=root.summary||raw.summary||{};
    const trades=arr(root.trades,raw.trades,root.orders,root.history);
    const positions=trades.filter(x=>String(x.status||'').toUpperCase()==='OPEN');
    return {summary,trades,positions};
  }

  function account(){
    const raw=state.account||{}, x=raw.snapshot||raw.account||raw.result||raw;
    const realEquity=x.total_equity??x.totalEquity??x.equity;
    const realPositions=arr(x.positions,raw.positions);
    const realAssets=arr(x.assets,x.coins,x.coin,raw.assets);
    const realConnected=Boolean(state.account&&!state.errors.account&&(realEquity!=null||realPositions.length||realAssets.length));
    if(realConnected){
      return {
        equity:realEquity,
        available:x.total_available_balance??x.totalAvailableBalance??x.available_balance,
        wallet:x.total_wallet_balance??x.totalWalletBalance??x.wallet_balance,
        positions:realPositions, assets:realAssets, connected:true, source:'Bybit private API', virtual:false,
      };
    }
    const v=virtualData(), s=v.summary;
    return {
      equity:s.equity, available:s.cash, wallet:s.cash,
      positions:v.positions, assets:v.positions, connected:Boolean(s.market_price_accounting),
      source:'Виртуальный счёт · котировки Bybit', virtual:true,
    };
  }

  const card=(l,v,n='',c='')=>`<article class="card"><span>${esc(l)}</span><strong class="${c}">${esc(v)}</strong><small>${esc(n)}</small></article>`;
  const row=(l,v,c='')=>`<div class="pr16-row"><span>${esc(l)}</span><b class="${c}">${esc(v)}</b></div>`;
  const empty=(t)=>`<div class="empty">${esc(t)}</div>`;
  const title=(h,p)=>`<div class="title"><h1>${esc(h)}</h1><p>${esc(p)}</p></div>`;
  const panel=(h,b,c='')=>`<article class="panel ${c}"><small>SHARIPOVAI</small><h2>${esc(h)}</h2>${b}</article>`;

  function positionValue(x){ return Number(x.usdValue??x.usd_value??x.positionValue??x.value??x.walletBalance??x.notional??0)||0; }
  function positionPnl(x){ return Number(x.unrealisedPnl??x.unrealized_pnl??x.net_pnl??x.pnl??0)||0; }

  function portfolio(){
    const a=account(); const total=Number(a.equity)||0;
    const items=a.assets.length?a.assets:a.positions;
    let gross=0, pnl=0;
    const allocations=items.map((x)=>{
      const value=positionValue(x), upnl=positionPnl(x);
      gross+=Math.abs(value); pnl+=upnl;
      const share=total>0?Math.abs(value)/total*100:null;
      return `<div class="pr16-allocation"><div><b>${esc(x.coin||x.symbol||x.asset||'Актив')}</b><span>${share==null?'—':num(share)+'%'}</span></div><progress max="100" value="${share==null?0:Math.min(100,share)}"></progress><small>${value?num(value,8)+' USDT':'Стоимость не передана'}</small></div>`;
    }).join('');
    const concentration=total>0&&items.length?Math.max(...items.map(x=>Math.abs(positionValue(x))/total*100)):null;
    const exposure=total>0?gross/total*100:null;
    const positions=a.positions.length?`<table class="v10-table"><thead><tr><th>Инструмент</th><th>Сторона</th><th>Размер</th><th>Вход</th><th>Текущая цена</th><th>Net PnL</th><th>Статус</th></tr></thead><tbody>${a.positions.map(p=>`<tr><td>${esc(p.symbol||p.asset||'—')}</td><td>${esc(p.side||'—')}</td><td>${esc(p.size??p.qty??p.quantity??'—')}</td><td>${esc(p.avgPrice??p.entryPrice??p.entry_price??'—')}</td><td>${esc(p.markPrice??p.lastPrice??p.current_price??'—')}</td><td>${esc(p.unrealisedPnl??p.unrealized_pnl??p.net_pnl??'—')}</td><td>${esc(p.status??'OPEN')}</td></tr>`).join('')}</tbody></table>`:empty('Открытых позиций нет.');
    return title('Портфель',a.virtual?'Виртуальный капитал и позиции по подтверждённым рыночным котировкам Bybit':'Капитал, распределение, доходность и концентрация по личному API Bybit')+
      `<section class="metrics">${card('Капитал',total?num(total,8)+' USDT':'—',a.source)}${card('Доступно',a.available!=null?num(a.available,8)+' USDT':'—','Свободные средства')}${card('Нереализованный PnL',items.length?num(pnl,8)+' USDT':'0 USDT','Сумма открытых позиций',pnl>=0?'positive':'negative')}${card('Рыночная экспозиция',exposure!=null?num(exposure)+'%':'0%','От капитала')}${card('Макс. концентрация',concentration!=null?num(concentration)+'%':'0%','Крупнейший актив')}</section>`+
      `<section class="pr16-grid">${panel('Распределение капитала',allocations||empty('Открытых позиций нет.'))}${panel('Позиции',positions,'wide')}${panel('Контроль данных',row('Источник',a.source,a.connected?'positive':'negative')+row('Реальные ордера',a.virtual?'заблокированы':'по разрешениям API','positive')+row('Синтетические котировки','запрещены','positive')+row('Последнее обновление',state.loadedAt||'—'))}</section>`;
  }

  function risk(){
    const a=account(), run=state.run||{}, raw=state.virtual||{}, root=raw.state&&typeof raw.state==='object'?raw.state:raw, s=root.summary||raw.summary||{}, r=state.report||{};
    const limits=run.risk_limits||run.limits||r.risk_limits||{};
    const warnings=arr(run.risk_warnings,run.warnings,r.warnings);
    const equity=Number(a.equity)||0;
    const gross=a.positions.reduce((sum,p)=>sum+Math.abs(positionValue(p)),0);
    const exposure=equity>0?gross/equity*100:0;
    const drawdown=s.drawdown_percent??root.drawdown_percent??run.drawdown_percent??r.drawdown_percent;
    const dailyLoss=run.daily_loss_percent??r.daily_loss_percent;
    const maxDrawdown=limits.max_drawdown_percent;
    const maxTrade=limits.max_trade_risk_percent;
    const blocked=Boolean(run.block_trading||run.trading_blocked||run.risk_veto||root.trading_blocked||s.real_orders_blocked!==false);
    const checks=[
      ['Вывод средств','Запрещён',true],['Ордера без проверки','Запрещены',true],
      ['Реальные ордера',s.real_orders_blocked!==false?'Заблокированы':'Разрешены',s.real_orders_blocked!==false],
      ['Рыночный учёт PnL',s.market_price_accounting===true?'Подтверждён':'Не подтверждён',s.market_price_accounting===true],
    ];
    return title('Центр рисков','Просадка, экспозиция, лимиты, предупреждения и блокировка торговли')+
      `<section class="metrics">${card('Уровень риска',run.risk_level||'LOW','Фактическая оценка')}${card('Экспозиция',num(exposure)+'%','Открытые позиции')}${card('Просадка',drawdown!=null?num(drawdown)+'%':'—','Подтверждённое значение')}${card('Дневной убыток',dailyLoss!=null?num(dailyLoss)+'%':'—','Если API передал')}${card('Реальная торговля',s.real_orders_blocked!==false?'ЗАБЛОКИРОВАНА':'РАЗРЕШЕНА','Защитный контур',s.real_orders_blocked!==false?'positive':'negative')}</section>`+
      `<section class="pr16-grid">${panel('Лимиты риска',row('Максимальный риск сделки',maxTrade!=null?num(maxTrade)+'%':'не передан')+row('Максимальная просадка',maxDrawdown!=null?num(maxDrawdown)+'%':'не передана')+row('Максимальная экспозиция',limits.max_exposure_percent!=null?num(limits.max_exposure_percent)+'%':'не передана')+row('Лимит дневного убытка',limits.max_daily_loss_percent!=null?num(limits.max_daily_loss_percent)+'%':'не передан'))}${panel('Защитные проверки',checks.map(x=>row(x[0],x[1],x[2]?'positive':'negative')).join(''))}${panel('Предупреждения',warnings.length?warnings.map(w=>`<div class="pr16-warning"><b>${esc(w.title||w.code||'Предупреждение')}</b><p>${esc(w.message||w.description||w)}</p></div>`).join(''):empty('Активные подтверждённые предупреждения не получены.'),'wide')}</section>`;
  }

  async function load(page){
    const entries=[['account','/api/exchange/account/snapshot'],['run','/api/run'],['virtual','/api/virtual-account/state'],['report','/api/ai-control-center/daily-report']];
    const rs=await Promise.allSettled(entries.map(([,u])=>get(u))); state.errors={};
    rs.forEach((x,i)=>{const k=entries[i][0]; if(x.status==='fulfilled') state[k]=x.value; else state.errors[k]=x.reason?.message||'недоступно';});
    state.loadedAt=new Date().toLocaleString('ru-RU');
    const c=$('content'); if(c) c.innerHTML=page==='portfolio'?portfolio():risk();
  }
  document.addEventListener('click',(e)=>{const b=e.target.closest('#nav button[data-page]'); if(!b||!['portfolio','risk'].includes(b.dataset.page)) return; setTimeout(()=>load(b.dataset.page),20);});
  window.addEventListener('DOMContentLoaded',()=>{const p=document.querySelector('#nav button.active')?.dataset.page; if(['portfolio','risk'].includes(p)) load(p);});
})();
