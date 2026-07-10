"""Dashboard API for SharipovAI operational agents."""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from operations_ai import cto_report, diagnose_system, heal_system


def install_operations_ai_api(app: FastAPI) -> None:
    if getattr(app.state, "operations_ai_api_installed", False):
        return
    app.state.operations_ai_api_installed = True

    @app.get("/api/operations/doctor")
    def doctor_snapshot() -> dict[str, Any]:
        return diagnose_system()

    @app.post("/api/operations/doctor/heal")
    def doctor_heal(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return heal_system(execute_safe_actions=bool(data.get("execute_safe_actions", False)))

    @app.get("/api/operations/cto")
    def operations_cto() -> dict[str, Any]:
        return cto_report()

    @app.get("/operations", response_class=HTMLResponse)
    def operations_page() -> HTMLResponse:
        report = cto_report()
        summary = report.get("summary", {})
        priorities = report.get("top_priorities", [])
        rows = "".join(
            f"<tr><td>{item.get('agent')}</td><td>{item.get('severity')}</td><td>{item.get('problem')}</td></tr>"
            for item in priorities
        ) or "<tr><td colspan='3'>Открытых инцидентов нет</td></tr>"
        return HTMLResponse(
            "<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>SharipovAI · Operations</title><style>body{margin:0;background:#07111f;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}main{padding:18px;max-width:980px;margin:auto}.card{background:#111827;border:1px solid #263245;border-radius:20px;padding:18px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:14px}small{display:block;color:#9db0cc}b{font-size:24px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #263245;text-align:left}a{color:#60a5fa}</style></head>"
            f"<body><main><section class='card'><h1>AI Doctor / AI CTO</h1><p>Сервисный контур: диагностика, безопасное восстановление и release gate. Реальные ордера недоступны.</p><p><a href='/api/operations/doctor'>Doctor JSON</a> · <a href='/api/operations/cto'>CTO JSON</a></p></section>"
            f"<section class='card'><div class='grid'><div class='stat'><small>Статус</small><b>{report.get('status')}</b></div><div class='stat'><small>Инциденты</small><b>{summary.get('incident_count', 0)}</b></div><div class='stat'><small>Критичные</small><b>{summary.get('high', 0)}</b></div><div class='stat'><small>Работают</small><b>{summary.get('working_agents', 0)}/{summary.get('total_agents', 0)}</b></div></div></section>"
            f"<section class='card'><h2>Главные проблемы</h2><table><thead><tr><th>Модуль</th><th>Уровень</th><th>Причина</th></tr></thead><tbody>{rows}</tbody></table></section></main></body></html>"
        )
