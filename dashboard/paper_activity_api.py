"""Virtual Account Activity API for active SharipovAI execution monitoring."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from market_paper_engine import PaperActivityEngine
from paper_activity_autorun import paper_activity_autorun_status, start_paper_activity_autorun
from sharipovai_constitution import constitution_snapshot
from .market_intelligence_api import install_market_intelligence_api
from .trade_explanations import enrich_tick_result, enrich_virtual_state


def install_paper_activity_api(app: FastAPI) -> None:
    """Install virtual account activity endpoints once."""

    install_market_intelligence_api(app)
    if getattr(app.state, "paper_activity_api_installed", False):
        return
    app.state.paper_activity_api_installed = True

    @app.on_event("startup")
    def paper_activity_startup() -> None:
        app.state.paper_activity_autorun = start_paper_activity_autorun()

    @app.get("/api/paper-activity/state")
    def paper_state() -> JSONResponse:
        return _legacy_runtime_disabled()

    @app.get("/api/virtual-account/state")
    def virtual_account_state() -> JSONResponse:
        return paper_state()

    @app.get("/api/paper-activity/trades")
    def paper_trades() -> JSONResponse:
        return _legacy_runtime_disabled()

    @app.get("/api/virtual-account/trades")
    def virtual_account_trades() -> JSONResponse:
        return paper_trades()

    @app.post("/api/paper-activity/tick")
    def paper_tick(payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
        del payload
        return _legacy_runtime_disabled()

    @app.post("/api/virtual-account/tick")
    def virtual_account_tick(payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
        return paper_tick(payload)

    @app.post("/api/paper-activity/catch-up")
    def paper_catch_up(payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
        del payload
        return _legacy_runtime_disabled()

    @app.post("/api/virtual-account/catch-up")
    def virtual_account_catch_up(payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
        return paper_catch_up(payload)

    @app.post("/api/paper-activity/reset")
    def paper_reset() -> JSONResponse:
        return _legacy_runtime_disabled()

    @app.get("/paper-activity", response_class=HTMLResponse)
    def paper_activity_page() -> JSONResponse:
        return _legacy_runtime_disabled()

    @app.get("/virtual-account", response_class=HTMLResponse)
    def virtual_account_page() -> JSONResponse:
        return _legacy_runtime_disabled()


def _legacy_runtime_disabled() -> JSONResponse:
    """Do not let compatibility endpoints create a second paper decision path."""

    return JSONResponse(
        status_code=410,
        content={
            "status": "blocked",
            "source_of_truth": "CouncilAuthorizedPaperLoop",
            "replacement": "/api/autonomous-paper/status",
            "automatic_legacy_mutation": False,
            "reason": "legacy PaperActivityEngine is not an authorized decision or execution runtime",
        },
    )


def _render(state: dict[str, Any], autorun: dict[str, Any] | None = None) -> str:
    summary = state.get("summary", {})
    autorun = autorun or {}
    all_trades = list(state.get("trades", []))
    rows = list(reversed(all_trades))
    trades = "".join(_trade_row(trade, len(all_trades) - index) for index, trade in enumerate(rows)) or "<tr><td colspan='16'>Пока нет виртуальных сделок. Нажми tick или дождись autorun.</td></tr>"
    last_tick = _format_time(summary.get("last_tick_at"))
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Virtual Account</title><style>{_css()}</style></head><body><main><section class="card"><span class="ok">VIRTUAL ACCOUNT</span><h1>Virtual Account Execution</h1><p class="legacy-name">Paper Activity Engine · Market-backed paper execution</p><p>Виртуален только счёт и исполнение ордеров. Котировки, комиссии и PnL считаются по подтверждённым рыночным данным. Размер позиции масштабируется от equity, но защитный резерв не используется.</p><p><a href="/">Главная</a> · <a href="/api/virtual-account/state">JSON state</a> · <a href="/api/virtual-account/trades">JSON all trades</a> · <a href="/realtime-status">Realtime Status</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Trades</small><b>{summary.get('trade_count', len(all_trades))}</b></div><div class="stat"><small>Buy / Sell</small><b>{summary.get('buy_count', 0)} / {summary.get('sell_count', 0)}</b></div><div class="stat"><small>Open</small><b>{summary.get('open_positions', 0)}</b></div><div class="stat"><small>Closed</small><b>{summary.get('closed_positions', 0)}</b></div><div class="stat"><small>Equity</small><b>{_money(summary.get('equity'))}</b></div><div class="stat"><small>В позициях</small><b>{_money(summary.get('deployed_notional'))}</b></div><div class="stat"><small>Можно распределить</small><b>{_money(summary.get('available_to_allocate'))}</b></div><div class="stat"><small>Защитный резерв</small><b>{_money(summary.get('reserve_amount'))} · {summary.get('reserve_percent', 0)}%</b></div><div class="stat"><small>Использование капитала</small><b>{summary.get('capital_utilization_percent', 0)}%</b></div><div class="stat"><small>Использование доступной части</small><b>{summary.get('deployable_utilization_percent', 0)}%</b></div><div class="stat"><small>Win rate</small><b>{summary.get('win_rate_percent', 0)}%</b></div><div class="stat"><small>Net PnL</small><b>{_money(summary.get('net_pnl'))}</b></div><div class="stat"><small>Fees</small><b>{_money(summary.get('total_fees'))}</b></div><div class="stat"><small>Last tick</small><b>{escape(last_tick)}</b></div><div class="stat"><small>Last reason</small><b>{escape(str(summary.get('last_reason_ru', summary.get('last_reason', ''))))}</b></div><div class="stat"><small>Real orders</small><b>blocked</b></div><div class="stat"><small>Autorun</small><b>{escape(str(autorun.get('status', 'unknown')))}</b></div></div></section><section class="card"><h2>Все сделки · Все виртуальные операции</h2><table><thead><tr><th>#</th><th>ID</th><th>Пара</th><th>Операция</th><th>Статус</th><th>Размер USDT</th><th>Открыта</th><th>Закрыта</th><th>Вход</th><th>Текущая / выход</th><th>Net PnL</th><th>Комиссия</th><th>Почему открыта</th><th>Почему закрыта</th><th>Real order</th><th>Источник</th></tr></thead><tbody>{trades}</tbody></table></section></main></body></html>"""


