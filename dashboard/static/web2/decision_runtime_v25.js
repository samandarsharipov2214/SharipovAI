(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const num = (value, digits=4) => Number.isFinite(Number(value)) ? Number(value).toLocaleString('ru-RU',{maximumFractionDigits:digits}) : '—';
  const arr = (...values) => values.find(Array.isArray) || [];
  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === 'decision';
  const get = async (url) => { const response=await fetch(url,{credentials:'same-origin',cache:'no-store'}); if(!response.ok) throw new Error(String(response.status)); return response.json(); };
  const state = { run:null, virtual:null, evidence:null, loadedAt:null, errors:{} };
  const card = (label,value,note='',tone='') => `<article class="card"><span>${esc(label)}</span><strong class="${esc(tone)}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
  const panel = (heading,body,wide='') => `<article class="panel ${wide}"><small>SHARIPOVAI</small><h2>${esc(heading)}</h2>${body}</article>`;
  const empty = (text) => `<div class="empty">${esc(text)}</div>`;
  const row = (label,value,tone='') => `<div class="v10-row"><span>${esc(label)}</span><b class="${esc(tone)}">${esc(value)}</b></div>`;

  function virtualData(){
    const raw=state.virtual||{};
    const root=raw.state&&typeof raw.state==='object'?raw.state:raw;
    return {summary:root.summary||raw.summary||{},trades:arr(root.trades,raw.trades,root.orders,root.history)};
  }

  function render(){
    if(!active()) return;
    const content=$('content'); if(!content) return;
    const run=state.run||{};
    const virtual=virtualData(), s=virtual.summary;
    const canonical=run.decision||'NO_DECISION';
    const canonicalReason=run.reason||run.report||'Канонический контур не передал исполнимое решение.';
    const diagnostic=String(canonicalReason).toLowerCase().includes('legacy offline runner');
    const tickStatus=s.last_tick_status||'—';
    const tickReason=s.last_reason_ru||s.last_reason||'Виртуальный контур ещё не передал последнее действие.';
    const evidence=arr(state.evidence?.items,state.evidence?.records,state.evidence?.events,state.evidence).slice(0,8);
    const evidenceRows=evidence.length?evidence.map(item=>`<div class="v10-evidence"><b>${esc(item.event||item.action||item.title||item.type||'Событие')}</b><p>${esc(item.result||item.outcome||item.status||item.description||'—')}</p><small>${esc(item.evidence_id||item.id||item.hash||'без идентификатора')}</small></div>`).join(''):empty('Связанные доказательства пока не получены.');
    content.innerHTML=`<div class="title"><h1>Решение ИИ</h1><p>Каноническое решение и действия виртуального контура показаны раздельно</p></div>
      <section class="metrics">
        ${card('Каноническое решение',canonical,diagnostic?'Диагностический legacy-вывод, не для исполнения':'Финальный результат')}
        ${card('Уверенность',run.confidence!=null?num(run.confidence,2)+'%':'—','Только измеренное значение')}
        ${card('Риск',run.risk_level||'—','Оценка центра рисков')}
        ${card('Последнее virtual-действие',tickStatus,'Фактический статус paper-контура')}
        ${card('Открыто позиций',String(s.open_positions??0),'Виртуальный счёт')}
        ${card('Net PnL',num(s.net_pnl)+' USDT','С учётом комиссий',Number(s.net_pnl)>=0?'positive':'negative')}
      </section>
      <section class="v10-grid">
        ${panel('Канонический контур',`<p class="v10-explanation">${esc(canonicalReason)}</p>${row('Исполнимость',diagnostic?'НЕ ИСПОЛНЯЕТСЯ':'по правилам Trade Gate',diagnostic?'negative':'positive')}${row('Источник','/api/run')}`,'wide')}
        ${panel('Виртуальный контур',`<p class="v10-explanation">${esc(tickReason)}</p>${row('Рыночный учёт',s.market_price_accounting===true?'ПОДТВЕРЖДЁН':'НЕ ПОДТВЕРЖДЁН',s.market_price_accounting===true?'positive':'negative')}${row('Реальные ордера',s.real_orders_blocked===false?'РАЗРЕШЕНЫ':'ЗАБЛОКИРОВАНЫ',s.real_orders_blocked===false?'negative':'positive')}${row('Всего сделок',String(s.trade_count??virtual.trades.length))}${row('Закрыто',String(s.closed_positions??0))}`,'wide')}
        ${panel('Доказательства решения',evidenceRows,'wide')}
      </section>`;
  }

  async function load(){
    if(!active()) return;
    const entries=[['run','/api/run'],['virtual','/api/virtual-account/state'],['evidence','/api/evidence-vault/recent']];
    const results=await Promise.allSettled(entries.map(([,url])=>get(url)));
    state.errors={};
    results.forEach((result,index)=>{const key=entries[index][0];if(result.status==='fulfilled')state[key]=result.value;else state.errors[key]=result.reason?.message||'недоступно';});
    state.loadedAt=new Date().toLocaleString('ru-RU');
    render();
  }

  document.addEventListener('click',(event)=>{const button=event.target.closest('#nav button[data-page="decision"]');if(button)setTimeout(()=>load().catch(()=>{}),0);});
  $('refresh')?.addEventListener('click',()=>{if(active())setTimeout(()=>load().catch(()=>{}),0);});
  window.addEventListener('DOMContentLoaded',()=>{if(active())load().catch(()=>{});});
})();
