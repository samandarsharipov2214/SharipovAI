"""Admin research dashboard for experiments, comparisons and promotion reports."""
from __future__ import annotations

import json
from html import escape
from typing import Any, Mapping

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from autonomous_trading.startup_reconciliation import StartupExecutionReconciler
from dashboard.auth import AdminPrincipal, admin_principal
from exchange_connector.private_ws_gate import PrivateStreamHealthRepository
from experiments import ExperimentRegistry, PromotionGateEngine, PromotionTarget
from storage import ProjectDatabase
from validation import FillValidationRepository

router = APIRouter(tags=["research-experiments"])


@router.get("/api/experiments")
def experiments_api(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    _principal: AdminPrincipal = Depends(admin_principal),
) -> dict[str, Any]:
    rows = _registry(request).list(limit=limit, newest_first=True)
    return {"status": "ok", "count": len(rows), "experiments": rows}


@router.get("/api/experiments/compare")
def compare_experiments_api(
    request: Request,
    ids: str = Query(default=""),
    _principal: AdminPrincipal = Depends(admin_principal),
) -> dict[str, Any]:
    identifiers = _ids(ids)
    if len(identifiers) < 2:
        identifiers = [
            str(item["experiment_id"])
            for item in _registry(request).list(limit=2, newest_first=True)
        ]
    if len(identifiers) < 2:
        raise HTTPException(status_code=400, detail="at least two experiments are required")
    try:
        return _registry(request).compare(identifiers)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"experiment not found: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/experiments/{experiment_id}")
