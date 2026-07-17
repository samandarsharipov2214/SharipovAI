"""Admin execution-status router with real runtime and paper metrics."""
from __future__ import annotations

import json
from html import escape
from typing import Any, Mapping

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from capital_allocation import CapitalAllocationPolicy
from market_paper_engine import MarketPaperActivityEngine as PaperActivityEngine
from observability.metrics import update_runtime_metrics

from dashboard.auth import AdminPrincipal, admin_principal

router = APIRouter(tags=["execution-status"])


@router.get("/api/execution/status")
def execution_status(
    request: Request,
    _principal: AdminPrincipal = Depends(admin_principal),
) -> dict[str, Any]:
    return build_execution_status(request)


@router.get("/execution-status", response_class=HTMLResponse)
def execution_status_page(
    request: Request,
    principal: AdminPrincipal = Depends(admin_principal),
) -> HTMLResponse:
    snapshot = build_execution_status(request)
    return HTMLResponse(_render_page(snapshot, principal.username))


def build_execution_status(request: Request) -> dict[str, Any]:
    state = request.app.state
    execution_client = getattr(state, "execution_client", None)
    stage_controller = getattr(state, "stage_controller", None)
    execution_journal = getattr(state, "execution_journal", None)

    execution = (
        execution_client.status()
        if execution_client is not None
        else {
            "mode": "unknown",
            "testnet_execution_enabled": False,
            "live_execution_enabled": False,
            "kill_switch": True,
            "status": "unavailable",
        }
    )
    assessment = (
        stage_controller.assess().to_dict()
        if stage_controller is not None
        else {"status": "unavailable"}
    )
    journal = (
        execution_journal.summary()
        if execution_journal is not None
        else {"status": "unavailable", "record_count": 0}
    )
    try:
        paper_state = PaperActivityEngine().state(catch_up=False)
    except Exception as exc:
        paper_state = {
            "summary": {},
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}",
        }
    paper = _mapping(paper_state.get("summary"))
    policy = CapitalAllocationPolicy.from_environment()
    equity = _number(paper.get("equity"))
    deployed = _number(paper.get("deployed_notional"))
    reserve = _number(
        paper.get(
            "reserve_amount",
            equity * policy.reserve_percent / 100.0,
        )
    )
    exposure_percent = deployed / equity * 100.0 if equity > 0 else 0.0
    available = max(0.0, equity - reserve - deployed)
    risk = {
        "equity": round(equity, 8),
        "cash": round(_number(paper.get("cash")), 8),
        "net_pnl": round(_number(paper.get("net_pnl")), 8),
        "deployed_notional": round(deployed, 8),
        "exposure_percent": round(exposure_percent, 8),
        "reserve_amount": round(reserve, 8),
        "reserve_percent": policy.reserve_percent,
        "available_to_allocate": round(
            _number(paper.get("available_to_allocate"), default=available),
            8,
        ),
        "open_positions": int(_number(paper.get("open_positions"))),
        "max_total_exposure_percent": policy.max_total_exposure_percent,
        "max_symbol_exposure_percent": policy.max_symbol_exposure_percent,
        "max_correlated_exposure_percent": policy.max_correlated_exposure_percent,
        "max_risk_per_trade_percent": policy.max_risk_per_trade_percent,
        "max_daily_loss_percent": policy.max_daily_loss_percent,
    }
    blocked = not bool(
        execution.get("testnet_execution_enabled")
        or execution.get("live_execution_enabled")
    )
    result = {
        "status": "ok",
        "execution_blocked": blocked,
        "execution": execution,
        "stage": assessment,
        "journal": journal,
        "risk": risk,
        "paper": {**paper, "state_status": paper_state.get("status", "ok")},
        "canonical_write_path": "ApprovedExecutionRequest",
        "raw_order_api": "removed",
        "mainnet_available": False,
    }
    update_runtime_metrics(
        execution=execution,
        journal=journal,
        paper={
            **paper,
            "exposure_percent": exposure_percent,
            "reserve_amount": reserve,
        },
    )
    return result


def _render_page(snapshot: Mapping[str, Any], username: str) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SharipovAI · Execution Status</title>
<style>
:root{{color-scheme:dark;--bg:#050912;--panel:#0d1726;--line:#22344c;--text:#edf6ff;--muted:#8fa4b8;--ok:#36d98b;--bad:#ff6f83;--blue:#4aa3ff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif}}
main{{max-width:1440px;margin:auto;padding:24px}}header{{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:18px}}
a{{color:var(--blue);font-weight:800}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:16px;margin-bottom:14px}}
.metric small{{display:block;color:var(--muted);margin-bottom:7px}}.metric b{{font-size:24px}}pre{{white-space:pre-wrap;overflow:auto;color:#cde5ff}}.ok{{color:var(--ok)}}.bad{{color:var(--bad)}}button{{border:1px solid #4aa3ff66;background:#102b48;color:white;border-radius:11px;padding:10px 14px;font-weight:800;cursor:pointer}}
</style></head><body><main>
<header><div><h1>Execution Status</h1><p>Admin: {escape(username)} · read-only operational view</p></div><div><a href="/">Dashboard</a> · <a href="/metrics">Metrics</a></div></header>
<section class="card"><div class="grid">
<div class="metric"><small>Execution</small><b id="execution-state"></b></div>
<div class="metric"><small>Mode</small><b id="execution-mode"></b></div>
<div class="metric"><small>Kill switch</small><b id="kill-switch"></b></div>
<div class="metric"><small>Paper equity</small><b id="paper-equity"></b></div>
<div class="metric"><small>Paper net PnL</small><b id="paper-pnl"></b></div>
<div class="metric"><small>Exposure</small><b id="exposure"></b></div>
<div class="metric"><small>Protected reserve</small><b id="reserve"></b></div>
<div class="metric"><small>Open positions</small><b id="positions"></b></div>
</div></section>
<section class="card"><button id="refresh">Refresh</button><p>Canonical write path: <b>ApprovedExecutionRequest</b>. Raw order API removed. Mainnet unavailable.</p></section>
<section class="card"><h2>Runtime snapshot</h2><pre id="payload"></pre></section>
</main><script>
const initial={payload};
function money(value){{return Number(value||0).toLocaleString('en-US',{{maximumFractionDigits:2}})+' USDT'}}
function render(data){{
 const blocked=Boolean(data.execution_blocked);
 const state=document.getElementById('execution-state');
 state.textContent=blocked?'BLOCKED':'ENABLED';state.className=blocked?'bad':'ok';
 document.getElementById('execution-mode').textContent=data.execution?.mode||'unknown';
 document.getElementById('kill-switch').textContent=String(Boolean(data.execution?.kill_switch));
 document.getElementById('paper-equity').textContent=money(data.risk?.equity);
 document.getElementById('paper-pnl').textContent=money(data.risk?.net_pnl);
 document.getElementById('exposure').textContent=Number(data.risk?.exposure_percent||0).toFixed(2)+'%';
 document.getElementById('reserve').textContent=money(data.risk?.reserve_amount);
 document.getElementById('positions').textContent=String(data.risk?.open_positions||0);
 document.getElementById('payload').textContent=JSON.stringify(data,null,2);
}}
async function refresh(){{const response=await fetch('/api/execution/status',{{credentials:'same-origin',cache:'no-store'}});if(!response.ok)throw new Error('status '+response.status);render(await response.json());}}
document.getElementById('refresh').addEventListener('click',()=>refresh().catch(console.error));render(initial);setInterval(()=>refresh().catch(console.error),5000);
</script></body></html>"""


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["build_execution_status", "execution_status", "execution_status_page", "router"]
