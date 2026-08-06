(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const state = { results:{}, errors:{}, loadedAt:null, loading:false };
  const checks = {
    truth: { label:'Канонический runtime', url:'/api/system/runtime-truth', required:true },
    market: { label:'Поток рынка', url:'/api/market/stream/status', required:true },
    news: { label:'News Intelligence', url:'/api/social-news', required:true },
    learning: { label:'Learning Engine', url:'/api/learning-os/status', required:true },
    evidence: { label:'Evidence Vault', url:'/api/evidence-vault/recent', required:true },
    reports: { label:'Отчёты', url:'/api/ai-control-center/daily-report', required:true },
    account: { label:'Личный Bybit read-only', url:'/api/exchange/account/status', required:false },
  };
  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === 'system-status';
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  async function getJson(url){
    const started=performance.now();
    const response=await fetch(url,{credentials:'same-origin',cache:'no-store'});
    const latencyMs=Math.round(performance.now()-started);
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    return {data:await response.json(),latencyMs};
  }

  function transport(key){
    if(state.errors[key]||!state.results[key])return {level:'bad',label:'НЕТ ОТВЕТА'};
    return {level:'ok',label:'HTTP ДОСТУПЕН'};
  }

  function semantic(key){
    const result=state.results[key];
    if(!result)return {level:'bad',label:'НЕИЗВЕСТНО',detail:state.errors[key]||'нет ответа'};
    const data=result.data||{};
    if(key==='truth'){
      const value=String(data.status||'unavailable').toLowerCase();
      if(value==='healthy')return {level:'ok',label:'HEALTHY',detail:'канонические owners подтверждены'};
      if(value==='degraded')return {level:'warn',label:'DEGRADED',detail:'есть неполная или stale evidence'};
      return {level:'bad',label:'BLOCKED',detail:'есть critical blocker или safety mismatch'};
    }
    if(key==='account'){
      if(data.connected===true)return {level:'ok',label:'READ-ONLY',detail:'подключён только для чтения'};
      return {level:'optional',label:'НЕ НАСТРОЕН',detail:'не влияет на canonical paper runtime'};
    }
    const value=String(data.status||data.state||'').toLowerCase();
    if(['error','unavailable','failed','offline','blocked'].includes(value))return {level:'bad',label:value.toUpperCase(),detail:String(data.error||data.message||'')};
    if(['warning','degraded','stale'].includes(value))return {level:'warn',label:value.toUpperCase(),detail:String(data.error||data.message||'')};
    return {level:'ok',label:'AVAILABLE',detail:'семантическая оценка ограничена контрактом источника'};
  }

  function serviceCard(key){
    const meta=checks[key];
    const transportState=transport(key);
    const semanticState=semantic(key);
    const result=state.results[key];
    const cls=semanticState.level==='bad'&&meta.required?'bad':'ok';
    return `<article class="status-service ${cls}"><div class="status-service-head"><span class="status-dot"></span><div><b>${esc(meta.label)}</b><small>${esc(meta.url)}${meta.required?'':' · optional'}</small></div><strong>${esc(semanticState.label)}</strong></div><div class="status-service-body"><span>Транспорт <b>${esc(transportState.label)}</b></span>${result?`<span>Отклик <b>${esc(String(result.latencyMs))} мс</b></span>`:''}${semanticState.detail?`<span class="status-service-note">${esc(semanticState.detail)}</span>`:''}</div></article>`;
  }

  function ageText(){
    if(!state.loadedAt)return 'Проверка ещё не выполнялась';
    const seconds=Math.max(0,Math.floor((Date.now()-new Date(state.loadedAt).getTime())/1000));
    return seconds<60?`Проверено ${seconds} сек назад`:`Проверено ${Math.floor(seconds/60)} мин назад`;
  }

  function render(){
    if(!active())return;
    const content=$('content'); if(!content)return;
    const keys=Object.keys(checks);
    const required=keys.filter((key)=>checks[key].required);
    const available=required.filter((key)=>transport(key).level==='ok').length;
    const truth=state.results.truth?.data||{};
    const counts=truth.organs?.counts||{};
    const paper=truth.paper?.summary||{};
    const safety=truth.safety||{};
    const runtime=String(truth.status||'unavailable').toUpperCase();
    const runtimeTone=runtime==='HEALTHY'?'positive':'negative';
    content.innerHTML=`<div class="title"><h1>Состояние системы</h1><p>Доступность транспорта отделена от реального состояния runtime</p></div><section class="metrics"><article class="card"><span>Canonical runtime</span><strong class="${runtimeTone}">${esc(runtime)}</strong><small>не вычисляется из количества HTTP 200</small></article><article class="card"><span>Источники доступны</span><strong>${available}/${required.length}</strong><small>только транспорт, не здоровье</small></article><article class="card"><span>Органы</span><strong>${esc(String(truth.organs?.organ_count??0))}</strong><small>${esc(`healthy ${counts.healthy??0} · degraded ${counts.degraded??0} · blocked ${counts.blocked??0}`)}</small></article><article class="card"><span>Paper owner</span><strong>${paper.worker_running?'RUNNING':'STOPPED'}</strong><small>CouncilAuthorizedPaperLoop</small></article><article class="card"><span>Execution safety</span><strong class="${safety.real_orders_blocked?'positive':'negative'}">${safety.real_orders_blocked?'LOCKED':'UNSAFE'}</strong><small>kill switch + Testnet/Mainnet locks</small></article><article class="card"><span>Последняя проверка</span><strong id="statusClock">${esc(new Date().toLocaleTimeString('ru-RU'))}</strong><small id="statusAge">${esc(ageText())}</small></article></section><div class="status-actions"><button id="statusRefresh" class="action">Проверить сейчас</button><span id="statusCheckedAt">${state.loadedAt?esc(new Date(state.loadedAt).toLocaleString('ru-RU')):'—'}</span></div><section class="status-grid">${keys.map(serviceCard).join('')}</section>`;
    $('statusRefresh')?.addEventListener('click',()=>load(true));
  }

  async function load(manual=false){
    if(state.loading||!active())return;
    state.loading=true;
    const button=$('statusRefresh');
    if(button&&manual){button.disabled=true;button.textContent='Проверяю…';}
    const entries=Object.entries(checks);
    const settled=await Promise.allSettled(entries.map(([,meta])=>getJson(meta.url)));
    state.results={}; state.errors={};
    settled.forEach((result,index)=>{const key=entries[index][0];if(result.status==='fulfilled')state.results[key]=result.value;else state.errors[key]=result.reason?.message||'нет ответа';});
    state.loadedAt=new Date().toISOString(); state.loading=false; render();
  }

  function install(){
    const nav=$('nav'); if(!nav)return;
    let button=nav.querySelector('[data-page="system-status"]');
    if(!button){button=document.createElement('button');button.type='button';button.dataset.page='system-status';button.textContent='Состояние системы';nav.insertBefore(button,nav.firstChild);}
    if(button.dataset.status44Bound==='1')return;
    button.dataset.status44Bound='1';
    button.addEventListener('click',()=>{setTimeout(()=>{render();load().catch(()=>{});},0);});
    if(location.hash==='#system-status')button.click();
  }

  window.addEventListener('DOMContentLoaded',install);
  setInterval(()=>{const clock=$('statusClock');const age=$('statusAge');if(clock)clock.textContent=new Date().toLocaleTimeString('ru-RU');if(age)age.textContent=ageText();},1000);
  setInterval(()=>{if(active()&&!document.hidden)load().catch(()=>{});},15000);
})();