def experiment_api(
    request: Request,
    experiment_id: str,
    _principal: AdminPrincipal = Depends(admin_principal),
) -> dict[str, Any]:
    record = _registry(request).get(experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return {
        "status": "ok",
        "experiment": record,
        "history": _registry(request).history(experiment_id),
        "fill_validations": _validation_repository(request).list(
            experiment_id=experiment_id,
            limit=50,
        ),
    }


@router.post("/api/experiments/{experiment_id}/promotion-report")
def generate_promotion_report(
    request: Request,
    experiment_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    principal: AdminPrincipal = Depends(admin_principal),
) -> dict[str, Any]:
    registry = _registry(request)
    experiment = registry.get(experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    try:
        target = PromotionTarget(str(payload.get("target_stage", "paper")).strip().lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="unsupported promotion target") from exc

    validation_rows = _validation_repository(request).list(
        experiment_id=experiment_id,
        limit=1,
    )
    validation = validation_rows[0] if validation_rows else {}
    reconciliation: Mapping[str, Any] = {}
    private_stream: Mapping[str, Any] = {}
    if target in {PromotionTarget.TESTNET, PromotionTarget.CONTROLLED_MAINNET}:
        database = _database(request)
        reconciliation = StartupExecutionReconciler(
            database=database,
            environment="testnet",
            require_private_stream=True,
        ).reconcile().to_dict()
        private_stream = PrivateStreamHealthRepository(
            database=database,
            environment="testnet",
        ).evaluate(required=True).to_dict()

    report = PromotionGateEngine().evaluate(
        experiment,
        target_stage=target,
        paper_testnet_validation=validation,
        reconciliation=reconciliation,
        private_stream=private_stream,
    ).to_dict()
    updated = registry.save_promotion_report(
        experiment_id,
        report,
        actor=principal.username,
        expected_version=int(experiment["version"]),
    )
    return {
        "status": "ok",
        "report": report,
        "experiment": updated,
        "manual_approval_token_format": f"APPROVE:{experiment_id}:{target.value}",
        "runtime_flags_changed": False,
    }


@router.post("/api/experiments/{experiment_id}/promotion-decision")
def promotion_decision(
    request: Request,
    experiment_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    principal: AdminPrincipal = Depends(admin_principal),
) -> dict[str, Any]:
    registry = _registry(request)
    experiment = registry.get(experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    try:
        updated = registry.manual_decision(
            experiment_id,
            target_stage=str(payload.get("target_stage", "")),
            approve=bool(payload.get("approve", False)),
            actor=principal.username,
            reason=str(payload.get("reason", "")),
            approval_token=str(payload.get("approval_token", "")),
            expected_version=int(experiment["version"]),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "ok",
        "experiment": updated,
        "runtime_flags_changed": False,
        "execution_enabled": False,
    }


@router.get("/backtest-results", response_class=HTMLResponse)
def backtest_results_page(
    request: Request,
    principal: AdminPrincipal = Depends(admin_principal),
) -> HTMLResponse:
    experiments = _registry(request).list(limit=200, newest_first=True)
    return HTMLResponse(_render_results(experiments, principal.username))


@router.get("/experiment-comparison", response_class=HTMLResponse)
def experiment_comparison_page(
    request: Request,
    ids: str = Query(default=""),
    principal: AdminPrincipal = Depends(admin_principal),
) -> HTMLResponse:
    identifiers = _ids(ids)
    if len(identifiers) < 2:
        identifiers = [
            str(item["experiment_id"])
            for item in _registry(request).list(limit=2, newest_first=True)
        ]
    comparison = (
        _registry(request).compare(identifiers)
        if len(identifiers) >= 2
        else {"status": "empty", "rows": [], "ranking": []}
    )
    return HTMLResponse(_render_comparison(comparison, principal.username))


def _registry(request: Request) -> ExperimentRegistry:
    return ExperimentRegistry(_database(request))


def _validation_repository(request: Request) -> FillValidationRepository:
    return FillValidationRepository(_database(request))


def _database(request: Request) -> ProjectDatabase:
    database = getattr(request.app.state, "project_database", None)
    return database if isinstance(database, ProjectDatabase) else ProjectDatabase()


def _ids(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()][:20]


def _render_results(experiments: list[dict[str, Any]], username: str) -> str:
    rows = "".join(_experiment_row(item) for item in experiments) or (
        "<tr><td colspan='10'>No persisted experiments yet.</td></tr>"
    )
    payload = json.dumps(experiments, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SharipovAI · Backtest Results</title>
<style>{_css()}</style></head><body><main><header><div><h1>Backtest Results</h1><p>Admin: {escape(username)} · canonical ProjectDatabase evidence</p></div><nav><a href="/">Dashboard</a> · <a href="/execution-status">Execution</a> · <a href="/experiment-comparison">Compare</a></nav></header>
<section class="card"><p>Promotion reports are automated evidence only. Every promotion requires a separate manual decision and never changes exchange flags.</p></section>
<section class="card"><table><thead><tr><th>Experiment</th><th>Strategy</th><th>Status</th><th>Commit</th><th>Manifest</th><th>OOS PnL</th><th>Return</th><th>Drawdown</th><th>Profitable windows</th><th>Promotion</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="card"><h2>Raw evidence</h2><pre id="payload"></pre></section></main><script>document.getElementById('payload').textContent=JSON.stringify({payload},null,2);</script></body></html>"""


def _render_comparison(comparison: Mapping[str, Any], username: str) -> str:
    rows = comparison.get("rows") if isinstance(comparison.get("rows"), list) else []
    ranking = comparison.get("ranking") if isinstance(comparison.get("ranking"), list) else []
    table = "".join(
        "<tr>"
        f"<td>{ranking.index(item.get('experiment_id')) + 1 if item.get('experiment_id') in ranking else '—'}</td>"
        f"<td><a href='/api/experiments/{escape(str(item.get('experiment_id', '')))}'>{escape(str(item.get('experiment_id', '')))}</a></td>"
        f"<td>{escape(str(item.get('strategy_name', '')))}</td>"
        f"<td>{_number(item.get('oos_net_pnl')):,.2f}</td>"
        f"<td>{_number(item.get('return_percent')):.2f}%</td>"
        f"<td>{_number(item.get('max_drawdown_percent')):.2f}%</td>"
        f"<td>{_number(item.get('profitable_window_percent')):.2f}%</td>"
        f"<td>{escape(str(item.get('promotion_status', '')))}</td>"
        "</tr>"
        for item in rows
    ) or "<tr><td colspan='8'>Select at least two persisted experiments.</td></tr>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SharipovAI · Experiment Comparison</title><style>{_css()}</style></head><body><main><header><div><h1>Experiment Comparison</h1><p>Admin: {escape(username)} · identical all-cost metrics</p></div><nav><a href="/backtest-results">Results</a> · <a href="/execution-status">Execution</a></nav></header><section class="card"><table><thead><tr><th>Rank</th><th>Experiment</th><th>Strategy</th><th>OOS PnL</th><th>Return</th><th>Drawdown</th><th>Profitable windows</th><th>Promotion</th></tr></thead><tbody>{table}</tbody></table></section></main></body></html>"""


def _experiment_row(item: Mapping[str, Any]) -> str:
    results = item.get("results") if isinstance(item.get("results"), Mapping) else {}
    walk = results.get("walk_forward") if isinstance(results.get("walk_forward"), Mapping) else {}
    manifest = item.get("manifest") if isinstance(item.get("manifest"), Mapping) else {}
    promotion = item.get("promotion") if isinstance(item.get("promotion"), Mapping) else {}
    identifier = escape(str(item.get("experiment_id", "")))
    return (
        "<tr>"
        f"<td><a href='/api/experiments/{identifier}'>{identifier}</a></td>"
        f"<td>{escape(str(item.get('strategy_name', '')))}</td>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td><code>{escape(str(item.get('commit_sha', ''))[:12])}</code></td>"
        f"<td>{escape(str(manifest.get('manifest_id', '')))}</td>"
        f"<td>{_number(walk.get('net_pnl')):,.2f}</td>"
        f"<td>{_number(walk.get('return_percent')):.2f}%</td>"
        f"<td>{_number(walk.get('max_drawdown_percent')):.2f}%</td>"
        f"<td>{_number(walk.get('profitable_window_percent')):.2f}%</td>"
        f"<td>{escape(str(promotion.get('status', 'not_evaluated')))}</td>"
        "</tr>"
    )


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _css() -> str:
    return "body{margin:0;background:#050912;color:#edf6ff;font-family:Inter,system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:24px}header{display:flex;justify-content:space-between;align-items:center;gap:18px}a{color:#59adff;font-weight:800}.card{background:#0d1726;border:1px solid #22344c;border-radius:18px;padding:16px;margin:14px 0;overflow:auto}table{width:100%;border-collapse:collapse;min-width:1100px}th,td{text-align:left;padding:10px;border-bottom:1px solid #22344c}th{color:#9bb0c4}code{color:#8de1bd}pre{white-space:pre-wrap;max-height:520px;overflow:auto}"


__all__ = [
    "backtest_results_page",
    "compare_experiments_api",
    "experiment_api",
    "experiment_comparison_page",
    "experiments_api",
    "generate_promotion_report",
    "promotion_decision",
    "router",
]
