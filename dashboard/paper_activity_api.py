"""Virtual Account Activity API for active SharipovAI execution monitoring."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from paper_activity_autorun import paper_activity_autorun_status, start_paper_activity_autorun
from paper_activity_engine import PaperActivityEngine
from sharipovai_constitution import constitution_snapshot


def install_paper_activity_api(app: FastAPI) -> None:
    """Install virtual account activity endpoints once."""

    if getattr(app.state, "paper_activity_api_installed", False):
        return
    app.state.paper_activity_api_installed = True

    @app.on_event("startup")
    def paper_activity_startup() -> None:
        app.state.paper_activity_autorun = start_paper_activity_autorun()

    @app.get("/api/paper-activity/state")
    def paper_state() -> dict[str, Any]:
        return {"status": "ok", "state": PaperActivityEngine().state(catch_up=True), "autorun": paper_activity_autorun_status(), "constitution": constitution_snapshot()}

    @app.get("/api/virtual-account/state")
    def virtual_account_state() -> dict[str, Any]:
        return paper_state()

    @app.get("/api/paper-activity/trades")
    def paper_trades() -> dict[str, Any]:
        state = PaperActivityEngine().state(catch_up=True)
        return {"status": "ok", "summary": state.get("summary", {}), "trades": state.get("trades", []), "constitution": constitution_snapshot()}

    @app.get("/api/virtual-account/trades")
    def virtual_account_trades() -> dict[str, Any]:
        return paper_trades()

    @app.post("/api/paper-activity/tick")
    def paper_tick(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return PaperActivityEngine().tick(force=bool(data.get("force", False)), gate_payload=data.get("gate_payload") if isinstance(data.get("gate_payload"), dict) else None)

    @app.post("/api/virtual-account/tick")
    def virtual_account_tick(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        return paper_tick(payload)

    @app.post("/api/paper-activity/catch-up")
    def paper_catch_up(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return PaperActivityEngine().catch_up(max_ticks=int(data.get("max_ticks", 24) or 24))

    @app.post("/api/virtual-account/catch-up")
    def virtual_account_catch_up(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        return paper_catch_up(payload)

    @app.post("/api/paper-activity/reset")
    def paper_reset() -> dict[str, Any]:
        return PaperActivityEngine().reset()

    @app.get("/paper-activity", response_class=HTMLResponse)
    def paper_activity_page() -> HTMLResponse:
        return HTMLResponse(_render(PaperActivityEngine().state(catch_up=True), paper_activity_autorun_status()))

    @app.get("/virtual-account", response_class=HTMLResponse)
    def virtual_account_page() -> HTMLResponse:
        return HTMLResponse(_render(PaperActivityEngine().state(catch_up=True), paper_activity_autorun_status()))


def _render(state: dict[str, Any], autorun: dict[str, Any] | None = None) -> str:
    summary = state.get("summary", {})
    autorun = autorun or {}
    all_trades = list(state.get("trades", []))
    rows = list(reversed(all_trades))
    trades = "".join(_trade_row(trade, len(all_trades) - index) for index, trade in enumerate(rows)) or "<tr><td colspan='12'>Пока нет виртуальных сделок. Нажми tick или дождись autorun.</td></tr>"
    last_tick = _format_time(summary.get("last_tick_at"))
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Virtual Account</title><style>{_css()}</style></head><body><main><section class="card"><span class="ok">VIRTUAL ACCOUNT</span><h1>Virtual Account Execution</h1><p>Виртуален только счёт и исполнение ордеров. Новости, риск, портфель, комиссии, обучение, Evidence, аудит, сайт и Telegram должны работать как реальные органы системы.</p><p><a href="/">Главная</a> · <a href="/api/virtual-account/state">JSON state</a> · <a href="/api/virtual-account/trades">JSON all trades</a> · <a href="/realtime-status">Realtime Status</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Trades</small><b>{summary.get('trade_count', len(all_trades))}</b></div><div class="stat"><small>Open</small><b>{summary.get('open_positions', 0)}</b></div><div class="stat"><small>Closed</small><b>{summary.get('closed_positions', 0)}</b></div><div class="stat"><small>Net PnL</small><b>{summary.get('net_pnl', 0)}</b></div><div class="stat"><small>Fees</small><b>{summary.get('total_fees', 0)}</b></div><div class="stat"><small>Last tick</small><b>{escape(last_tick)}</b></div><div class="stat"><small>Last tick age</small><b>{escape(str(summary.get('last_tick_age_seconds', '—')))} сек</b></div><div class="stat"><small>Last reason</small><b>{escape(str(summary.get('last_reason', '')))}</b></div><div class="stat"><small>Execution</small><b>{escape(str(summary.get('execution_mode', state.get('execution_mode', 'virtual_execution_only'))))}</b></div><div class="stat"><small>Real orders</small><b>blocked</b></div><div class="stat"><small>Autorun</small><b>{escape(str(autorun.get('status', 'unknown')))}</b></div><div class="stat"><small>Thread</small><b>{'alive' if autorun.get('thread_alive') else 'not alive'}</b></div></div></section><section class="card"><h2>Управление</h2><p>POST <code>/api/virtual-account/tick</code> с <code>{{"force": true}}</code> принудительно делает следующий виртуальный execution tick.</p><p>POST <code>/api/virtual-account/catch-up</code> догоняет пропущенные tick после сна сервера.</p><p>Env: <code>VIRTUAL_ACCOUNT_TICK_SECONDS</code>, <code>VIRTUAL_ACCOUNT_MAX_OPEN</code>, <code>VIRTUAL_ACCOUNT_MAX_CATCH_UP_TICKS</code>. Старые PAPER_* env поддерживаются только для совместимости.</p></section><section class="card"><h2>Все виртуальные сделки</h2><table><thead><tr><th>#</th><th>ID</th><th>Asset</th><th>Side</th><th>Status</th><th>Открыта</th><th>Закрыта</th><th>Длительность</th><th>Notional</th><th>Net PnL</th><th>Real order</th><th>Source</th></tr></thead><tbody>{trades}</tbody></table></section></main></body></html>"""


