"""Autonomous paper-trading loop driven only by verified streamed prices.

The canonical ProjectDatabase is the source of truth. The JSON file remains a
bounded UI/operator backup; immutable trade and event history is never truncated
from the database. Read-only snapshots never mutate account state and never
materialize full history just to count it.
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

from storage import ProjectDatabase, VersionConflict, count_json_items, list_json_items

from .market_stream import MarketStream
from .trade_identity import (
    default_paper_state_file,
    new_event_id,
    new_trade_id,
    normalize_event,
    normalize_trade,
    scope_for_path,
)

SNAPSHOT_TRADE_WINDOW = 20
SNAPSHOT_EVENT_WINDOW = 20


class AutonomousPaperLoop:
    def __init__(self, stream: MarketStream, *, database: ProjectDatabase | None = None) -> None:
        self.stream = stream
        self.state_file = default_paper_state_file()
        self.scope = scope_for_path(self.state_file)
        self.state_namespace = "autonomous_paper_state"
        self.trade_namespace = f"paper_trades:{self.scope}"
        self.event_namespace = f"paper_events:{self.scope}"
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.tick_seconds = max(_finite_env("AUTONOMOUS_PAPER_TICK_SECONDS", 5.0), 1.0)
        self.wait_event_min_interval_seconds = max(
            _finite_env("AUTONOMOUS_PAPER_WAIT_EVENT_MIN_INTERVAL_SECONDS", 300.0),
            30.0,
        )
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
        # Immutable history is reconciled once after startup; subsequent writes
        # only need to append new IDs rather than re-check the bounded UI cache.
        self._synced_trade_ids: set[str] = set()
        self._synced_event_ids: set[str] = set()
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
        """Return a read-only marked-to-market copy of the canonical state.

        Cabinet/status polls stay O(1) memory with respect to history length:
        counts use SQL COUNT, and trades/events are a bounded presentation window.
        """
        market = self.stream.snapshot()
        with self._lock:
            payload = dict(self._state)
            payload["trades"] = bound_snapshot_history(self._state.get("trades"), SNAPSHOT_TRADE_WINDOW)
            payload["events"] = bound_snapshot_history(self._state.get("events"), SNAPSHOT_EVENT_WINDOW)
            state = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
            self._mark_state_to_market(state, market, update_timestamp=False)
        state["market_stream"] = {
            key: market.get(key)
            for key in ("status", "connected", "verified", "age_seconds", "last_error")
        }
        state["real_execution_enabled"] = False
        state["database_backed"] = True
        state["database_scope"] = self.scope
        state["trade_history_count"] = self.trade_history_count()
        state["event_history_count"] = self.event_history_count()
        state["backup_status"] = "error" if self._last_backup_error else "ok"
        state["backup_error"] = self._last_backup_error
        state["worker_running"] = bool(self._thread and self._thread.is_alive())
        state["source_of_truth"] = "autonomous_paper"
        state["legacy_virtual_account_deprecated"] = True
        state["mutation_on_read"] = False
        state["wait_event_min_interval_seconds"] = self.wait_event_min_interval_seconds
        return state

    def trade_history_count(self) -> int:
        return count_json_items(self.database, self.trade_namespace)

    def event_history_count(self) -> int:
        return count_json_items(self.database, self.event_namespace)

    def trade_history(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self._read_history(self.trade_namespace, limit=limit)

    def event_history(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self._read_history(self.event_namespace, limit=limit)

    def _read_history(self, namespace: str, *, limit: int | None) -> list[dict[str, Any]]:
        if limit is None:
            rows = list_json_items(self.database, namespace)
            return [item["value"] for item in rows]
        bounded = max(1, int(limit))
        rows = list_json_items(self.database, namespace, limit=bounded, newest_first=True)
        return [item["value"] for item in reversed(rows)]

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
            clean_action = str(action)
            clean_reason = str(reason)
            clean_symbol = str(symbol).strip().upper() if symbol else None
            created_at_ms = self._now_ms()
            if clean_action == "WAIT" and self._suppress_wait_event(
                clean_reason,
                clean_symbol,
                created_at_ms=created_at_ms,
            ):
                self._state["last_action"] = clean_action
                self._state["last_reason"] = clean_reason
                self._state["updated_at"] = self._now()
                return
            item = {
                "event_id": new_event_id(),
                "created_at_ms": created_at_ms,
                "time": self._now(),
                "action": clean_action,
                "symbol": clean_symbol,
                "reason": clean_reason,
            }
            self._state["events"].append(item)
            self._state["events"] = self._state["events"][-1000:]
            self._state["last_action"] = clean_action
            self._state["last_reason"] = clean_reason
            self._state["updated_at"] = self._now()
            self._persist()

    def _suppress_wait_event(
        self,
        reason: str,
        symbol: str | None,
        *,
        created_at_ms: int,
    ) -> bool:
        signature = f"{symbol or '*'}|{reason}"
        last_by_signature = self._state.setdefault("wait_event_last_emitted_ms", {})
        if not isinstance(last_by_signature, dict):
            last_by_signature = {}
            self._state["wait_event_last_emitted_ms"] = last_by_signature
        last = int(last_by_signature.get(signature, 0) or 0)
        minimum_ms = int(self.wait_event_min_interval_seconds * 1000)
        if last > 0 and created_at_ms - last < minimum_ms:
            self._state["suppressed_wait_events"] = int(
                self._state.get("suppressed_wait_events", 0) or 0
            ) + 1
            return True
        last_by_signature[signature] = created_at_ms
        if len(last_by_signature) > 200:
            newest = sorted(last_by_signature.items(), key=lambda item: int(item[1]), reverse=True)[:200]
            self._state["wait_event_last_emitted_ms"] = dict(newest)
        return False

    def _mark_to_market(self, market: dict[str, Any]) -> None:
        self._mark_state_to_market(self._state, market, update_timestamp=True)

    def _mark_state_to_market(
        self,
        state: dict[str, Any],
        market: dict[str, Any],
        *,
        update_timestamp: bool,
    ) -> None:
        positions_value = 0.0
        unrealized = 0.0
        quotes = market.get("quotes", {}) if isinstance(market, dict) else {}
        for symbol, position in state["positions"].items():
            quote = quotes.get(symbol)
            current = (
                _positive(quote["price"], "quote price")
                if quote and _finite(quote.get("price", 0), "quote price") > 0
                else _positive(position["entry_price"], "entry_price")
            )
            quantity = _positive(position["quantity"], "position quantity")
            positions_value += current * quantity
            unrealized += (current - _positive(position["entry_price"], "entry_price")) * quantity
        state["unrealized_pnl"] = round(unrealized, 8)
        state["equity"] = round(_nonnegative(state["cash"], "cash") + positions_value, 8)
        if update_timestamp:
            state["updated_at"] = self._now()

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
        raw_wait_index = state.get("wait_event_last_emitted_ms", {})
        state["wait_event_last_emitted_ms"] = {
            str(key): max(0, int(value or 0))
            for key, value in raw_wait_index.items()
        } if isinstance(raw_wait_index, dict) else {}
        state["suppressed_wait_events"] = max(
            0,
            int(state.get("suppressed_wait_events", 0) or 0),
        )
        state["last_close_by_symbol"] = _normalize_last_close_by_symbol(
            state.get("last_close_by_symbol")
        )
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
            "wait_event_last_emitted_ms": {},
            "suppressed_wait_events": 0,
            "last_action": "START",
            "last_reason": "Autonomous paper account initialized",
            "updated_at": self._now(),
            "last_close_by_symbol": {},
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
            trade_id = str(trade["trade_id"])
            if trade_id not in self._synced_trade_ids:
                self._put_immutable(self.trade_namespace, trade_id, trade)
                self._synced_trade_ids.add(trade_id)
        for event in self._state.get("events", []):
            event_id = str(event["event_id"])
            if event_id not in self._synced_event_ids:
                self._put_immutable(self.event_namespace, event_id, event)
                self._synced_event_ids.add(event_id)

    def _put_immutable(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        canonical = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
        try:
            self.database.put_json(namespace, key, canonical, expected_version=0)
        except VersionConflict:
            existing = self.database.get_json(namespace, key)
            if existing is None or existing["value"] != canonical:
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


def bound_snapshot_history(items: Any, limit: int) -> list[Any]:
    """Return the newest `limit` items without copying unbounded history."""
    if not isinstance(items, list) or limit <= 0:
        return []
    return list(items[-limit:])


def _normalize_last_close_by_symbol(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for symbol, row in raw.items():
        if not isinstance(row, dict):
            continue
        clean_symbol = str(symbol).strip().upper()
        if not clean_symbol or not clean_symbol.isalnum():
            continue
        try:
            closed_at_ms = max(0, int(row.get("closed_at_ms") or 0))
            close_price = float(row.get("close_price") or 0.0)
            fees = float(row.get("fees") or 0.0)
            spread_cost = float(row.get("spread_cost") or 0.0)
            slippage_cost = float(row.get("slippage_cost") or 0.0)
            quantity = float(row.get("quantity") or 0.0)
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (close_price, fees, spread_cost, slippage_cost, quantity)):
            continue
        normalized[clean_symbol] = {
            "closed_at_ms": closed_at_ms,
            "close_price": close_price,
            "decision_id": str(row.get("decision_id") or ""),
            "candidate_id": str(row.get("candidate_id") or ""),
            "fees": max(0.0, fees),
            "spread_cost": max(0.0, spread_cost),
            "slippage_cost": max(0.0, slippage_cost),
            "side": str(row.get("side") or "SELL").upper() or "SELL",
            "trade_id": str(row.get("trade_id") or ""),
            "quantity": max(0.0, quantity),
        }
    return normalized


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
