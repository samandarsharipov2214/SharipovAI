"""Admin Champion/Challenger comparison and evidence-bound manual promotion UI."""
from __future__ import annotations

import json
from html import escape
from typing import Any, Mapping

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from dashboard.auth import AdminPrincipal, admin_principal
from experiments import ChampionChallengerRegistry, ExperimentRegistry
from storage import ProjectDatabase

router = APIRouter(tags=["strategy-leadership"])


@router.get("/api/strategy-leadership/{scope}")
def leadership_api(
    request: Request,
    scope: str,
    _principal: AdminPrincipal = Depends(admin_principal),
) -> dict[str, Any]:
    registry = _leadership(request)
    snapshot = registry.snapshot(scope)
    return {
        "status": "ok",
        "leadership": snapshot,
        "comparison": registry.comparison(scope),
        "runtime_deployment_changed": False,
    }


@router.post("/api/strategy-leadership/{scope}/challengers")
def register_challenger(
    request: Request,
    scope: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    principal: AdminPrincipal = Depends(admin_principal),
) -> dict[str, Any]:
    try:
        updated = _leadership(request).register_challenger(
            scope,
            str(payload.get("experiment_id", "")),
            actor=principal.username,
            reason=str(payload.get("reason", "")),
            expected_version=(
                int(payload["expected_version"])
                if payload.get("expected_version") not in (None, "")
                else None
            ),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"experiment not found: {exc.args[0]}") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "leadership": updated, "runtime_deployment_changed": False}


@router.post("/api/strategy-leadership/{scope}/promote")
def promote_challenger(
    request: Request,
    scope: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    principal: AdminPrincipal = Depends(admin_principal),
) -> dict[str, Any]:
    try:
        updated = _leadership(request).promote_challenger(
            scope,
            str(payload.get("experiment_id", "")),
            target_stage=str(payload.get("target_stage", "testnet")),
            actor=principal.username,
            reason=str(payload.get("reason", "")),
            expected_version=(
                int(payload["expected_version"])
                if payload.get("expected_version") not in (None, "")
                else None
            ),
            approval_token=str(payload.get("approval_token", "")),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"experiment not found: {exc.args[0]}") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "ok",
        "leadership": updated,
        "runtime_deployment_changed": False,
        "execution_enabled": False,
    }


@router.get("/champion-challenger", response_class=HTMLResponse)
def champion_challenger_page(
    request: Request,
    scope: str = Query(default="spot:testnet"),
    principal: AdminPrincipal = Depends(admin_principal),
) -> HTMLResponse:
    leadership = _leadership(request)
    snapshot = leadership.snapshot(scope)
    comparison = leadership.comparison(scope)
    experiments = _experiments(request).list(limit=100, newest_first=True)
    return HTMLResponse(
        _render_page(
            scope=scope,
            username=principal.username,
            snapshot=snapshot,
            comparison=comparison,
            experiments=experiments,
        )
    )


def _leadership(request: Request) -> ChampionChallengerRegistry:
    return ChampionChallengerRegistry(_database(request))


def _experiments(request: Request) -> ExperimentRegistry:
    return ExperimentRegistry(_database(request))


def _database(request: Request) -> ProjectDatabase:
    database = getattr(request.app.state, "project_database", None)
    return database if isinstance(database, ProjectDatabase) else ProjectDatabase()


def _render_page(
    *,
    scope: str,
    username: str,
    snapshot: Mapping[str, Any],
    comparison: Mapping[str, Any],
    experiments: list[dict[str, Any]],
) -> str:
    champion = str(snapshot.get("champion_experiment_id") or "")
    challengers = snapshot.get("challengers") if isinstance(snapshot.get("challengers"), Mapping) else {}
    challenger_rows = "".join(
        _challenger_row(identifier, item)
        for identifier, item in challengers.items()
        if isinstance(item, Mapping)
    ) or "<tr><td colspan='6'>No challengers registered.</td></tr>"
    comparison_rows = comparison.get("rows") if isinstance(comparison.get("rows"), list) else []
    ranking = comparison.get("ranking") if isinstance(comparison.get("ranking"), list) else []
    metric_rows = "".join(_metric_row(item, ranking) for item in comparison_rows) or (
        "<tr><td colspan='8'>Register at least two evidence-backed candidates for comparison.</td></tr>"
    )
    options = "".join(
        f"<option value='{escape(str(item.get('experiment_id', '')))}'>"
        f"{escape(str(item.get('experiment_id', '')))} · "
        f"{escape(str(item.get('strategy_name', '')))} · "
        f"{escape(str(item.get('status', '')))}</option>"
        for item in experiments
    )
    raw = json.dumps(
        {"leadership": snapshot, "comparison": comparison},
        ensure_ascii=False,
        allow_nan=False,
    ).replace("</", "<\\/")
    safe_scope = escape(scope)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SharipovAI · Champion / Challenger</title><style>{_css()}</style></head>
