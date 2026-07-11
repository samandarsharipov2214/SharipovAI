"""Stable responses for static assets whose legacy clients require extra hooks."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response


def install_static_contracts_middleware(app: FastAPI) -> None:
    if getattr(app.state, "static_contracts_middleware_installed", False):
        return
    app.state.static_contracts_middleware_installed = True

    @app.middleware("http")
    async def static_contracts(request: Request, call_next):
        if request.method == "GET" and request.url.path == "/static/mini-app-live.js":
            path = Path(__file__).resolve().parent / "static" / "mini-app-live.js"
            source = path.read_text(encoding="utf-8") if path.exists() else ""
            compatibility = r'''

// Stable exchange-monitor contract for Mini App clients.
function renderExchangeMonitor(state) {
  const exchange = (state && state.exchange_status) || {};
  const monitoring = (state && state.online_monitoring) || {};
  const set = (id, value) => { const node = document.getElementById(id); if (node) node.textContent = String(value); };
  set('exchange-mode', exchange.mode || 'Песочница');
  set('exchange-preview', exchange.preview || 'Расчёт условий');
  set('exchange-live', monitoring.real_orders_blocked === false ? 'Разрешены' : 'Заблокированы');
  set('exchange-fees', state && state.total_fees || 0);
  set('exchange-drag', state && state.commission_drag || 0);
  set('exchange-breakeven', state && state.break_even_price || '—');
}
'''
            if "function renderExchangeMonitor" not in source:
                source += compatibility
            return Response(source, media_type="application/javascript; charset=utf-8")
        return await call_next(request)


__all__: tuple[str, ...] = ("install_static_contracts_middleware",)
