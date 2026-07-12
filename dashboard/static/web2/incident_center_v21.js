(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const get = async url => { const r = await fetch(url,{cache:'no-store',credentials:'same-origin'}); if(!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); };
  const severity = text => /critical|blocked|kill switch|execution/i.test(text) ? 'critical' : /degraded|warning|stale|absent|unavailable|error/i.test(text) ? 'warning' : 'info';

  async function renderIncidentCenter(){
    const out = $('content'); if(!out) return;
    out.innerHTML = '<div class="title"><h1>Центр ошибок</h1><p>Подтверждённые проблемы и безопасные действия</p></div><div class="incident-empty">Загрузка…</div>';
    try {
      const [health, recovery, evidence] = await Promise.all([
        get('/api/system/health'),
        get('/api/system/recovery-plan'),
        get('/api/evidence-vault/recent').catch(() => ({items:[]}))
      ]);
      const incidents = [];
      (health.components || []).forEach(component => {
        (component.blockers || []).forEach(message => incidents.push({component:component.component,message,level:severity(message)}));
      });
      const actions = Array.isArray(recovery.actions) ? recovery.actions : [];
      const records = Array.isArray(evidence.items) ? evidence.items : Array.isArray(evidence.records) ? evidence.records : [];
      const counts = {
        critical: incidents.filter(x=>x.level==='critical').length,
        warning: incidents.filter(x=>x.level==='warning').length,
        info: incidents.filter(x=>x.level==='info').length
      };
      const incidentRows = incidents.length ? incidents.map((x,i)=>`<article class="incident-row ${x.level}"><div><b>${esc(x.component)}</b><p>${esc(x.message)}</p></div><span>${x.level==='critical'?'КРИТИЧНО':x.level==='warning'?'ВНИМАНИЕ':'ИНФО'}</span></article>`).join('') : '<div class="incident-empty">Подтверждённых проблем нет.</div>';
      const actionRows = actions.length ? actions.map(x=>`<li><b>${esc(x.component)}</b><span>${esc(x.action)}</span><small>${x.automatic===false?'Только вручную':'Статус не указан'}</small></li>`).join('') : '<li>План восстановления пуст.</li>';
      out.innerHTML = `<div class="title"><h1>Центр ошибок</h1><p>Единый список проблем без выдуманных тревог</p></div>
        <section class="incident-metrics">
          <article><small>Критические</small><b>${counts.critical}</b></article>
          <article><small>Предупреждения</small><b>${counts.warning}</b></article>
          <article><small>Информация</small><b>${counts.info}</b></article>
          <article><small>Доказательства</small><b>${records.length}</b></article>
          <article><small>Безопасный режим</small><b>${health.safe_mode?'ВКЛЮЧЁН':'НЕ ТРЕБУЕТСЯ'}</b></article>
        </section>
        <div class="incident-actions"><button id="incidentRefresh" class="action">Обновить</button><span>Автоматические исправления отключены</span></div>
        <section class="incident-grid"><article class="incident-panel"><h2>Активные проблемы</h2>${incidentRows}</article><article class="incident-panel"><h2>Рекомендуемые действия</h2><ul class="incident-plan">${actionRows}</ul></article></section>`;
      $('incidentRefresh')?.addEventListener('click', renderIncidentCenter);
    } catch (error) {
      out.innerHTML = `<div class="title"><h1>Центр ошибок</h1><p>Проверка недоступна</p></div><div class="incident-empty">${esc(error.message || 'Нет ответа API')}</div>`;
    }
  }

  function install(){
    const nav = $('nav'); if(!nav || nav.querySelector('[data-page="incidents"]')) return;
    const button = document.createElement('button');
    button.type='button'; button.dataset.page='incidents'; button.textContent='Центр ошибок';
    const settings = nav.querySelector('[data-page="settings"]');
    nav.insertBefore(button, settings || null);
    button.addEventListener('click',()=>{
      nav.querySelectorAll('button[data-page]').forEach(x=>x.classList.remove('active'));
      button.classList.add('active');
      renderIncidentCenter();
      history.replaceState(null,'','#incidents');
    });
    if(location.hash==='#incidents') button.click();
  }
  window.addEventListener('DOMContentLoaded', install);
})();