<body><main><header><div><h1>Champion / Challenger</h1>
<p>Admin: {escape(username)} · scope: <code>{safe_scope}</code></p></div>
<nav><a href="/">Dashboard</a> · <a href="/backtest-results">Experiments</a> · <a href="/experiment-comparison">Compare</a></nav></header>
<section class="grid"><article class="card hero"><span>Current champion</span><strong>{escape(champion or 'NONE')}</strong>
<p>Leadership is research metadata only. This page cannot deploy code, enable Testnet/Mainnet or change capital.</p></article>
<article class="card"><span>Registry version</span><strong>{int(snapshot.get('version', 0))}</strong><p>Every write uses optimistic versioning.</p></article></section>
<section class="card"><h2>Candidate metrics</h2><table><thead><tr><th>Rank</th><th>Experiment</th><th>Strategy</th><th>OOS PnL</th><th>Return</th><th>Drawdown</th><th>Profitable windows</th><th>Promotion</th></tr></thead><tbody>{metric_rows}</tbody></table></section>
<section class="card"><h2>Leadership registry</h2><table><thead><tr><th>Experiment</th><th>Status</th><th>Strategy</th><th>Commit</th><th>Registered</th><th>Reason</th></tr></thead><tbody>{challenger_rows}</tbody></table></section>
<section class="grid"><form class="card" id="register"><h2>Register challenger</h2><label>Experiment<select name="experiment_id" required>{options}</select></label><label>Reason<textarea name="reason" required minlength="3"></textarea></label><button>Register challenger</button></form>
<form class="card danger" id="promote"><h2>Manual champion promotion</h2><label>Experiment<select name="experiment_id" required>{options}</select></label><label>Target stage<select name="target_stage"><option value="testnet">testnet</option><option value="paper">paper</option></select></label><label>Reason<textarea name="reason" required minlength="3"></textarea></label><label>Approval token<input name="approval_token" required placeholder="PROMOTE:{safe_scope}:experiment:testnet"></label><button>Promote evidence-backed challenger</button></form></section>
<section class="card"><h2>Result</h2><pre id="result">No action submitted.</pre></section>
<section class="card"><h2>Raw evidence</h2><pre id="raw"></pre></section></main>
<script>
const scope={json.dumps(scope)};const version={int(snapshot.get('version',0))};
document.getElementById('raw').textContent=JSON.stringify({raw},null,2);
async function submit(form,path){{const data=Object.fromEntries(new FormData(form).entries());data.expected_version=version;const response=await fetch(path,{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify(data)}});const body=await response.json();document.getElementById('result').textContent=JSON.stringify(body,null,2);if(response.ok)setTimeout(()=>location.reload(),500);}}
document.getElementById('register').addEventListener('submit',e=>{{e.preventDefault();submit(e.currentTarget,`/api/strategy-leadership/${{encodeURIComponent(scope)}}/challengers`);}});
document.getElementById('promote').addEventListener('submit',e=>{{e.preventDefault();submit(e.currentTarget,`/api/strategy-leadership/${{encodeURIComponent(scope)}}/promote`);}});
</script></body></html>"""


def _challenger_row(identifier: Any, item: Mapping[str, Any]) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(str(identifier))}</code></td>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td>{escape(str(item.get('strategy_name', '')))}</td>"
        f"<td>{escape(str(item.get('commit_sha', ''))[:12])}</td>"
        f"<td>{escape(str(item.get('registered_at_ms') or item.get('promoted_at_ms') or ''))}</td>"
        f"<td>{escape(str(item.get('reason', '')))}</td>"
        "</tr>"
    )


def _metric_row(item: Mapping[str, Any], ranking: list[Any]) -> str:
    identifier = str(item.get("experiment_id", ""))
    rank = ranking.index(identifier) + 1 if identifier in ranking else "—"
    return (
        "<tr>"
        f"<td>{rank}</td>"
        f"<td><code>{escape(identifier)}</code></td>"
        f"<td>{escape(str(item.get('strategy_name', '')))}</td>"
        f"<td>{_number(item.get('oos_net_pnl')):,.2f}</td>"
        f"<td>{_number(item.get('return_percent')):.2f}%</td>"
        f"<td>{_number(item.get('max_drawdown_percent')):.2f}%</td>"
        f"<td>{_number(item.get('profitable_window_percent')):.2f}%</td>"
        f"<td>{escape(str(item.get('promotion_status', '')))}</td>"
        "</tr>"
    )


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _css() -> str:
    return "body{margin:0;background:#050912;color:#edf6ff;font-family:Inter,system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:24px}header{display:flex;justify-content:space-between;align-items:center;gap:18px}a{color:#59adff;font-weight:800}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}.card{background:#0d1726;border:1px solid #22344c;border-radius:18px;padding:18px;margin:14px 0;overflow:auto}.hero strong{font-size:28px;color:#8de1bd}.danger{border-color:#6d3940}table{width:100%;border-collapse:collapse;min-width:1050px}th,td{text-align:left;padding:10px;border-bottom:1px solid #22344c}th{color:#9bb0c4}code{color:#8de1bd}label{display:grid;gap:7px;margin:12px 0;color:#b9c9da}select,input,textarea,button{font:inherit;padding:11px;border-radius:10px;border:1px solid #314761;background:#07101d;color:#edf6ff}textarea{min-height:80px}button{background:#1767a7;font-weight:800;cursor:pointer}pre{white-space:pre-wrap;max-height:460px;overflow:auto}"


__all__ = [
    "champion_challenger_page",
    "leadership_api",
    "promote_challenger",
    "register_challenger",
    "router",
]
