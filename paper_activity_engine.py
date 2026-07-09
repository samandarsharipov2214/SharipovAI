"""Active paper trading activity engine for SharipovAI.

This is a PAPER/SIMULATION engine only. It does not place live exchange orders.
It exists to avoid a static "3 demo trades and stop" state and to explain why
paper activity did or did not continue.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from trading_intelligence import trade_gate


DEFAULT_STATE_FILE = "data/paper_activity_state.json"
SYMBOL_ROTATION = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]


def paper_state_file() -> Path:
    return Path(os.getenv("PAPER_ACTIVITY_STATE_FILE", DEFAULT_STATE_FILE))


def paper_tick_seconds() -> int:
    return max(5, int(os.getenv("PAPER_ACTIVITY_TICK_SECONDS", "60") or 60))


def max_open_positions() -> int:
    return max(1, int(os.getenv("PAPER_ACTIVITY_MAX_OPEN", "5") or 5))


def max_catch_up_ticks() -> int:
    return max(1, int(os.getenv("PAPER_ACTIVITY_MAX_CATCH_UP_TICKS", "24") or 24))


class PaperActivityEngine:
    """Durable paper activity engine."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else paper_state_file()

    def state(self, *, catch_up: bool = False) -> dict[str, Any]:
        if catch_up:
            self.catch_up()
        state = self._load()
        state["summary"] = self._summary(state)
        state["config"] = {
            "tick_seconds": paper_tick_seconds(),
            "max_open_positions": max_open_positions(),
            "max_catch_up_ticks": max_catch_up_ticks(),
            "mode": "paper_simulation_only",
            "catch_up_on_state": catch_up,
        }
        return state

    def tick(self, *, force: bool = False, now: int | None = None, gate_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one paper activity tick."""

        now = int(time.time()) if now is None else int(now)
        state = self._load()
        elapsed = now - int(state.get("last_tick_at", 0) or 0)
        if not force and elapsed < paper_tick_seconds():
            state["last_reason"] = f"waiting_interval:{paper_tick_seconds() - elapsed}s_left"
            self._save(state)
            return {"status": "waiting", "reason": state["last_reason"], "state": self.state()}

        gate = trade_gate(_safe_gate_payload(gate_payload))
        if not bool(gate.get("can_trade_demo", False)):
            state["last_tick_at"] = now
            state["last_reason"] = "trade_gate_blocked_demo"
            state["last_gate"] = gate
            state["last_tick_status"] = "blocked"
            self._save(state)
            return {"status": "blocked", "reason": state["last_reason"], "gate": gate, "state": self.state()}

        open_trades = [trade for trade in state.get("trades", []) if trade.get("status") == "OPEN"]
        if len(open_trades) >= max_open_positions():
            closed = self._close_oldest_open(state, now)
            state["last_tick_at"] = now
            state["tick_count"] = int(state.get("tick_count", 0) or 0) + 1
            state["last_reason"] = "max_open_reached_closed_oldest"
            state["last_tick_status"] = "closed_position"
            state["last_gate"] = gate
            self._save(state)
            return {"status": "closed_position", "reason": state["last_reason"], "closed_trade": closed, "gate": gate, "state": self.state()}

        trade = self._open_trade(state, now)
        state["last_tick_at"] = now
        state["tick_count"] = int(state.get("tick_count", 0) or 0) + 1
        state["last_reason"] = "opened_paper_trade"
        state["last_tick_status"] = "ok"
        state["last_gate"] = gate
        self._save(state)
        return {"status": "ok", "action": "opened_paper_trade", "trade": trade, "gate": gate, "state": self.state()}

    def catch_up(self, *, now: int | None = None, max_ticks: int | None = None) -> dict[str, Any]:
        """Run missed paper ticks after sleep/redeploy/idle time.

        This fixes the situation where the Mini App is opened in the morning and
        still shows yesterday's three static demo trades. If the web process was
        asleep or no scheduler called tick overnight, the first state request can
        safely catch up a bounded number of PAPER-only actions.
        """

        now = int(time.time()) if now is None else int(now)
        limit = int(max_ticks or max_catch_up_ticks())
        state = self._load()
        last_tick = int(state.get("last_tick_at", 0) or 0)
        if last_tick <= 0:
            result = self.tick(force=True, now=now)
            return {"status": "ok", "catch_up_ticks": 1, "last_result": result}
        elapsed = max(0, now - last_tick)
        due = min(limit, elapsed // paper_tick_seconds())
        results: list[dict[str, Any]] = []
        for index in range(int(due)):
            tick_at = last_tick + paper_tick_seconds() * (index + 1)
            results.append(self.tick(force=True, now=tick_at))
        if results:
            final_state = self._load()
            final_state["last_reason"] = f"catch_up_completed:{len(results)}_ticks"
            final_state["last_tick_status"] = results[-1].get("status", "ok")
            self._save(final_state)
        return {"status": "ok", "catch_up_ticks": len(results), "last_result": results[-1] if results else None, "due_ticks": int(due)}

    def reset(self) -> dict[str, Any]:
        state = _default_state()
        self._save(state)
        return {"status": "ok", "state": self.state()}

    def _open_trade(self, state: dict[str, Any], now: int) -> dict[str, Any]:
        tick_count = int(state.get("tick_count", 0) or 0)
        symbol = SYMBOL_ROTATION[tick_count % len(SYMBOL_ROTATION)]
        side = "BUY" if tick_count % 3 != 2 else "SELL"
        notional = 100.0
        fee = round(notional * 0.001, 4)
        trade = {
            "id": f"PT-{now}-{tick_count + 1}",
            "asset": symbol,
            "symbol": symbol,
            "side": side,
            "status": "OPEN",
            "notional": notional,
            "fee": fee,
            "pnl_usdt": 0.0,
            "net_pnl": -fee,
            "opened_at": now,
            "closed_at": 0,
            "source": "paper_activity_engine",
        }
        trades = state.setdefault("trades", [])
        trades.append(trade)
        state["cash"] = round(float(state.get("cash", 10000.0)) - fee, 4)
        state["equity"] = round(float(state.get("equity", 10000.0)) - fee, 4)
        return trade

    def _close_oldest_open(self, state: dict[str, Any], now: int) -> dict[str, Any] | None:
        open_trades = [trade for trade in state.get("trades", []) if trade.get("status") == "OPEN"]
        if not open_trades:
            return None
        trade = sorted(open_trades, key=lambda item: int(item.get("opened_at", 0)))[0]
        pnl = _simulated_pnl(int(state.get("tick_count", 0) or 0), str(trade.get("asset", "")))
        fee = round(float(trade.get("notional", 100.0)) * 0.001, 4)
        trade["status"] = "CLOSED"
        trade["pnl_usdt"] = pnl
        trade["fee"] = round(float(trade.get("fee", 0.0)) + fee, 4)
        trade["net_pnl"] = round(pnl - float(trade.get("fee", 0.0)), 4)
        trade["closed_at"] = now
        state["cash"] = round(float(state.get("cash", 10000.0)) + trade["net_pnl"], 4)
        state["equity"] = round(float(state.get("equity", 10000.0)) + trade["net_pnl"], 4)
        return trade

    def _summary(self, state: dict[str, Any]) -> dict[str, Any]:
        trades = list(state.get("trades", []))
        open_count = len([trade for trade in trades if trade.get("status") == "OPEN"])
        closed_count = len([trade for trade in trades if trade.get("status") == "CLOSED"])
        net_pnl = round(sum(float(trade.get("net_pnl", 0.0) or 0.0) for trade in trades), 4)
        total_fees = round(sum(float(trade.get("fee", 0.0) or 0.0) for trade in trades), 4)
        last_tick = int(state.get("last_tick_at", 0) or 0)
        age = max(0, int(time.time()) - last_tick) if last_tick else None
        return {
            "trade_count": len(trades),
            "open_positions": open_count,
            "closed_positions": closed_count,
            "net_pnl": net_pnl,
            "total_fees": total_fees,
            "last_reason": state.get("last_reason", "not_started"),
            "last_tick_at": last_tick,
            "last_tick_age_seconds": age,
            "last_tick_status": state.get("last_tick_status", "not_started"),
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _default_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else _default_state()
        except Exception:
            return _default_state()

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_state() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "PAPER_SIMULATION",
        "cash": 10000.0,
        "equity": 10000.0,
        "trades": [],
        "tick_count": 0,
        "last_tick_at": 0,
        "last_reason": "not_started",
        "last_tick_status": "not_started",
        "live_execution_enabled": False,
        "real_orders_blocked": True,
    }


def _safe_gate_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault("ai_consensus_score", 75)
    data.setdefault("news_credibility_percent", 75)
    data.setdefault("risk_per_trade_percent", 1.0)
    data.setdefault("exchange_ok", True)
    data.setdefault("strategy_approved", True)
    data.setdefault("live_requested", False)
    return data


def _simulated_pnl(tick_count: int, symbol: str) -> float:
    base = (tick_count % 7) - 3
    symbol_factor = (sum(ord(char) for char in symbol) % 5) - 2
    return round((base + symbol_factor) * 1.75, 4)
