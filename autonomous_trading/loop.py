"""Autonomous paper-trading loop driven only by verified streamed prices.

The canonical ProjectDatabase is the source of truth. The JSON file remains a
bounded UI/operator backup; immutable trade and event history is never truncated
from the database.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from storage import ProjectDatabase, VersionConflict, list_json_items

from .market_stream import MarketStream
from .trade_identity import new_event_id, new_trade_id, normalize_event, normalize_trade, scope_for_path


class AutonomousPaperLoop:
    def __init__(self, stream: MarketStream, *, database: ProjectDatabase | None = None) -> None:
        self.stream = stream
        self.state_file = Path(os.getenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json"))
        self.scope = scope_for_path(self.state_file)
        self.state_namespace = "autonomous_paper_state"
        self.trade_namespace = f"paper_trades:{self.scope}"
        self.event_namespace = f"paper_events:{self.scope}"
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.tick_seconds = max(_finite_env("AUTONOMOUS_PAPER_TICK_SECONDS", 5.0), 1.0)
        self.initial_cash = _positive_env("AUTONOMOUS_PAPER_INITIAL_CASH", 10_000.0)
        self.fee_rate = min(max(_finite_env("EXCHANGE_DEFAULT_FEE_RATE", 0.001), 0.0), 0.05)
        self.max_position_percent = min(max(_finite_env("AUTONOMOUS_PAPER_MAX_POSITION_PERCENT", 10.0), 0.1), 25.0)
        self.stop_loss_percent = min(max(_finite_env("AUTONOMOUS_PAPER_STOP_LOSS_PERCENT", 1.5), 0.2), 10.0)
        self.take_profit_percent = min(max(_finite_env("AUTONOMOUS_PAPER_TAKE_PROFIT_PERCENT", 3.0), 0.3), 20.0)
        self.entry_change_percent = _finite_env("AUTONOMOUS_PAPER_ENTRY_CHANGE_PERCENT", 0.8)
        self.exit_change_percent = _finite_env("AUTONOMOUS_PAPER_EXIT_CHANGE_PERCENT", -0.4)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._db_version = 0
        self._last_backup_error = ""
        self._state = self._load()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="autonomous-paper-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict[str, Any]:
        market = self.stream.snapshot()
        with self._lock:
            self._mark_to_market(market)
            state = json.loads(json.dumps(self._state, ensure_ascii=False, allow_nan=False))
        state["market_stream"] = {
            key: market.get(key)
            for key in ("status", "connected", "verified", "age_seconds", "last_error")
        }
        state["real_execution_enabled"] = False
        state["database_backed"] = True
        state["database_scope"] = self.scope
        state["trade_history_count"] = len(list_json_items(self.database, self.trade_namespace))
        state["event_history_count"] = len(list_json_items(self.database, self.event_namespace))
        state["backup_status"] = "error" if self._last_backup_error else "ok"
        state["backup_error"] = self._last_backup_error
        return state

    def trade_history(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return [item["value"] for item in list_json_items(self.database, self.trade_namespace, limit=limit)]

    def event_history(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return [item["value"] for item in list_json_items(self.database, self.event_namespace, limit=limit)]

    def tick(self) -> None:
        market = self.stream.snapshot()
        if not market.get("verified"):
            self._event("BLOCK", "Market stream is unavailable or stale; no paper order created")
            return
        with self._lock:
            for symbol in self.stream.symbols:
                try:
                    quote = self.stream.quote(symbol)
                except RuntimeError as exc:
                    self._event("BLOCK", str(exc), symbol)
                    continue
                change = quote.change_24h_percent
                if change is None:
                    continue
                position = self._state["positions"].get(symbol)
                if position:
                    entry = _positive(position["entry_price"], "entry_price")
                    move = (quote.price - entry) / entry * 100
                    if move <= -self.stop_loss_percent:
                        self._close(symbol, quote.price, "stop_loss")
                    elif move >= self.take_profit_percent:
                        self._close(symbol, quote.price, "take_profit")
                    elif change <= self.exit_change_percent:
                        self._close(symbol, quote.price, "momentum_exit")
                elif change >= self.entry_change_percent:
                    self._open(symbol, quote.price, "positive_24h_momentum")
            self._mark_to_market(market)
            self._persist()

    def _open(self, symbol: str, price: float, reason: str) -> None:
        price = _positive(price, "price")
        cash = _nonnegative(self._state["cash"], "cash")
        budget = min(cash * self.max_position_percent / 100, cash / max(len(self.stream.symbols), 1))
        fee = budget * self.fee_rate
        if budget <= fee or cash < budget + fee:
            return
        quantity = budget / price
        opened_at = self._now()
        self._state["cash"] = cash - budget - fee
        self._state["positions"][symbol] = {
            "quantity": quantity,
            "entry_price": price,
            "opened_at": opened_at,
            "entry_fee": fee,
            "reason": reason,
        }
        self._state["total_fees"] += fee
        self._trade(symbol, "BUY", quantity, price, fee, reason, None)

    def _close(self, symbol: str, price: float, reason: str) -> None:
        price = _positive(price, "price")
        position = self._state["positions"].pop(symbol)
        quantity = _positive(position["quantity"], "position quantity")
        proceeds = quantity * price
        fee = proceeds * self.fee_rate
        gross = (price - _positive(position["entry_price"], "entry_price")) * quantity
        net = gross - _nonnegative(position["entry_fee"], "entry_fee") - fee
        self._state["cash"] += proceeds - fee
        self._state["realized_pnl"] += net
        self._state["total_fees"] += fee
        self._trade(symbol, "SELL", quantity, price, fee, reason, net)

    def _trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee: float,
        reason: str,
        net_pnl: float | None,
    ) -> None:
        now = self._now()
        item = {
            "trade_id": new_trade_id(),
            "created_at_ms": self._now_ms(),
            "time": now,
            "symbol": str(symbol).strip().upper(),
            "side": side,
            "quantity": _positive(quantity, "quantity"),
            "price": _positive(price, "price"),
            "fee": _nonnegative(fee, "fee"),
            "net_pnl": None if net_pnl is None else _finite(net_pnl, "net_pnl"),
            "reason": str(reason),
            "source": "bybit_websocket",
            "verified_market_data": True,
        }
        self._state["trades"].append(item)
        self._state["trades"] = self._state["trades"][-500:]
        self._event(side, reason, symbol)

    def _event(self, action: str, reason: str, symbol: str | None = None) -> None:
        with self._lock:
            item = {
                "event_id": new_event_id(),
                "created_at_ms": self._now_ms(),
                "time": self._now(),
                "action": str(action),
                "symbol": str(symbol).strip().upper() if symbol else None,
                "reason": str(reason),
            }
            self._state["events"].append(item)
            self._state["events"] = self._state["events"][-1000:]
            self._state["last_action"] = str(action)
            self._state["last_reason"] = str(reason)
            self._state["updated_at"] = self._now()
            self._persist()

    def _mark_to_market(self, market: dict[str, Any]) -> None:
        positions_value = 0.0
        unrealized = 0.0
        quotes = market.get("quotes", {}) if isinstance(market, dict) else {}
        for symbol, position in self._state["positions"].items():
            quote = quotes.get(symbol)
            current = (
                _positive(quote["price"], "quote price")
                if quote and _finite(quote.get("price", 0), "quote price") > 0
                else _positive(position["entry_price"], "entry_price")
            )
            quantity = _positive(position["quantity"], "position quantity")
            positions_value += current * quantity
            unrealized += (current - _positive(position["entry_price"], "entry_price")) * quantity
        self._state["unrealized_pnl"] = round(unrealized, 8)
        self._state["equity"] = round(_nonnegative(self._state["cash"], "cash") + positions_value, 8)
        self._state["updated_at"] = self._now()

    def _run(self) -> None:
        while not self._stop.wait(self.tick_seconds):
            try:
                self.tick()
            except Exception as exc:
                try:
                    self._event("ERROR", f"{type(exc).__name__}: {exc}")
                except Exception:
                    continue

    def _load(self) -> dict[str, Any]:
        current = self.database.get_json(self.state_namespace, self.scope)
        if current is not None:
            self._db_version = int(current["version"])
            state = self._normalize_state(current["value"])
            self._state = state
            self._sync_immutable_history()
            if state != current["value"]:
                self._save_database_state()
            return state

        state = None
        if self.state_file.exists():
            try:
                raw = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    state = self._normalize_state(raw)
            except Exception:
                state = None
        if state is None:
            state = self._default_state()
        self._state = state
        self._save_database_state()
        self._sync_immutable_history()
        return state

    def _normalize_state(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise RuntimeError("paper account state must be an object")
        state = dict(raw)
        state["mode"] = "autonomous_paper"
        state["cash"] = _nonnegative(state.get("cash", self.initial_cash), "cash")
        state["equity"] = _nonnegative(state.get("equity", state["cash"]), "equity")
        state["realized_pnl"] = _finite(state.get("realized_pnl", 0), "realized_pnl")
        state["unrealized_pnl"] = _finite(state.get("unrealized_pnl", 0), "unrealized_pnl")
        state["total_fees"] = _nonnegative(state.get("total_fees", 0), "total_fees")
        positions = state.get("positions", {})
        if not isinstance(positions, dict):
            raise RuntimeError("paper positions must be an object")
        normalized_positions: dict[str, dict[str, Any]] = {}
        for symbol, position in positions.items():
            if not isinstance(position, dict):
                raise RuntimeError("paper position must be an object")
            clean_symbol = str(symbol).strip().upper()
            if not clean_symbol or not clean_symbol.isalnum():
                raise RuntimeError("paper position symbol is invalid")
            normalized_positions[clean_symbol] = {
                **position,
                "quantity": _positive(position.get("quantity"), "position quantity"),
                "entry_price": _positive(position.get("entry_price"), "entry_price"),
                "entry_fee": _nonnegative(position.get("entry_fee", 0), "entry_fee"),
            }
        state["positions"] = normalized_positions
        trades = state.get("trades", [])
        events = state.get("events", [])
        if not isinstance(trades, list) or not all(isinstance(item, dict) for item in trades):
            raise RuntimeError("paper trades must be a list of objects")
        if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
            raise RuntimeError("paper events must be a list of objects")
        state["trades"] = [normalize_trade(item, scope=self.scope, index=index) for index, item in enumerate(trades)][-500:]
        state["events"] = [normalize_event(item, scope=self.scope, index=index) for index, item in enumerate(events)][-1000:]
        state["last_action"] = str(state.get("last_action", "START"))
        state["last_reason"] = str(state.get("last_reason", "Autonomous paper account initialized"))
        state["updated_at"] = str(state.get("updated_at") or self._now())
        return state

    def _default_state(self) -> dict[str, Any]:
        return {
            "mode": "autonomous_paper",
            "cash": self.initial_cash,
            "equity": self.initial_cash,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_fees": 0.0,
            "positions": {},
            "trades": [],
            "events": [],
            "last_action": "START",
            "last_reason": "Autonomous paper account initialized",
            "updated_at": self._now(),
        }

    def _persist(self) -> None:
        self._save_database_state()
        self._sync_immutable_history()
        try:
            self._write_json_backup()
        except Exception as exc:
            self._last_backup_error = f"{type(exc).__name__}: {exc}"
        else:
            self._last_backup_error = ""

    def _save_database_state(self) -> None:
        try:
            version = self.database.put_json(
                self.state_namespace,
                self.scope,
                self._state,
                expected_version=self._db_version,
            )
        except VersionConflict as exc:
            raise RuntimeError("paper account state changed concurrently; update blocked") from exc
        self._db_version = version

    def _sync_immutable_history(self) -> None:
        for trade in self._state.get("trades", []):
            self._put_immutable(self.trade_namespace, str(trade["trade_id"]), trade)
        for event in self._state.get("events", []):
            self._put_immutable(self.event_namespace, str(event["event_id"]), event)

    def _put_immutable(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        try:
            self.database.put_json(namespace, key, value, expected_version=0)
        except VersionConflict:
            existing = self.database.get_json(namespace, key)
            if existing is None or existing["value"] != value:
                raise RuntimeError(f"immutable paper record conflict: {namespace}/{key}")

    def _write_json_backup(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._state, ensure_ascii=False, indent=2, allow_nan=False)
        temp = self.state_file.with_name(f".{self.state_file.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(8):
                try:
                    os.replace(temp, self.state_file)
                    return
                except PermissionError:
                    if attempt == 7:
                        raise
                    time.sleep(min(0.025 * (2**attempt), 0.25))
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)


def _finite(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _positive(value: Any, name: str) -> float:
    parsed = _finite(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _nonnegative(value: Any, name: str) -> float:
    parsed = _finite(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must not be negative")
    return parsed


def _finite_env(name: str, default: float) -> float:
    try:
        return _finite(os.getenv(name, str(default)), name)
    except (TypeError, ValueError):
        return default


def _positive_env(name: str, default: float) -> float:
    value = _finite_env(name, default)
    return value if value > 0 else default
