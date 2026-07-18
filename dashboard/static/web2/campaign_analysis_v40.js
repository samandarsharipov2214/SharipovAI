(() => {
  'use strict';
  const active = () => (window.SharipovAIPageCoordinator?.activePage?.() || document.querySelector('#nav button.active[data-page]')?.dataset.page) === 'campaigns';
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = (v,d=6) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('ru-RU',{maximumFractionDigits:d}) : '—';
  let busy = false;

  async function api(url, options={}) {
    const response = await fetch(url,{cache:'no-store',credentials:'same-origin',headers:{'Content-Type':'application/json'},...options});
    const data = await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(data?.detail?.message || data?.detail || `HTTP ${response.status}`);
    return data;
  }

  function panel() {
    const shell = document.querySelector('#content .campaign36-shell');
    if(!shell) return null;
    let root = document.getElementById('phase8AnalysisPanel');
    if(!root){ root=document.createElement('section'); root.id='phase8AnalysisPanel'; root.className='p8-shell'; shell.append(root); }
    return root;
  }

  function render(data, campaignId, error='') {
    const root=panel(); if(!root) return;
    const pnl=data?.pnl||{}, div=data?.divergence||{}, rec=data?.recommendation||{};
    root.innerHTML=`<article class="p8-hero"><div><small>PHASE 8 · POST-CAMPAIGN</small><h2>Campaign Analysis</h2><p>${esc(campaignId||'No completed campaign selected')}</p></div><button id="phase8Analyze" ${!campaignId||busy?'disabled':''}>Analyze now</button></article>${error?`<div class="p8-error">${esc(error)}</div>`:''}<section class="p8-metrics"><article><span>Net realized PnL</span><b>${num(pnl.net_realized_pnl_usdt,8)} USDT</b></article><article><span>Gross PnL</span><b>${num(pnl.gross_realized_pnl_usdt,8)} USDT</b></article><article><span>Fees</span><b>${num(data?.fees_usdt,8)} USDT</b></article><article><span>Price divergence</span><b>${num(div.price_divergence_bps,3)} bps</b></article><article><span>Fill count</span><b>${Number(data?.fill_count||0)}</b></article><article><span>Recommendation</span><b>${esc(rec.action||'pending')}</b></article></section><article class="p8-card"><h3>Recommendation</h3><p>${esc(rec.reason||'Analysis has not been generated.')}</p><div class="p8-gates">${Object.entries(data?.gates||{}).map(([k,v])=>`<span class="${v?'ok':'bad'}">${v?'✓':'×'} ${esc(k)}</span>`).join('')}</div><small>Automatic promotion: disabled · Mainnet: disabled</small></article>`;
    document.getElementById('phase8Analyze')?.addEventListener('click',()=>analyze(campaignId));
  }

  async function load() {
    if(!active()) return;
    try {
      const monitor=await api('/api/campaigns/phase7/monitor');
      const id=String(monitor.campaign_id||'');
      if(!id){render({},'');return;}
      try { render(await api(`/api/campaigns/phase8/analysis/${encodeURIComponent(id)}`),id); }
      catch(e){ render({},id,e.message); }
    } catch(e){ render({},'',e.message); }
  }

  async function analyze(id){ if(busy||!id)return; busy=true; render({},id); try{render(await api(`/api/campaigns/phase8/analyze/${encodeURIComponent(id)}`,{method:'POST'}),id);}catch(e){render({},id,e.message);}finally{busy=false;} }

  setInterval(()=>{if(active()&&!busy&&document.visibilityState==='visible')load();},5000);
  document.addEventListener('visibilitychange',()=>{if(active()&&document.visibilityState==='visible')load();});
  document.addEventListener('click',e=>{if(e.target?.closest?.('#nav button[data-page="campaigns"]'))setTimeout(load,150);});
  const observer=new MutationObserver(()=>{if(active()&&!document.getElementById('phase8AnalysisPanel'))load();});
  window.addEventListener('DOMContentLoaded',()=>{const content=document.getElementById('content');if(content)observer.observe(content,{childList:true,subtree:true});if(active())load();},{once:true});
})();
