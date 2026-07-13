(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const num = (value, digits=4) => Number.isFinite(Number(value)) ? Number(value).toLocaleString('ru-RU',{maximumFractionDigits:digits}) : '—';
  const arr = (...values) => values.find(Array.isArray) || [];
  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === 'learning';
  const get = async (url) => { const response=await fetch(url,{credentials:'same-origin',cache:'no-store'}); if(!response.ok) throw new Error(String(response.status)); return response.json(); };
  const state = { virtual:null, learning:null, evidence:null, loadedAt:null, errors:{} };
  const card = (label,value,note='',tone='') => `<article class="card"><span>${esc(label)}</span><strong class="${esc(tone)}">${esc(value)}</strong><small>${esc(note)}</small></article>`;
  const empty = (text) => `<div class="empty">${esc(text)}</div>`;

  function virtualData(){
    const raw=state.virtual||{};
    const root=raw.state&&typeof raw.state==='object'?raw.state:raw;
    return {summary:root.summary||raw.summary||{},trades:arr(root.trades,raw.trades,root.orders,root.history)};
  }
  function learningItems(){ return arr(state.learning?.insights,state.learning?.recommendations,state.learning?.lessons,state.learning?.items); }

  function render(){
    if(!active()) return;
    const content=$('content'); if(!content) return;
    const virtual=virtualData(), summary=virtual.summary;
    const closed=virtual.trades.filter(x=>String(x.status||'').toUpperCase()==='CLOSED');
    const wins=closed.filter(x=>Number(x.net_pnl)>0);
    const losses=closed.filter(x=>Number(x.net_pnl)<0);
    const lessons=learningItems();
    const rows=closed.length?`<table class="v10-table"><thead><tr><th>Пара</th><th>Сторона</th><th>Вход</th><th>Выход</th><th>Net PnL</th><th>Комиссия</th><th>Причина закрытия</th></tr></thead><tbody>${closed.slice().reverse().slice(0,200).map(x=>`<tr><td>${esc(x.symbol||x.asset||'—')}</td><td>${esc(x.side||'—')}</td><td>${esc(num(x.entry_price))}</td><td>${esc(num(x.exit_price??x.current_price))}</td><td>${esc(num(x.net_pnl))}</td><td>${esc(num(x.fee))}</td><td>${esc(x.close_reason_ru||'—')}</td></tr>`).join('')}</tbody></table>`:empty('Закрытых виртуальных сделок пока нет.');
    const lessonRows=lessons.length?lessons.map(item=>`<article class="v17-lesson"><header><span class="v17-badge neutral">${esc(item.status||item.priority||'наблюдение')}</span></header><h3>${esc(item.title||item.lesson||item.pattern||'Вывод обучения')}</h3><p>${esc(item.description||item.recommendation||item.reason||item.details||'Описание не передано.')}</p></article>`).join(''):empty('Отдельные подтверждённые выводы Learning OS пока не получены. Ниже показан фактический журнал закрытых сделок для анализа.');
    content.innerHTML=`<div class="title"><h1>Центр обучения</h1><p>Фактические результаты виртуальных сделок и подтверждённые выводы без синтетической статистики</p></div>
      <section class="metrics">
        ${card('Закрыто сделок',String(closed.length),'Материал для анализа')}
        ${card('Прибыльных',String(wins.length),'Net PnL выше нуля',wins.length?'positive':'')}
        ${card('Убыточных',String(losses.length),'Net PnL ниже нуля',losses.length?'negative':'')}
        ${card('Win rate',closed.length?num(wins.length/closed.length*100,2)+'%':'—','По закрытым сделкам')}
        ${card('Общий Net PnL',num(summary.net_pnl)+' USDT','С учётом комиссий',Number(summary.net_pnl)>=0?'positive':'negative')}
        ${card('Комиссии',num(summary.total_fees)+' USDT','Фактически учтённые')}
      </section>
      <section class="v17-toolbar"><button id="learningRuntimeRefresh" class="action">Обновить данные</button><span>Загружено: ${esc(state.loadedAt||'—')}</span></section>
      <section class="v17-lesson-grid">${lessonRows}</section>
      <article class="panel wide"><small>SHARIPOVAI</small><h2>Закрытые виртуальные сделки</h2>${rows}</article>
      <article class="panel wide"><small>КОНТРОЛЬ</small><h2>Статус использования результатов</h2><p>Результаты показаны как проверяемый материал. Они не дают автоматического допуска к реальной торговле, не повышают репутацию ИИ без отдельного Evidence и не включают реальные ордера.</p></article>`;
    $('learningRuntimeRefresh')?.addEventListener('click',()=>load().catch(()=>{}));
  }

  async function load(){
    if(!active()) return;
    const entries=[['virtual','/api/virtual-account/trades'],['learning','/api/learning-os/status'],['evidence','/api/evidence-vault/recent']];
    const results=await Promise.allSettled(entries.map(([,url])=>get(url)));
    state.errors={};
    results.forEach((result,index)=>{const key=entries[index][0];if(result.status==='fulfilled')state[key]=result.value;else state.errors[key]=result.reason?.message||'недоступно';});
    state.loadedAt=new Date().toLocaleString('ru-RU');
    render();
  }

  document.addEventListener('click',(event)=>{const button=event.target.closest('#nav button[data-page="learning"]');if(button)setTimeout(()=>load().catch(()=>{}),0);});
  $('refresh')?.addEventListener('click',()=>{if(active())setTimeout(()=>load().catch(()=>{}),0);});
  window.addEventListener('DOMContentLoaded',()=>{if(active())load().catch(()=>{});});
})();
