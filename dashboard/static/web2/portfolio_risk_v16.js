(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = (v, d=2) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('ru-RU',{maximumFractionDigits:d}) : '—';
  const arr = (...v) => v.find(Array.isArray) || [];
  const get = async (url) => { const r=await fetch(url,{credentials:'same-origin',cache:'no-store'}); if(!r.ok) throw new Error(String(r.status)); return r.json(); };
  const state = { account:null, run:null, virtual:null, report:null, errors:{}, loadedAt:null };

  function account(){
    const raw=state.account||{}, x=raw.snapshot||raw.account||raw.result||raw;
    return {
      equity:x.total_equity??x.totalEquity??x.equity,
      available:x.total_available_balance??x.totalAvailableBalance??x.available_balance,
      wallet:x.total_wallet_balance??x.totalWalletBalance??x.wallet_balance,
      positions:arr(x.positions,raw.positions), assets:arr(x.assets,x.coins,x.coin,raw.assets),
      connected:Boolean(state.account&&!state.errors.account)
    };
  }
  const card=(l,v,n='',c='')=>`<article class="card"><span>${esc(l)}</span><strong class="${c}">${esc(v)}</strong><small>${esc(n)}</small></article>`;
  const row=(l,v,c='')=>`<div class="pr16-row"><span>${esc(l)}</span><b class="${c}">${esc(v)}</b></div>`;
  const empty=(t)=>`<div class="empty">${esc(t)}</div>`;
  const title=(h,p)=>`<div class="title"><h1>${esc(h)}</h1><p>${esc(p)}</p></div>`;
  const panel=(h,b,c='')=>`<article class="panel ${c}"><small>SHARIPOVAI</small><h2>${esc(h)}</h2>${b}</article>`;

  function portfolio(){
    const a=account(); const total=Number(a.equity)||0;
    const items=a.assets.length?a.assets:a.positions;
    let gross=0, pnl=0;
    const allocations=items.map((x)=>{
      const value=Number(x.usdValue??x.usd_value??x.positionValue??x.value??x.walletBalance??0)||0;
      const upnl=Number(x.unrealisedPnl??x.unrealized_pnl??x.pnl??0)||0;
      gross+=Math.abs(value); pnl+=upnl;
      const share=total>0?Math.abs(value)/total*100:null;
      return `<div class="pr16-allocation"><div><b>${esc(x.coin||x.symbol||x.asset||'Актив')}</b><span>${share==null?'—':num(share)+'%'}</span></div><progress max="100" value="${share==null?0:Math.min(100,share)}"></progress><small>${value?num(value,8)+' USDT':'Стоимость не передана'}</small></div>`;
    }).join('');
    const concentration=total>0&&items.length?Math.max(...items.map(x=>Math.abs(Number(x.usdValue??x.usd_value??x.positionValue??x.value??x.walletBalance??0)||0)/total*100)):null;
    const exposure=total>0?gross/total*100:null;
    const positions=a.positions.length?`<table class="v10-table"><thead><tr><th>Инструмент</th><th>Сторона</th><th>Размер</th><th>Вход</th><th>Текущая цена</th><th>PnL</th><th>Плечо</th></tr></thead><tbody>${a.positions.map(p=>`<tr><td>${esc(p.symbol||'—')}</td><td>${esc(p.side||'—')}</td><td>${esc(p.size??p.qty??'—')}</td><td>${esc(p.avgPrice??p.entryPrice??p.entry_price??'—')}</td><td>${esc(p.markPrice??p.lastPrice??'—')}</td><td>${esc(p.unrealisedPnl??p.unrealized_pnl??'—')}</td><td>${esc(p.leverage??'—')}</td></tr>`).join('')}</tbody></table>`:empty('Открытые позиции не получены.');
    return title('Портфель','Капитал, распределение, доходность и концентрация по подтверждённым данным Bybit')+
      `<section class="metrics">${card('Капитал',total?num(total,8)+' USDT':'—',a.connected?'Bybit':'Нет подтверждения биржи')}${card('Доступно',a.available!=null?num(a.available,8)+' USDT':'—','Свободные средства')}${card('Нереализованный PnL',items.length?num(pnl,8)+' USDT':'—','Сумма полученных позиций',pnl>=0?'positive':'negative')}${card('Рыночная экспозиция',exposure!=null?num(exposure)+'%':'—','От капитала')}${card('Макс. концентрация',concentration!=null?num(concentration)+'%':'—','Крупнейший актив')}</section>`+
      `<section class="pr16-grid">${panel('Распределение капитала',allocations||empty('Состав активов не получен.'))}${panel('Позиции',positions,'wide')}${panel('Контроль данных',row('Источник',a.connected?'Bybit':'не подтверждён',a.connected?'positive':'negative')+row('Синтетические значения','запрещены','positive')+row('Последнее обновление',state.loadedAt||'—'))}</section>`;
  }

  function risk(){
    const a=account(), run=state.run||{}, v=state.virtual||{}, r=state.report||{};
    const limits=run.risk_limits||run.limits||r.risk_limits||{};
    const warnings=arr(run.risk_warnings,run.warnings,r.warnings);
    const equity=Number(a.equity)||0;
    const gross=a.positions.reduce((s,p)=>s+Math.abs(Number(p.positionValue??p.position_value??0)||0),0);
    const exposure=equity>0?gross/equity*100:null;
    const drawdown=v.drawdown_percent??run.drawdown_percent??r.drawdown_percent;
    const dailyLoss=run.daily_loss_percent??r.daily_loss_percent;
    const maxDrawdown=limits.max_drawdown_percent;
    const maxTrade=limits.max_trade_risk_percent;
    const blocked=Boolean(run.block_trading||run.trading_blocked||run.risk_veto||v.trading_blocked);
    const checks=[
      ['Вывод средств','Запрещён',true],['Ордера без проверки','Запрещены',true],
      ['Аварийная остановка',run.kill_switch_active===true?'Активна':run.kill_switch_active===false?'Готова':'Не подтверждена',run.kill_switch_active!==undefined],
      ['Право вето риска',run.risk_veto===true?'Применено':'Доступно',true]
    ];
    return title('Центр рисков','Просадка, экспозиция, лимиты, предупреждения и блокировка торговли')+
      `<section class="metrics">${card('Уровень риска',run.risk_level||'—','Фактическая оценка')}${card('Экспозиция',exposure!=null?num(exposure)+'%':'—','Открытые позиции')}${card('Просадка',drawdown!=null?num(drawdown)+'%':'—','Подтверждённое значение')}${card('Дневной убыток',dailyLoss!=null?num(dailyLoss)+'%':'—','Если API передал')}${card('Торговля',blocked?'ЗАБЛОКИРОВАНА':'НЕ ЗАБЛОКИРОВАНА',blocked?'Сработала защита':'Нет подтверждённой блокировки',blocked?'negative':'positive')}</section>`+
      `<section class="pr16-grid">${panel('Лимиты риска',row('Максимальный риск сделки',maxTrade!=null?num(maxTrade)+'%':'не передан')+row('Максимальная просадка',maxDrawdown!=null?num(maxDrawdown)+'%':'не передана')+row('Максимальная экспозиция',limits.max_exposure_percent!=null?num(limits.max_exposure_percent)+'%':'не передана')+row('Лимит дневного убытка',limits.max_daily_loss_percent!=null?num(limits.max_daily_loss_percent)+'%':'не передан'))}${panel('Защитные проверки',checks.map(x=>row(x[0],x[1],x[2]?'positive':'')).join(''))}${panel('Предупреждения',warnings.length?warnings.map(w=>`<div class="pr16-warning"><b>${esc(w.title||w.code||'Предупреждение')}</b><p>${esc(w.message||w.description||w)}</p></div>`).join(''):empty('Активные подтверждённые предупреждения не получены.'),'wide')}</section>`;
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