def _trade_row(trade: dict[str, Any], number: int) -> str:
    opened_at = int(trade.get("opened_at", 0) or 0)
    closed_at = int(trade.get("closed_at", 0) or 0)
    side = str(trade.get("side", ""))
    operation = "BUY · покупка" if side.upper() == "BUY" else "SELL · продажа" if side.upper() == "SELL" else side
    return (
        f"<tr><td>{number}</td><td>{escape(str(trade.get('id', '')))}</td>"
        f"<td>{escape(str(trade.get('asset', trade.get('symbol', ''))))}</td><td>{escape(operation)}</td>"
        f"<td>{escape(str(trade.get('status', '')))}</td><td>{escape(_money(trade.get('notional')))}</td>"
        f"<td>{escape(_format_time(opened_at))}</td>"
        f"<td>{escape(_format_time(closed_at) if closed_at else 'ещё открыта')}</td>"
        f"<td>{escape(_price(trade.get('entry_price')))}</td><td>{escape(_price(trade.get('exit_price') or trade.get('current_price')))}</td>"
        f"<td>{escape(_money(trade.get('net_pnl')))}</td><td>{escape(_money(trade.get('fee')))}</td>"
        f"<td>{escape(str(trade.get('entry_reason_ru', 'причина входа не записана')))}</td>"
        f"<td>{escape(str(trade.get('close_reason_ru', 'позиция ещё открыта')))}</td>"
        f"<td>{escape('yes' if trade.get('real_order_placed') else 'no')}</td>"
        f"<td>{escape(str(trade.get('quote_source', trade.get('source', ''))))}</td></tr>"
    )


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.1f}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _price(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    digits = 1 if abs(number) >= 100 else 2 if abs(number) >= 10 else 4
    return f"{number:,.{digits}f}".replace(",", " ")


def _format_time(value: Any) -> str:
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        return "—"
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%d.%m %H:%M:%S UTC")


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1700px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0;overflow:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:18px}table{width:100%;border-collapse:collapse;font-size:13px;min-width:1650px}td,th{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}td:nth-child(13),td:nth-child(14){min-width:260px;white-space:normal}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:6px 10px;font-weight:900}a{color:#60a5fa;font-weight:800}"
