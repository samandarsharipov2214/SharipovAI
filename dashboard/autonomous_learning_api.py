"""Autonomous Learning API for SharipovAI dashboard."""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from learning.autonomous_learning_cycle import morning_report, run_autonomous_learning_cycle


def install_autonomous_learning_api(app: FastAPI) -> None:
    """Install safe paper-realism learning endpoints."""

    if getattr(app.state, "autonomous_learning_api_installed", False):
        return
    app.state.autonomous_learning_api_installed = True

    @app.get("/api/autonomous-learning/snapshot")
    def autonomous_learning_snapshot() -> dict[str, Any]:
        return morning_report()

    @app.post("/api/autonomous-learning/run")
    def autonomous_learning_run(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        payload = payload or {}
        cycles = int(payload.get("cycles", 4) or 4)
        return run_autonomous_learning_cycle(cycles=max(1, min(cycles, 4)))

    @app.get("/api/autonomous-learning/morning-report")
    def autonomous_learning_morning_report() -> dict[str, Any]:
        return morning_report()

    @app.get("/autonomous-learning", response_class=HTMLResponse)
    def autonomous_learning_page() -> HTMLResponse:
        report = morning_report()
        summary = report.get("summary", {})
        lessons = report.get("lessons", [])
        actions = report.get("next_actions", [])
        lesson_rows = "".join(
            f"<li><b>{lesson.get('symbol')}</b>: {lesson.get('rule')} · impact {lesson.get('impact')}</li>"
            for lesson in lessons
        )
        action_rows = "".join(f"<li>{action}</li>" for action in actions)
        return HTMLResponse(
            "<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>SharipovAI · Autonomous Learning</title>"
            "<style>body{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}main{padding:20px;max-width:900px;margin:auto}.card{background:#111827;border:1px solid #263245;border-radius:20px;padding:18px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:14px}small{display:block;color:#9db0cc}b{font-size:22px}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:7px 12px;font-weight:900}</style></head>"
            "<body><main>"
            "<section class='card'><span class='ok'>PAPER-REALISM</span><h1>Autonomous Learning Cycle</h1><p>Реальные деньги защищены. AI тренируется как при настоящем капитале: решения, комиссии, ошибки и уроки записаны в Evidence Vault.</p></section>"
            f"<section class='card'><h2>Итог</h2><div class='grid'><div class='stat'><small>Cycles</small><b>{summary.get('cycles')}</b></div><div class='stat'><small>Paper PnL</small><b>{summary.get('paper_pnl')} USDT</b></div><div class='stat'><small>Fees</small><b>{summary.get('fees')} USDT</b></div><div class='stat'><small>Prevented loss</small><b>{summary.get('prevented_loss')} USDT</b></div></div></section>"
            f"<section class='card'><h2>Уроки</h2><ul>{lesson_rows}</ul></section>"
            f"<section class='card'><h2>Следующие действия</h2><ol>{action_rows}</ol></section>"
            "<section class='card'><p><a href='/api/autonomous-learning/morning-report'>JSON morning report</a> · <a href='/api/evidence-vault/snapshot'>Evidence Vault</a> · <a href='/'>Mini App</a></p></section>"
            "</main></body></html>"
        )
