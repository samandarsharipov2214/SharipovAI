(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const state = { truth:null, evidence:[], selected:null, filter:'all', query:'', errors:{} };
  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === 'bots';
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const get = async (url) => { const response=await fetch(url,{credentials:'same-origin',cache:'no-store'}); if(!response.ok)throw new Error(`${response.status}`); return response.json(); };
  const organs = () => Array.isArray(state.truth?.organs?.organs) ? state.truth.organs.organs : [];
  const organName = (organ) => String(organ.organ_id || 'unknown').replaceAll('_',' ');
  const status = (organ) => {
    const value=String(organ.status||'blocked').toLowerCase();
    if(value==='healthy')return {text:'HEALTHY',cls:'good'};
    if(value==='degraded')return {text:'DEGRADED',cls:'warn'};
    return {text:'BLOCKED',cls:'bad'};
  };
  const evidenceFor = (organ) => {
    const id=String(organ.organ_id||'').toLowerCase();
    return state.evidence.filter((item)=>String(item.agent||item.module||item.source||'').toLowerCase().includes(id)).slice(0,20);
  };
  const badge = (text,cls='') => `<span class="ai14-badge ${cls}">${esc(text)}</span>`;
  const stat = (label,value) => `<div class="ai14-stat"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;

  function filtered(){
    return organs().filter((organ)=>{
      const s=status(organ);
      if(state.filter==='healthy'&&s.cls!=='good')return false;
      if(state.filter==='degraded'&&s.cls!=='warn')return false;
      if(state.filter==='blocked'&&s.cls!=='bad')return false;
      const query=state.query.trim().toLowerCase();
      return !query || `${organName(organ)} ${organ.responsibility||''}`.toLowerCase().includes(query);
    });
  }

  function card(organ){
    const s=status(organ);
    const linked=evidenceFor(organ);
    const blockers=Array.isArray(organ.blockers)?organ.blockers:[];
    const proof=Array.isArray(organ.evidence)?organ.evidence:[];
    return `<article class="ai14-card"><header><div><small>CANONICAL ORGAN</small><h3>${esc(organName(organ))}</h3></div>${badge(s.text,s.cls)}</header><div class="ai14-card-grid">${stat('Проверено',organ.checked_at_ms?new Date(organ.checked_at_ms).toLocaleString('ru-RU'):'—')}${stat('Runtime evidence',String(proof.length))}${stat('Blockers',String(blockers.length))}${stat('Связанные записи',String(linked.length))}</div><p>${esc(organ.responsibility||'Ответственность не указана')}</p><button class="action" data-ai44-open="${esc(organ.organ_id)}">Открыть орган</button></article>`;
  }

  function journal(){
    if(!state.evidence.length)return '<div class="ai14-empty">Подтверждённые события не получены. Выдуманные события не создаются.</div>';
    return state.evidence.slice(0,80).map((item)=>`<div class="ai14-event"><time>${esc(item.time||item.created_at||item.timestamp||'—')}</time><div><b>${esc(item.agent||item.module||item.source||'Источник')}</b><p>${esc(item.event||item.action||item.title||'Событие')}</p><small>${esc(item.evidence_id||item.id||item.hash||'идентификатор не передан')}</small></div></div>`).join('');
  }

  function detail(organ){
    if(!organ)return '';
    const s=status(organ);
    const proof=Array.isArray(organ.evidence)?organ.evidence:[];
    const blockers=Array.isArray(organ.blockers)?organ.blockers:[];
    return `<div class="ai14-modal" id="ai44Modal"><div class="ai14-dialog"><button class="ai14-close" id="ai44Close">×</button><header><div><small>CANONICAL ORGAN</small><h2>${esc(organName(organ))}</h2></div>${badge(s.text,s.cls)}</header><section class="ai14-detail-grid">${stat('Источник','AIOrganRuntimeMonitor')}${stat('Статус',s.text)}${stat('Проверено',organ.checked_at_ms?new Date(organ.checked_at_ms).toLocaleString('ru-RU'):'—')}${stat('ProjectDatabase',state.truth?.organs?.database_backed?'backed':'not confirmed')}</section><section><h3>Ответственность</h3><p>${esc(organ.responsibility||'—')}</p></section><section><h3>Runtime evidence</h3>${proof.length?`<ul>${proof.map((item)=>`<li>${esc(item)}</li>`).join('')}</ul>`:'<div class="ai14-empty">Evidence отсутствует.</div>'}</section><section><h3>Blockers</h3>${blockers.length?`<ul>${blockers.map((item)=>`<li>${esc(item)}</li>`).join('')}</ul>`:'<div class="ai14-empty">Блокирующих причин нет.</div>'}</section></div></div>`;
  }

  function render(){
    if(!active())return;
    const content=$('content'); if(!content)return;
    const rows=filtered();
    const counts=state.truth?.organs?.counts||{};
    const runtime=String(state.truth?.status||'unavailable').toUpperCase();
    content.innerHTML=`<div class="title"><h1>Канонический центр ИИ</h1><p>Ровно 9 органов из AIOrganRuntimeMonitor. HTTP-ответ не считается доказательством здоровья.</p></div><section class="metrics"><article class="card"><span>Runtime truth</span><strong>${esc(runtime)}</strong><small>/api/system/runtime-truth</small></article><article class="card"><span>Органы</span><strong>${esc(String(state.truth?.organs?.organ_count??0))}</strong><small>канонический реестр</small></article><article class="card"><span>Healthy</span><strong class="positive">${esc(String(counts.healthy??0))}</strong><small>без blockers</small></article><article class="card"><span>Degraded</span><strong>${esc(String(counts.degraded??0))}</strong><small>есть неполная evidence</small></article><article class="card"><span>Blocked</span><strong class="negative">${esc(String(counts.blocked??0))}</strong><small>есть critical blockers</small></article></section><div class="ai14-toolbar"><input id="ai44Search" placeholder="Поиск органа" value="${esc(state.query)}"><button data-ai44-filter="all" class="${state.filter==='all'?'active':''}">Все</button><button data-ai44-filter="healthy" class="${state.filter==='healthy'?'active':''}">Healthy</button><button data-ai44-filter="degraded" class="${state.filter==='degraded'?'active':''}">Degraded</button><button data-ai44-filter="blocked" class="${state.filter==='blocked'?'active':''}">Blocked</button><button id="ai44Refresh" class="action">Обновить</button></div><section class="ai14-layout"><div><div class="ai14-grid">${rows.length?rows.map(card).join(''):'<div class="ai14-empty">Органы по фильтру не найдены.</div>'}</div></div><aside class="panel ai14-journal"><small>PROJECT DATABASE</small><h2>Журнал доказательств</h2>${journal()}</aside></section>${detail(state.selected)}`;
    bind();
  }

  function bind(){
    $('ai44Search')?.addEventListener('input',(event)=>{state.query=event.target.value;render();});
    document.querySelectorAll('[data-ai44-filter]').forEach((button)=>button.addEventListener('click',()=>{state.filter=button.dataset.ai44Filter;render();}));
    document.querySelectorAll('[data-ai44-open]').forEach((button)=>button.addEventListener('click',()=>{state.selected=organs().find((item)=>item.organ_id===button.dataset.ai44Open)||null;render();}));
    $('ai44Close')?.addEventListener('click',()=>{state.selected=null;render();});
    $('ai44Refresh')?.addEventListener('click',()=>load().catch(()=>{}));
  }

  async function load(){
    if(!active())return;
    const results=await Promise.allSettled([get('/api/system/runtime-truth'),get('/api/evidence-vault/recent')]);
    state.errors={};
    if(results[0].status==='fulfilled')state.truth=results[0].value;else state.errors.truth=results[0].reason?.message||'недоступно';
    if(results[1].status==='fulfilled'){
      const value=results[1].value;
      state.evidence=Array.isArray(value?.items)?value.items:Array.isArray(value?.records)?value.records:Array.isArray(value?.events)?value.events:[];
    }else state.errors.evidence=results[1].reason?.message||'недоступно';
    render();
  }

  document.addEventListener('click',(event)=>{if(event.target.closest('#nav button[data-page="bots"]'))setTimeout(()=>load().catch(()=>{}),0);});
  window.addEventListener('DOMContentLoaded',()=>{if(active())load().catch(()=>{});});
})();
