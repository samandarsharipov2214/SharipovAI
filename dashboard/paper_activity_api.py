"""Paper Activity API for active demo trading simulation."""

from __future__ import annotations

from html import escape
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from paper_activity_autorun import paper_activity_autorun_status, start_paper_activity_autorun
from paper_activity_engine import PaperActivityEngine


def install_paper_activity_api(app: FastAPI) -> None:
    """Install paper activity endpoints once."""

    if getattr(app.state, "paper_activity_api_installed", False):
        return
    app.state.paper_activity_api_installed = True

    @app.on_event("startup")
    def paper_activity_startup() -> None:
        app.state.paper_activity_autorun = start_paper_activity_autorun()

    @app.get("/api/paper-activity/state")
    def paper_state() -> dict[str, Any]:
        return {"status": "ok", "state": PaperActivityEngine().state(catch_up=True), "autorun": paper_activity_autorun_status()}

    @app.get("/api/paper-activity/trades")
    def paper_trades() -> dict[str, Any]:
        state = PaperActivityEngine().state(catch_up=True)
        return {"status": "ok", "summary": state.get("summary", {}), "trades": state.get("trades", [])}

    @app.post("/api/paper-activity/tick")
    def paper_tick(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return PaperActivityEngine().tick(force=bool(data.get("force", False)), gate_payload=data.get("gate_payload") if isinstance(data.get("gate_payload"), dict) else None)

    @app.post("/api/paper-activity/catch-up")
    def paper_catch_up(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return PaperActivityEngine().catch_up(max_ticks=int(data.get("max_ticks", 24) or 24))

    @app.post("/api/paper-activity/reset")
    def paper_reset() -> dict[str, Any]:
        return PaperActivityEngine().reset()

    @app.get("/paper-activity", response_class=HTMLResponse)
    def paper_activity_page() -> HTMLResponse:
        return HTMLResponse(_render(PaperActivityEngine().state(catch_up=True), paper_activity_autorun_status()))


def _render(state: dict[str, Any], autorun: dict[str, Any] | None = None) -> str:
    summary = state.get("summary", {})
    autorun = autorun or {}
    all_trades = list(state.get("trades", []))
    rows = list(reversed(all_trades))
    trades = "".join(_trade_row(trade, len(all_trades) - index) for index, trade in enumerate(rows)) or "<tr><td colspan='8'>Пока нет paper-сделок. Нажми tick.</td></tr>"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Paper Activity</title><style>{_css()}</style></head><body><main><section class="card"><span class="ok">PAPER ONLY</span><h1>Paper Activity Engine</h1><p>Это активная demo/paper-симуляция. Реальные ордера заблокированы. На этой странице показываются <b>все сделки</b>, не только последние.</p><p><a href="/">Главная</a> · <a href="/api/paper-activity/state">JSON state</a> · <a href="/api/paper-activity/trades">JSON all trades</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Trades</small><b>{summary.get('trade_count', len(all_trades))}</b></div><div class="stat"><small>Open</small><b>{summary.get('open_positions', 0)}</b></div><div class="stat"><small>Closed</small><b>{summary.get('closed_positions', 0)}</b></div><div class="stat"><small>Net PnL</small><b>{summary.get('net_pnl', 0)}</b></div><div class="stat"><small>Fees</small><b>{summary.get('total_fees', 0)}</b></div><div class="stat"><small>Last reason</small><b>{escape(str(summary.get('last_reason', '')))}</b></div><div class="stat"><small>Last tick age</small><b>{escape(str(summary.get('last_tick_age_seconds', '—')))}</b></div><div class="stat"><small>Autorun</small><b>{escape(str(autorun.get('status', 'unknown')))}</b></div><div class="stat"><small>Thread</small><b>{'alive' if autorun.get('thread_alive') else 'not alive'}</b></div></div></section><section class="card"><h2>Как ускорить</h2><p>POST <code>/api/paper-activity/tick</code> с <code>{{"force": true}}</code> принудительно делает следующий paper tick.</p><p>POST <code>/api/paper-activity/catch-up</code> догоняет пропущенные tick после ночи/сна сервера.</p><p>Env: <code>PAPER_ACTIVITY_AUTORUN_ENABLED</code>, <code>PAPER_ACTIVITY_TICK_SECONDS</code>, <code>PAPER_ACTIVITY_MAX_OPEN</code>, <code>PAPER_ACTIVITY_MAX_CATCH_UP_TICKS</code>.</p></section><section class="card"><h2>Все сделки</h2><table><thead><tr><th>#</th><th>ID</th><th>Asset</th><th>Side</th><th>Status</th><th>Notional</th><th>Net PnL</th><th>Source</th></tr></thead><tbody>{trades}</tbody></table></section></main></body></html>"""


def _trade_row(trade: dict[str, Any], number: int) -> str:
    return f"<tr><td>{number}</td><td>{escape(str(trade.get('id', '')))}</td><td>{escape(str(trade.get('asset', '')))}</td><td>{escape(str(trade.get('side', '')))}</td><td>{escape(str(trade.get('status', '')))}</td><td>{escape(str(trade.get('notional', '')))}</td><td>{escape(str(trade.get('net_pnl', '')))}</td><td>{escape(str(trade.get('source', '')))}</td></tr>"


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1180px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:20px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #243044;text-align:left}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:6px 10px;font-weight:900}a{color:#60a5fa;font-weight:800}code{background:#020817;border:1px solid #243044;border-radius:8px;padding:2px 6px}"
