"""Read-only Russian report for the market-backed virtual account.

The report refreshes mark-to-market prices through ``state()`` but never opens or
closes a position and never places a real exchange order.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_paper_engine import PaperActivityEngine


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _trade_view(trade: dict[str, Any]) -> dict[str, Any]:
    status = str(trade.get("status", "UNKNOWN")).upper()
    return {
        "id": trade.get("id"),
        "symbol": trade.get("symbol") or trade.get("asset"),
        "side": str(trade.get("side", "")).upper(),
        "status": status,
        "entry_price": trade.get("entry_price"),
        "current_price": trade.get("current_price"),
        "exit_price": trade.get("exit_price"),
        "net_pnl_usdt": round(_number(trade.get("net_pnl")), 4),
        "gross_pnl_usdt": round(_number(trade.get("gross_pnl")), 4),
        "fees_usdt": round(_number(trade.get("fee")), 4),
        "opened_at": trade.get("opened_at"),
        "closed_at": trade.get("closed_at"),
        "close_reason_ru": trade.get("close_reason_ru"),
        "quote_source": trade.get("last_quote_source") or trade.get("quote_source"),
    }


def main() -> int:
    state = PaperActivityEngine().state()
    summary = state.get("summary", {}) if isinstance(state, dict) else {}
    trades = [item for item in state.get("trades", []) if isinstance(item, dict)]
    open_trades = [item for item in trades if str(item.get("status", "")).upper() == "OPEN"]
    closed_trades = [item for item in trades if str(item.get("status", "")).upper() == "CLOSED"]

    winning = [item for item in closed_trades if _number(item.get("net_pnl")) > 0]
    losing = [item for item in closed_trades if _number(item.get("net_pnl")) < 0]
    breakeven = [item for item in closed_trades if _number(item.get("net_pnl")) == 0]
    gross_profit = sum(max(_number(item.get("net_pnl")), 0.0) for item in closed_trades)
    gross_loss = sum(min(_number(item.get("net_pnl")), 0.0) for item in closed_trades)

    payload = {
        "status": "ok",
        "report_type": "read_only_mark_to_market",
        "starting_balance_usdt": 10000.0,
        "operations": {
            "opened_trades": len(trades),
            "completed_trades": len(closed_trades),
            "open_positions": len(open_trades),
            "exchange_actions_estimate": len(open_trades) + 2 * len(closed_trades),
            "buy_trades": int(summary.get("buy_count", 0) or 0),
            "sell_trades": int(summary.get("sell_count", 0) or 0),
            "skipped_cycles": int(summary.get("skipped_count", 0) or 0),
        },
        "results": {
            "profitable_closed": len(winning),
            "losing_closed": len(losing),
            "breakeven_closed": len(breakeven),
            "win_rate_percent": round(_number(summary.get("win_rate_percent")), 2),
            "gross_profit_closed_usdt": round(gross_profit, 4),
            "gross_loss_closed_usdt": round(gross_loss, 4),
            "realized_net_pnl_usdt": round(_number(summary.get("closed_net_pnl")), 4),
            "unrealized_net_pnl_usdt": round(_number(summary.get("unrealized_net_pnl")), 4),
            "total_net_pnl_usdt": round(_number(summary.get("net_pnl")), 4),
            "total_fees_usdt": round(_number(summary.get("total_fees")), 4),
            "cash_usdt": round(_number(summary.get("cash")), 4),
            "equity_usdt": round(_number(summary.get("equity")), 4),
            "return_percent": round(_number(summary.get("return_percent")), 4),
        },
        "safety": {
            "market_price_accounting": summary.get("market_price_accounting") is True,
            "real_orders_blocked": summary.get("real_orders_blocked") is True,
        },
        "last_activity": {
            "status": summary.get("last_tick_status"),
            "reason_ru": summary.get("last_reason_ru"),
            "age_seconds": summary.get("last_tick_age_seconds"),
        },
        "open_positions_detail": [_trade_view(item) for item in open_trades],
        "last_closed_trades": [_trade_view(item) for item in closed_trades[-20:]],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
