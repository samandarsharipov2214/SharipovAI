"""Virtual account execution engine for SharipovAI.

Only the account balance and order execution are virtual. The trading organs
(news, risk, portfolio, fees, learning, evidence and audit) must behave like a
real production system. This engine never places real exchange orders.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from sharipovai_constitution import EXECUTION_MODE, virtual_account_state
from trading_intelligence import trade_gate


DEFAULT_STATE_FILE = "data/virtual_account_activity_state.json"
LEGACY_STATE_FILE = "data/paper_activity_state.json"
SYMBOL_ROTATION = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]

REASON_RU = {
    "not_started": "ещё не запускался",
    "opened_virtual_trade": "открыта виртуальная сделка",
    "opened_paper_trade": "открыта виртуальная сделка",
    "max_open_reached_closed_oldest": "достигнут лимит открытых сделок — закрыта самая старая",
    "trade_gate_blocked_virtual_execution": "Trade Gate заблокировал виртуальную сделку",
    "trade_gate_blocked_demo": "Trade Gate заблокировал виртуальную сделку",
}

SOURCE_RU = {
    "virtual_account_execution_engine": "виртуальный счёт",
    "paper_activity_engine": "виртуальный счёт",
    "paper": "виртуальный счёт",
}


def paper_state_file() -> Path:
    """Backward-compatible env name; stores virtual account execution state."""

    return Path(os.getenv("VIRTUAL_ACCOUNT_STATE_FILE", os.getenv("PAPER_ACTIVITY_STATE_FILE", DEFAULT_STATE_FILE)))


def paper_tick_seconds() -> int:
    return max(5, int(os.getenv("VIRTUAL_ACCOUNT_TICK_SECONDS", os.getenv("PAPER_ACTIVITY_TICK_SECONDS", "60")) or 60))


def max_open_positions() -> int:
    return max(1, int(os.getenv("VIRTUAL_ACCOUNT_MAX_OPEN", os.getenv("PAPER_ACTIVITY_MAX_OPEN", "5")) or 5))


def max_catch_up_ticks() -> int:
    return max(1, int(os.getenv("VIRTUAL_ACCOUNT_MAX_CATCH_UP_TICKS", os.getenv("PAPER_ACTIVITY_MAX_CATCH_UP_TICKS", "24")) or 24))


def bootstrap_ticks() -> int:
    """How many virtual ticks to create when state was empty after redeploy/sleep."""

    return max(1, int(os.getenv("VIRTUAL_ACCOUNT_BOOTSTRAP_TICKS", os.getenv("PAPER_ACTIVITY_BOOTSTRAP_TICKS", "12")) or 12))


class PaperActivityEngine:
    """Durable virtual account execution engine.

    The class name stays for backward compatibility with older imports.
    """

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
            "bootstrap_ticks": bootstrap_ticks(),
            "mode": EXECUTION_MODE,
            "catch_up_on_state": catch_up,
        }
        return virtual_account_state(state)

    def tick(self, *, force: bool = False, now: int | None = None, gate_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one virtual account execution tick."""

        now = int(time.time()) if now is None else int(now)
        state = self._load()
        elapsed = now - int(state.get("last_tick_at", 0) or 0)
        if not force and elapsed < paper_tick_seconds():
            state["last_reason"] = f"waiting_interval:{paper_tick_seconds() - elapsed}s_left"
            state["last_reason_ru"] = reason_ru(state["last_reason"])
            self._save(state)
            return {"status": "waiting", "reason": state["last_reason"], "reason_ru": state["last_reason_ru"], "state": self.state()}

        gate = trade_gate(_safe_gate_payload(gate_payload))
        if not bool(gate.get("can_trade_demo", gate.get("can_trade_virtual", False))):
            state["last_tick_at"] = now
            state["last_reason"] = "trade_gate_blocked_virtual_execution"
            state["last_reason_ru"] = reason_ru(state["last_reason"])
            state["last_gate"] = gate
            state["last_tick_status"] = "blocked"
            self._save(state)
            return {"status": "blocked", "reason": state["last_reason"], "reason_ru": state["last_reason_ru"], "gate": gate, "state": self.state()}

        open_trades = [trade for trade in state.get("trades", []) if trade.get("status") == "OPEN"]
        if len(open_trades) >= max_open_positions():
            closed = self._close_oldest_open(state, now)
            state["last_tick_at"] = now
            state["tick_count"] = int(state.get("tick_count", 0) or 0) + 1
            state["last_reason"] = "max_open_reached_closed_oldest"
            state["last_reason_ru"] = reason_ru(state["last_reason"])
            state["last_tick_status"] = "closed_position"
            state["last_gate"] = gate
            self._save(state)
            return {"status": "closed_position", "reason": state["last_reason"], "reason_ru": state["last_reason_ru"], "closed_trade": closed, "gate": gate, "state": self.state()}

        trade = self._open_trade(state, now)
        state["last_tick_at"] = now
        state["tick_count"] = int(state.get("tick_count", 0) or 0) + 1
        state["last_reason"] = "opened_virtual_trade"
        state["last_reason_ru"] = reason_ru(state["last_reason"])
        state["last_tick_status"] = "ok"
        state["last_gate"] = gate
        self._save(state)
        return {"status": "ok", "action": "opened_virtual_trade", "reason_ru": state["last_reason_ru"], "trade": trade, "gate": gate, "state": self.state()}

    def catch_up(self, *, now: int | None = None, max_ticks: int | None = None) -> dict[str, Any]:
        """Run missed virtual execution ticks after sleep/redeploy/idle time.

        If the web process was asleep or no scheduler called tick, the first
        state request can safely catch up a bounded number of virtual-only
        actions. Empty-state bootstrap is deliberately independent from the
        normal catch-up cap, because a cap of 1 caused the UI to show only one
        trade after redeploy.
        """

        now = int(time.time()) if now is None else int(now)
        limit = int(max_ticks or max_catch_up_ticks())
        state = self._load()
        last_tick = int(state.get("last_tick_at", 0) or 0)
        if last_tick <= 0:
            count = bootstrap_ticks()
            start_at = now - paper_tick_seconds() * max(0, count - 1)
            results = [self.tick(force=True, now=start_at + paper_tick_seconds() * index) for index in range(count)]
            final_state = self._load()
            final_state["last_reason"] = f"bootstrap_completed:{len(results)}_ticks"
            final_state["last_reason_ru"] = f"восстановлена история после пустого состояния: {len(results)} виртуальных циклов"
            final_state["last_tick_status"] = results[-1].get("status", "ok") if results else "ok"
            self._save(final_state)
            return {"status": "ok", "catch_up_ticks": len(results), "bootstrap": True, "bootstrap_independent_from_catch_up_cap": True, "reason_ru": final_state["last_reason_ru"], "last_result": results[-1] if results else None}
        elapsed = max(0, now - last_tick)
        due = min(limit, elapsed // paper_tick_seconds())
        results: list[dict[str, Any]] = []
        for index in range(int(due)):
            tick_at = last_tick + paper_tick_seconds() * (index + 1)
            results.append(self.tick(force=True, now=tick_at))
        if results:
            final_state = self._load()
            final_state["last_reason"] = f"catch_up_completed:{len(results)}_ticks"
            final_state["last_reason_ru"] = f"догнал пропущенные циклы: {len(results)}"
            final_state["last_tick_status"] = results[-1].get("status", "ok")
            self._save(final_state)
        return {"status": "ok", "catch_up_ticks": len(results), "reason_ru": f"догнал пропущенные циклы: {len(results)}" if results else "пропущенных циклов нет", "last_result": results[-1] if results else None, "due_ticks": int(due)}

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
            "id": f"VA-{now}-{tick_count + 1}",
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
            "source": "virtual_account_execution_engine",
            "source_ru": source_ru("virtual_account_execution_engine"),
            "execution_mode": EXECUTION_MODE,
            "real_order_placed": False,
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
        pnl = _virtual_pnl(int(state.get("tick_count", 0) or 0), str(trade.get("asset", "")))
        fee = round(float(trade.get("notional", 100.0)) * 0.001, 4)
        trade["status"] = "CLOSED"
        trade["pnl_usdt"] = pnl
        trade["fee"] = round(float(trade.get("fee", 0.0)) + fee, 4)
        trade["net_pnl"] = round(pnl - float(trade.get("fee", 0.0)), 4)
        trade["closed_at"] = now
        trade["close_reason"] = "virtual_account_mark_to_market"
        trade["close_reason_ru"] = "виртуальная переоценка и закрытие старой позиции"
        trade["source_ru"] = source_ru(str(trade.get("source", "virtual_account_execution_engine")))
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
        last_reason = str(state.get("last_reason", "not_started"))
        return {
            "trade_count": len(trades),
            "open_positions": open_count,
            "closed_positions": closed_count,
            "net_pnl": net_pnl,
            "total_fees": total_fees,
            "last_reason": last_reason,
            "last_reason_ru": str(state.get("last_reason_ru", reason_ru(last_reason))),
            "last_tick_at": last_tick,
            "last_tick_age_seconds": age,
            "last_tick_status": state.get("last_tick_status", "not_started"),
            "execution_mode": EXECUTION_MODE,
            "real_orders_blocked": True,
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            legacy = Path(LEGACY_STATE_FILE)
            if legacy.exists() and str(self.path) == DEFAULT_STATE_FILE:
                try:
                    data = json.loads(legacy.read_text(encoding="utf-8"))
                    return _migrate_state(data if isinstance(data, dict) else _default_state())
                except Exception:
                    return _default_state()
            return _default_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return _migrate_state(data if isinstance(data, dict) else _default_state())
        except Exception:
            return _default_state()

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(_migrate_state(state), ensure_ascii=False, indent=2), encoding="utf-8")


def _default_state() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "VIRTUAL_ACCOUNT",
        "execution_mode": EXECUTION_MODE,
        "cash": 10000.0,
        "equity": 10000.0,
        "trades": [],
        "tick_count": 0,
        "last_tick_at": 0,
        "last_reason": "not_started",
        "last_reason_ru": reason_ru("not_started"),
        "last_tick_status": "not_started",
        "live_execution_enabled": False,
        "real_orders_blocked": True,
    }


