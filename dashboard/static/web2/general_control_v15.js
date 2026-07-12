(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const list = (v) => Array.isArray(v) ? v : [];
  async function get(url){ const r = await fetch(url,{cache:'no-store',credentials:'same-origin'}); if(!r.ok) throw new Error(String(r.status)); return r.json(); }
  function render(run,bots,evidence){
    const content=$('content'); if(!content) return;
    const votes=list(run?.votes||run?.agent_votes||run?.participants);
    const conflicts=list(run?.conflicts||run?.disagreements);
    const agents=list(bots?.bots||bots?.items||bots?.agents);
    const records=list(evidence?.items||evidence?.records||evidence?.events).slice(0,40);
    content.innerHTML=`<div class="title"><h1>Главное управление</h1><p>Проверяемая цепочка решений SharipovAI</p></div>
    <section class="metrics">
      <article class="card"><span>Решение</span><strong>${esc(run?.decision||'—')}</strong><small>API решения</small></article>
      <article class="card"><span>Уверенность</span><strong>${run?.confidence!=null?esc(run.confidence)+'%':'—'}</strong><small>Измеренное значение</small></article>
      <article class="card"><span>Риск</span><strong>${esc(run?.risk_level||'—')}</strong><small>Оценка риска</small></article>
      <article class="card"><span>Голоса ИИ</span><strong>${votes.length}</strong><small>Переданы API</small></article>
      <article class="card"><span>ИИ в реестре</span><strong>${agents.length}</strong><small>Фактический список</small></article>
    </section>
    <section class="gc15-grid">
      <article class="panel wide"><small>SHARIPOVAI</small><h2>Обоснование</h2><p class="gc15-reason">${esc(run?.reason||run?.report||'Подтверждённое объяснение не получено.')}</p></article>
      <article class="panel"><small>ГОЛОСОВАНИЕ</small><h2>Голоса ИИ</h2>${votes.length?votes.map(v=>`<div class="gc15-vote"><b>${esc(v.name||v.agent||v.module||'ИИ-модуль')}</b><span>${esc(v.decision||v.vote||v.signal||'—')}</span><p>${esc(v.reason||v.explanation||'Причина не передана')}</p></div>`).join(''):'<div class="empty">Отдельные голоса не переданы API.</div>'}</article>
      <article class="panel"><small>КОНФЛИКТЫ</small><h2>Разногласия</h2>${conflicts.length?conflicts.map(x=>`<div class="gc15-conflict"><b>${esc(x.title||x.type||'Конфликт')}</b><p>${esc(x.reason||x.description||x.message||'')}</p></div>`).join(''):'<div class="empty">Подтверждённые конфликты не переданы.</div>'}</article>
      <article class="panel wide"><small>ЖУРНАЛ</small><h2>Цепочка доказательств</h2>${records.length?records.map(x=>`<div class="gc15-record"><b>${esc(x.event||x.action||x.title||x.type||'Событие')}</b><span>${esc(x.source||x.agent||x.module||'источник не указан')}</span><p>${esc(x.result||x.reason||x.description||x.status||'')}</p><code>${esc(x.evidence_id||x.id||x.hash||'')}</code></div>`).join(''):'<div class="empty">Хранилище доказательств не вернуло записи.</div>'}</article>
    </section>`;
  }
  async function load(){ const [run,bots,evidence]=await Promise.allSettled([get('/api/run'),get('/api/ai-bots'),get('/api/evidence-vault/recent')]); render(run.status==='fulfilled'?run.value:null,bots.status==='fulfilled'?bots.value:null,evidence.status==='fulfilled'?evidence.value:null); }
  window.addEventListener('DOMContentLoaded',()=>{ $('nav')?.addEventListener('click',e=>{ if(e.target.closest('button[data-page="control"]')) setTimeout(()=>load().catch(()=>render(null,null,null)),30); }); });
})();