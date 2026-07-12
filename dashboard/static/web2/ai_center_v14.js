(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const arr = (v) => Array.isArray(v) ? v : [];
  const firstArray = (...values) => values.find(Array.isArray) || [];
  const fmt = (v) => v ? new Date(v).toLocaleString('ru-RU') : '—';
  const age = (bot) => {
    if (Number.isFinite(Number(bot?.heartbeat_age_seconds))) return Number(bot.heartbeat_age_seconds);
    const t = bot?.last_seen || bot?.updated_at || bot?.timestamp;
    if (!t) return null;
    const n = (Date.now() - new Date(t).getTime()) / 1000;
    return Number.isFinite(n) ? Math.max(0, n) : null;
  };
  const verified = (bot) => {
    const a = age(bot);
    return a !== null && a < 90;
  };
  const safeJson = async (url) => {
    const r = await fetch(url, {credentials:'same-origin', cache:'no-store'});
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  };
  const state = {bots:[], evidence:[], run:null, selected:null, filter:'all', query:'', loadedAt:null, errors:{}};

  function botName(bot){ return bot?.name || bot?.agent_name || bot?.id || 'ИИ без названия'; }
  function botRole(bot){ return bot?.role || bot?.kind || bot?.responsibility || 'Роль не указана'; }
  function botStatus(bot){
    if (bot?.status === 'error' || bot?.error || bot?.last_error) return {text:'Ошибка', cls:'bad'};
    if (verified(bot)) return {text:'Подтверждён', cls:'good'};
    return {text:'Не подтверждён', cls:'warn'};
  }
  function evidenceFor(bot){
    const name = botName(bot).toLowerCase();
    return state.evidence.filter(e => String(e.agent || e.module || e.source || '').toLowerCase().includes(name)).slice(0,20);
  }
  function tasksFor(bot){
    return firstArray(bot?.tasks, bot?.current_tasks, bot?.queue, bot?.jobs);
  }
  function linksFor(bot){
    return firstArray(bot?.connections, bot?.depends_on, bot?.inputs, bot?.linked_agents);
  }
  function filterBots(){
    return state.bots.filter(bot => {
      const s = botStatus(bot);
      if (state.filter === 'verified' && s.cls !== 'good') return false;
      if (state.filter === 'errors' && s.cls !== 'bad') return false;
      const q = state.query.trim().toLowerCase();
      if (!q) return true;
      return `${botName(bot)} ${botRole(bot)} ${bot?.reports_to || ''}`.toLowerCase().includes(q);
    });
  }
  function badge(text, cls=''){ return `<span class="ai14-badge ${cls}">${esc(text)}</span>`; }
  function stat(label, value){ return `<div class="ai14-stat"><span>${esc(label)}</span><b>${esc(value)}</b></div>`; }

  function mapHtml(){
    if (!state.bots.length) return '<div class="ai14-empty">Карта недоступна: реестр ИИ не получен.</div>';
    const roots = state.bots.filter(b => !b.reports_to || String(b.reports_to).toLowerCase().includes('general') || String(b.reports_to).toLowerCase().includes('глав'));
    const rootNames = new Set(roots.map(botName));
    const root = roots[0] || {name:'Главный управляющий ИИ'};
    const children = state.bots.filter(b => botName(b) !== botName(root));
    return `<div class="ai14-map"><div class="ai14-root">${esc(botName(root))}<small>${esc(botRole(root))}</small></div><div class="ai14-line"></div><div class="ai14-nodes">${children.map(b => { const s=botStatus(b); return `<button class="ai14-node ${s.cls}" data-ai14-open="${esc(botName(b))}"><b>${esc(botName(b))}</b><span>${esc(botRole(b))}</span><small>${esc(b.reports_to || (rootNames.size ? botName(root) : 'Главный управляющий ИИ'))}</small></button>`; }).join('')}</div></div>`;
  }

  function cardHtml(bot){
    const s=botStatus(bot), a=age(bot), tasks=tasksFor(bot), ev=evidenceFor(bot);
    return `<article class="ai14-card"><header><div><small>${esc(botRole(bot))}</small><h3>${esc(botName(bot))}</h3></div>${badge(s.text,s.cls)}</header><div class="ai14-card-grid">${stat('Последний сигнал',a===null?'нет времени':a<60?`${Math.round(a)} сек. назад`:`${Math.round(a/60)} мин. назад`)}${stat('Текущие задачи',String(tasks.length))}${stat('Доказательства',String(ev.length || (bot.evidence_id?1:0)))}${stat('Подчиняется',bot.reports_to || 'не указано')}</div><p>${esc(bot.last_action && (bot.evidence_id || ev.length) ? bot.last_action : 'Подтверждённое последнее действие не получено.')}</p><button class="action" data-ai14-open="${esc(botName(bot))}">Открыть ИИ</button></article>`;
  }

  function journalHtml(){
    const rows = state.evidence.slice(0,80);
    if (!rows.length) return '<div class="ai14-empty">Журнал действий не получен. Выдуманные события не создаются.</div>';
    return rows.map(e => `<div class="ai14-event"><time>${fmt(e.time || e.created_at || e.timestamp)}</time><div><b>${esc(e.agent || e.module || e.source || 'Источник не указан')}</b><p>${esc(e.event || e.action || e.title || 'Событие без названия')}</p><small>${esc(e.evidence_id || e.id || e.hash || 'идентификатор не передан')}</small></div></div>`).join('');
  }

  function detailHtml(bot){
    if (!bot) return '';
    const s=botStatus(bot), tasks=tasksFor(bot), links=linksFor(bot), ev=evidenceFor(bot), a=age(bot);
    return `<div class="ai14-modal" id="ai14Modal"><div class="ai14-dialog"><button class="ai14-close" id="ai14Close">×</button><header><div><small>${esc(botRole(bot))}</small><h2>${esc(botName(bot))}</h2></div>${badge(s.text,s.cls)}</header><section class="ai14-detail-grid">${stat('Свежесть сигнала',a===null?'нет отметки':`${Math.round(a)} сек.`)}${stat('Статус API',bot.status || 'не передан')}${stat('Качество',bot.metrics_verified && bot.quality_score!=null?`${bot.quality_score}%`:'нет измерений')}${stat('Ошибка',bot.error || bot.last_error || 'не передана')}${stat('Подчиняется',bot.reports_to || 'не указано')}${stat('Доказательство',bot.evidence_id || bot.last_evidence_id || 'не передано')}</section><section><h3>Текущие задачи</h3>${tasks.length?`<ul>${tasks.map(t=>`<li>${esc(t.title || t.name || t.task || t)}</li>`).join('')}</ul>`:'<div class="ai14-empty">API не передал текущие задачи.</div>'}</section><section><h3>Связи и входящие данные</h3>${links.length?`<div class="ai14-links">${links.map(x=>badge(x.name || x.source || x)).join('')}</div>`:'<div class="ai14-empty">Связи не переданы API.</div>'}</section><section><h3>Подтверждённые действия</h3>${ev.length?ev.map(e=>`<div class="ai14-event"><time>${fmt(e.time || e.created_at || e.timestamp)}</time><div><p>${esc(e.event || e.action || e.title)}</p><small>${esc(e.evidence_id || e.id || '—')}</small></div></div>`).join(''):'<div class="ai14-empty">Связанные доказательства не найдены.</div>'}</section></div></div>`;
  }

  function render(){
    const content=$('content'); if(!content) return;
    const list=filterBots(), ok=state.bots.filter(verified).length, errors=state.bots.filter(b=>botStatus(b).cls==='bad').length;
    content.innerHTML=`<div class="title"><h1>Центр ИИ</h1><p>Карта, задачи, связи, журнал и доказательства работы каждого ИИ</p></div><section class="metrics">${['Всего ИИ|'+state.bots.length,'Подтверждены|'+ok,'Без подтверждения|'+Math.max(0,state.bots.length-ok-errors),'С ошибкой|'+errors].map(x=>{const [a,b]=x.split('|');return `<article class="card"><span>${a}</span><strong>${b}</strong><small>Только фактические данные</small></article>`}).join('')}</section><div class="ai14-toolbar"><input id="ai14Search" placeholder="Поиск ИИ" value="${esc(state.query)}"><button data-ai14-filter="all" class="${state.filter==='all'?'active':''}">Все</button><button data-ai14-filter="verified" class="${state.filter==='verified'?'active':''}">Подтверждённые</button><button data-ai14-filter="errors" class="${state.filter==='errors'?'active':''}">Ошибки</button><button id="ai14Refresh" class="action">Обновить</button></div><section class="ai14-layout"><div><article class="panel"><small>SHARIPOVAI</small><h2>Карта ИИ</h2>${mapHtml()}</article><div class="ai14-grid">${list.length?list.map(cardHtml).join(''):'<div class="ai14-empty">ИИ по выбранному фильтру не найдены.</div>'}</div></div><aside class="panel ai14-journal"><small>SHARIPOVAI</small><h2>Журнал работы</h2>${journalHtml()}</aside></section>${state.selected?detailHtml(state.selected):''}`;
    bind();
  }

  function bind(){
    $('ai14Search')?.addEventListener('input',e=>{state.query=e.target.value;render();});
    document.querySelectorAll('[data-ai14-filter]').forEach(b=>b.addEventListener('click',()=>{state.filter=b.dataset.ai14Filter;render();}));
    document.querySelectorAll('[data-ai14-open]').forEach(b=>b.addEventListener('click',()=>{state.selected=state.bots.find(x=>botName(x)===b.dataset.ai14Open)||null;render();}));
    $('ai14Close')?.addEventListener('click',()=>{state.selected=null;render();});
    $('ai14Refresh')?.addEventListener('click',load);
  }

  async function load(){
    const results=await Promise.allSettled([safeJson('/api/ai-bots'),safeJson('/api/evidence-vault/recent'),safeJson('/api/run')]);
    state.errors={};
    if(results[0].status==='fulfilled') state.bots=firstArray(results[0].value?.bots,results[0].value?.items,results[0].value?.agents,results[0].value); else state.errors.bots=results[0].reason?.message;
    if(results[1].status==='fulfilled') state.evidence=firstArray(results[1].value?.items,results[1].value?.records,results[1].value?.events,results[1].value); else state.errors.evidence=results[1].reason?.message;
    if(results[2].status==='fulfilled') state.run=results[2].value; else state.errors.run=results[2].reason?.message;
    state.loadedAt=new Date().toISOString(); render();
  }

  function install(){
    const nav=$('nav'); if(!nav) return;
    nav.addEventListener('click',e=>{const b=e.target.closest('button[data-page="bots"]');if(!b)return;setTimeout(load,0);});
    if(nav.querySelector('button.active')?.dataset.page==='bots') load();
  }
  window.addEventListener('DOMContentLoaded',install);
})();