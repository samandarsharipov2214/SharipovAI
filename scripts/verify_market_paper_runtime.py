"""Post-deploy verification for market-backed virtual account execution."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# When Python executes ``/app/scripts/verify_market_paper_runtime.py`` directly,
# sys.path starts at ``/app/scripts`` rather than the project root.  Add the
# root explicitly so runtime modules are importable regardless of cwd.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_paper_engine import PaperActivityEngine


def main() -> int:
    if os.getenv("SHARIPOVAI_VERIFY_IMPORT_ONLY", "0").strip().lower() in {"1", "true", "yes", "on"}:
        print("MARKET_PAPER_VERIFIER_IMPORT_OK")
        return 0

    engine = PaperActivityEngine()
    tick = engine.tick(force=True)
    state = engine.state()
    summary = state.get("summary", {})
    payload = {
        "status": "ok",
        "tick_status": tick.get("status"),
        "market_price_accounting": summary.get("market_price_accounting"),
        "real_orders_blocked": summary.get("real_orders_blocked"),
        "trade_count": summary.get("trade_count", 0),
        "buy_count": summary.get("buy_count", 0),
        "sell_count": summary.get("sell_count", 0),
        "open_positions": summary.get("open_positions", 0),
        "closed_positions": summary.get("closed_positions", 0),
        "cash": summary.get("cash"),
        "equity": summary.get("equity"),
        "net_pnl": summary.get("net_pnl"),
        "total_fees": summary.get("total_fees"),
        "last_reason_ru": summary.get("last_reason_ru"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if summary.get("market_price_accounting") is not True:
        return 2
    if summary.get("real_orders_blocked") is not True:
        return 3
    if tick.get("status") not in {"ok", "wait", "blocked", "closed_position"}:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