def _trade_row(trade: dict[str, Any], number: int) -> str:
    opened_at = int(trade.get("opened_at", 0) or 0)
    closed_at = int(trade.get("closed_at", 0) or 0)
    return f"<tr><td>{number}</td><td>{escape(str(trade.get('id', '')))}</td><td>{escape(str(trade.get('asset', '')))}</td><td>{escape(str(trade.get('side', '')))}</td><td>{escape(str(trade.get('status', '')))}</td><td>{escape(_format_time(opened_at))}</td><td>{escape(_format_time(closed_at) if closed_at else 'ещё открыта')}</td><td>{escape(_duration(opened_at, closed_at))}</td><td>{escape(str(trade.get('notional', '')))}</td><td>{escape(str(trade.get('net_pnl', '')))}</td><td>{escape('yes' if trade.get('real_order_placed') else 'no')}</td><td>{escape(str(trade.get('source', '')))}</td></tr>"


def _format_time(value: Any) -> str:
    try:
        seconds = int(value or 0)
    except Exception:
        seconds = 0
    if seconds <= 0:
        return "—"
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%d.%m %H:%M:%S UTC")


def _duration(opened_at: int, closed_at: int) -> str:
    if not opened_at:
        return "—"
    end = closed_at or int(datetime.now(tz=timezone.utc).timestamp())
    diff = max(0, end - opened_at)
    if diff < 60:
        return f"{diff} сек"
    if diff < 3600:
        return f"{diff // 60} мин"
    if diff < 86400:
        return f"{diff // 3600} ч {(diff % 3600) // 60} мин"
    return f"{diff // 86400} дн {(diff % 86400) // 3600} ч"


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1280px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:18px}table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:6px 10px;font-weight:900}a{color:#60a5fa;font-weight:800}code{background:#020817;border:1px solid #243044;border-radius:8px;padding:2px 6px}"
