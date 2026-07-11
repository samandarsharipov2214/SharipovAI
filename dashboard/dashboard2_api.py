"""Dashboard 2.0 control center for the SharipovAI local node."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


PAGE = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SharipovAI Control Center</title>
<style>
:root{color-scheme:dark;--bg:#07111f;--card:#101d30;--line:#233552;--ok:#37d67a;--bad:#ff667a;--muted:#9bb0cb}*{box-sizing:border-box}
body{margin:0;background:linear-gradient(135deg,#07111f,#10172b);font:15px system-ui;color:#edf5ff}.wrap{max-width:1280px;margin:auto;padding:24px}
h1{margin:0 0 4px;font-size:28px}.sub{color:var(--muted);margin-bottom:20px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
.card{background:rgba(16,29,48,.94);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:0 10px 30px #0004}.label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.value{font-size:22px;font-weight:700;margin-top:8px}.ok{color:var(--ok)}.bad{color:var(--bad)}
section{margin-top:22px}table{width:100%;border-collapse:collapse;background:rgba(16,29,48,.94);border-radius:16px;overflow:hidden}th,td{text-align:left;padding:12px;border-bottom:1px solid var(--line)}th{color:var(--muted)}button{background:#2878ff;color:white;border:0;border-radius:10px;padding:9px 13px;cursor:pointer;margin-right:8px}.status{margin-top:12px;color:var(--muted)}
</style></head><body><div class="wrap"><h1>SharipovAI Control Center</h1><div class="sub">Agent · Supervisor · AI Registry · Backup · Resources</div>
<div id="cards" class="grid"></div><section><h2>ИИ и модули</h2><table><thead><tr><th>Модуль</th><th>Роль</th><th>Статус</th><th>Рекомендация</th></tr></thead><tbody id="agents"></tbody></table></section>
<section><h2>Безопасные действия</h2><button onclick="cmd('health_check')">Проверить систему</button><button onclick="cmd('restart_node')">Перезапустить web node</button><button onclick="cmd('restart_backup')">Перезапустить backup</button><div id="action" class="status"></div></section></div>
<script>
const esc=s=>String(s??'—').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function load(){try{const r=await fetch('/api/control-plane/status');const d=await r.json();const n=d.node||{},a=d.agent||{},b=d.backup||{},res=d.resources||{};
const cards=[['Web node',n.healthy?'ONLINE':'OFFLINE',n.healthy],['PC Agent',a.status||a.state||'UNKNOWN',String(a.status||a.state).toLowerCase()==='running'],['Backup',b.healthy?'FRESH':'STALE',b.healthy],['CPU',`${res.cpu_percent??'—'}%`,true],['Memory',`${res.memory_percent??'—'}%`,true],['Real trading','DISABLED',true]];
document.getElementById('cards').innerHTML=cards.map(x=>`<div class="card"><div class="label">${esc(x[0])}</div><div class="value ${x[2]?'ok':'bad'}">${esc(x[1])}</div></div>`).join('');
const list=d.ai_registry?.agents||d.ai_registry?.items||[];document.getElementById('agents').innerHTML=list.map(x=>`<tr><td>${esc(x.name||x.id)}</td><td>${esc(x.role||x.responsibility)}</td><td>${esc(x.status||'active')}</td><td>${esc(x.recommendation||'keep')}</td></tr>`).join('')||'<tr><td colspan="4">Реестр пуст</td></tr>';
}catch(e){document.getElementById('cards').innerHTML='<div class="card"><div class="value bad">Control Plane недоступен</div></div>'}}
async function cmd(command){const el=document.getElementById('action');el.textContent='Команда поставлена в очередь…';try{const r=await fetch('/api/control-plane/commands',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({command})});const d=await r.json();el.textContent=d.status==='ok'||d.status==='queued'?'Готово: команда принята':'Ошибка: '+JSON.stringify(d)}catch(e){el.textContent='Ошибка связи'}}
load();setInterval(load,5000);
</script></body></html>'''


def install_dashboard2_api(app: FastAPI) -> None:
    if getattr(app.state, "dashboard2_installed", False):
        return
    app.state.dashboard2_installed = True

    @app.get("/control", response_class=HTMLResponse)
    def control_center() -> HTMLResponse:
        return HTMLResponse(PAGE)