def reason_ru(reason: str) -> str:
    if reason.startswith("waiting_interval:"):
        seconds = reason.split(":", 1)[1].replace("s_left", "")
        return f"ждёт следующий цикл: осталось {seconds} сек"
    if reason.startswith("catch_up_completed:"):
        count = reason.split(":", 1)[1].replace("_ticks", "")
        return f"догнал пропущенные циклы: {count}"
    if reason.startswith("bootstrap_completed:"):
        count = reason.split(":", 1)[1].replace("_ticks", "")
        return f"восстановлена история после пустого состояния: {count} виртуальных циклов"
    return REASON_RU.get(reason, reason)


def source_ru(source: str) -> str:
    return SOURCE_RU.get(source, source)


def _migrate_state(state: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(state)
    migrated["mode"] = "VIRTUAL_ACCOUNT"
    migrated["execution_mode"] = EXECUTION_MODE
    migrated["real_orders_blocked"] = True
    migrated["live_execution_enabled"] = False
    if migrated.get("last_reason") == "trade_gate_blocked_demo":
        migrated["last_reason"] = "trade_gate_blocked_virtual_execution"
    if migrated.get("last_reason") == "opened_paper_trade":
        migrated["last_reason"] = "opened_virtual_trade"
    last_reason = str(migrated.get("last_reason", "not_started"))
    migrated["last_reason_ru"] = str(migrated.get("last_reason_ru") or reason_ru(last_reason))
    for trade in migrated.get("trades", []) if isinstance(migrated.get("trades"), list) else []:
        if isinstance(trade, dict):
            trade.setdefault("execution_mode", EXECUTION_MODE)
            trade.setdefault("real_order_placed", False)
            if trade.get("source") == "paper_activity_engine":
                trade["source"] = "virtual_account_execution_engine"
            trade["source_ru"] = source_ru(str(trade.get("source", "virtual_account_execution_engine")))
            if trade.get("close_reason") == "virtual_account_mark_to_market":
                trade["close_reason_ru"] = "виртуальная переоценка и закрытие старой позиции"
    return migrated


def _safe_gate_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault("ai_consensus_score", 75)
    data.setdefault("news_credibility_percent", 75)
    data.setdefault("risk_per_trade_percent", 1.0)
    data.setdefault("exchange_ok", True)
    data.setdefault("strategy_approved", True)
    data.setdefault("live_requested", False)
    return data


def _virtual_pnl(tick_count: int, symbol: str) -> float:
    base = (tick_count % 7) - 3
    symbol_factor = (sum(ord(char) for char in symbol) % 5) - 2
    return round((base + symbol_factor) * 1.75, 4)
