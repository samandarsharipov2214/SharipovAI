"""Paper Activity API for active demo trading simulation."""

from __future__ import annotations

from html import escape
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from paper_activity_engine import PaperActivityEngine


def install_paper_activity_api(app: FastAPI) -> None:
    """Install paper activity endpoints once."""

    if getattr(app.state, "paper_activity_api_installed", False):
        return
    app.state.paper_activity_api_installed = True

    @app.get("/api/paper-activity/state")
    def paper_state() -> dict[str, Any]:
        return PaperActivityEngine().state()

    @app.post("/api/paper-activity/tick")
    def paper_tick(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return PaperActivityEngine().tick(force=bool(data.get("force", False)), gate_payload=data.get("gate_payload") if isinstance(data.get("gate_payload"), dict) else None)

    @app.post("/api/paper-activity/reset")
    def paper_reset() -> dict[str, Any]:
        return PaperActivityEngine().reset()

    @app.get("/paper-activity", response_class=HTMLResponse)
    def paper_activity_page() -> HTMLResponse:
        return HTMLResponse(_render(PaperActivityEngine().state()))


def _render(state: dict[str, Any]) -> str:
    summary = state.get("summary", {})
    trades = "".join(_trade_row(trade) for trade in list(state.get("trades", []))[-30:]) or "<tr><td colspan='7'>Пока нет paper-сделок. Нажми tick.</td></tr>"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Paper Activity</title><style>{_css()}</style></head><body><main><section class="card"><span class="ok">PAPER ONLY</span><h1>Paper Activity Engine</h1><p>Это активная demo/paper-симуляция. Реальные ордера заблокированы.</p><p><a href="/">Главная</a> · <a href="/api/paper-activity/state">JSON state</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Trades</small><b>{summary.get('trade_count', 0)}</b></div><div class="stat"><small>Open</small><b>{summary.get('open_positions', 0)}</b></div><div class="stat"><small>Closed</small><b>{summary.get('closed_positions', 0)}</b></div><div class="stat"><small>Net PnL</small><b>{summary.get('net_pnl', 0)}</b></div><div class="stat"><small>Last reason</small><b>{escape(str(summary.get('last_reason', '')))}</b></div></div></section><section class="card"><h2>Как ускорить</h2><p>POST <code>/api/paper-activity/tick</code> с <code>{{"force": true}}</code> принудительно делает следующий paper tick.</p><p>Env: <code>PAPER_ACTIVITY_TICK_SECONDS</code>, <code>PAPER_ACTIVITY_MAX_OPEN</code>.</p></section><section class="card"><h2>Сделки</h2><table><thead><tr><th>ID</th><th>Asset</th><th>Side</th><th>Status</th><th>Notional</th><th>Net PnL</th><th>Source</th></tr></thead><tbody>{trades}</tbody></table></section></main></body></html>"""


def _trade_row(trade: dict[str, Any]) -> str:
    return f"<tr><td>{escape(str(trade.get('id', '')))}</td><td>{escape(str(trade.get('asset', '')))}</td><td>{escape(str(trade.get('side', '')))}</td><td>{escape(str(trade.get('status', '')))}</td><td>{escape(str(trade.get('notional', '')))}</td><td>{escape(str(trade.get('net_pnl', '')))}</td><td>{escape(str(trade.get('source', '')))}</td></tr>"


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1180px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:20px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #243044;text-align:left}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:6px 10px;font-weight:900}a{color:#60a5fa;font-weight:800}code{background:#020817;border:1px solid #243044;border-radius:8px;padding:2px 6px}"
