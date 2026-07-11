"""Mirror new autonomous paper trades to Bybit testnet after all gates pass.

The bridge is default-off, tracks immutable paper ``trade_id`` values in the
canonical database, and never automatically retries an ambiguous execution.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

from storage import ProjectDatabase, VersionConflict, list_json_items

from exchange_connector.bybit_execution import BybitExecutionClient

from .execution_journal import ExecutionJournal
from .stage_controller import StageController
from .trade_identity import normalize_trade, scope_for_path

_FINAL_RECORD_STATUSES = {"accepted", "unresolved", "invalid", "ignored_disabled", "ignored_stage", "ignored_non_trade"}


class AutonomousTestnetBridge:
    def __init__(
        self,
        execution_client: BybitExecutionClient | None = None,
        *,
        database: ProjectDatabase | None = None,
    ) -> None:
        self.paper_file = Path(os.getenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json"))
        self.state_file = Path(os.getenv("TESTNET_BRIDGE_STATE_FILE", "data/testnet_bridge.json"))
        self.paper_scope = scope_for_path(self.paper_file)
        self.bridge_scope = scope_for_path(self.state_file)
        self.paper_trade_namespace = f"paper_trades:{self.paper_scope}"
        self.state_namespace = "testnet_bridge_state"
        self.record_namespace = f"testnet_bridge_records:{self.bridge_scope}"
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.interval = max(_finite_env("TESTNET_BRIDGE_TICK_SECONDS", 5.0), 1.0)
        self.client = execution_client or BybitExecutionClient()
        self.journal = ExecutionJournal(database=self.database)
        self.stages = StageController(journal=self.journal)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_version = 0
        self._last_backup_error = ""
        self._state = self._load_state()
        self._migrate_legacy_paper_trades()

    def enabled(self) -> bool:
        return _truthy("AUTONOMOUS_TESTNET_BRIDGE_ENABLED") and _truthy("AUTONOMOUS_TESTNET_ENABLED")

    def start(self) -> None:
        if not _truthy("AUTONOMOUS_TESTNET_BRIDGE_ENABLED"):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="testnet-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict[str, Any]:
        records = self._records()
        unresolved = [item for item in records if item.get("status") == "unresolved"]
        return {
            **self._state,
            "enabled": self.enabled(),
            "bridge_feature_enabled": _truthy("AUTONOMOUS_TESTNET_BRIDGE_ENABLED"),
            "testnet_execution_enabled": _truthy("AUTONOMOUS_TESTNET_ENABLED"),
            "processed_trade_count": len(records),
            "unresolved_trade_count": len(unresolved),
            "unresolved_trade_ids": [item.get("paper_trade_id") for item in unresolved],
            "database_backed": True,
            "database_scope": self.bridge_scope,
            "backup_status": "error" if self._last_backup_error else "ok",
            "backup_error": self._last_backup_error,
            "execution": self.client.status(),
            "stage_assessment": self.stages.assess().to_dict(),
            "journal": self.journal.summary(),
        }

    def tick(self) -> None:
        trades = self._paper_trades()
        if not self.enabled():
            self._baseline(trades, "ignored_disabled", "disabled")
            return

        assessment = self.stages.assess()
        if assessment.eligible_stage < 3:
            self._baseline(trades, "ignored_stage", "blocked_by_stage_evidence")
            return

        for trade in trades:
            trade_id = str(trade.get("trade_id", "")).strip()
            if not trade_id:
                raise RuntimeError("paper trade has no stable trade_id")
            existing = self.database.get_json(self.record_namespace, trade_id)
            if existing is not None:
                status = str(existing["value"].get("status", ""))
                if status not in _FINAL_RECORD_STATUSES:
                    raise RuntimeError(f"unknown persisted bridge status for {trade_id}: {status}")
                continue

            if trade.get("side") not in {"BUY", "SELL"}:
                self._record(trade_id, "ignored_non_trade", trade, message="Paper record is not an executable BUY/SELL trade")
                continue

            price = _finite_number(trade.get("price"), "paper price")
            paper_quantity = _finite_number(trade.get("quantity"), "paper quantity")
            safe_quantity = min(paper_quantity, self.client.max_notional / price) if price > 0 else 0.0
            if paper_quantity <= 0 or not math.isfinite(safe_quantity) or safe_quantity <= 0:
                self.journal.append({
                    "journal_event_id": f"paper_invalid_{trade_id}",
                    "status": "blocked_or_error",
                    "mode": self.client.mode,
                    "environment": "testnet",
                    "category": "spot",
                    "symbol": trade.get("symbol"),
                    "side": trade.get("side"),
                    "quantity": safe_quantity,
                    "paper_trade_id": trade_id,
                    "message": "Invalid paper trade price or quantity",
                    "origin": "autonomous_bridge",
                })
                self._record(trade_id, "invalid", trade, message="Invalid paper trade price or quantity")
                self._set_state("skipped_invalid_trade", "Invalid paper trade price or quantity", trade_id=trade_id)
                continue

            try:
                result = self.client.place_market_order(
                    symbol=str(trade.get("symbol", "")),
                    side=str(trade.get("side", "")),
                    quantity=safe_quantity,
                    reference_price=price,
                )
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                self.journal.append({
                    "journal_event_id": f"paper_unresolved_{trade_id}",
                    "status": "unresolved",
                    "mode": self.client.mode,
                    "environment": "testnet",
                    "category": "spot",
                    "symbol": trade.get("symbol"),
                    "side": trade.get("side"),
                    "quantity": safe_quantity,
                    "paper_trade_id": trade_id,
                    "message": message,
                    "origin": "autonomous_bridge",
                    "requires_reconciliation": True,
                })
                self._record(trade_id, "unresolved", trade, message=message, mirrored_quantity=safe_quantity)
                self._set_state("unresolved", message, trade_id=trade_id)
                # Never attempt later trades after an unresolved financial action.
                break

            journal_item = self.journal.append({
                **result.to_dict(),
                "journal_event_id": f"paper_accepted_{trade_id}",
                "paper_trade_id": trade_id,
                "paper_quantity": paper_quantity,
                "mirrored_quantity": safe_quantity,
                "signal_reason": trade.get("reason"),
                "origin": "autonomous_bridge",
            })
            self._record(
                trade_id,
                "accepted",
                trade,
                message=str(result.message),
                mirrored_quantity=safe_quantity,
                order_id=result.order_id,
                journal_event_id=journal_item["journal_event_id"],
            )
            self._set_state("accepted", "", trade_id=trade_id, order_id=result.order_id)

    def _baseline(self, trades: list[dict[str, Any]], record_status: str, state_status: str) -> None:
        if not _truthy("TESTNET_REPLAY_HISTORICAL_TRADES"):
            for trade in trades:
                trade_id = str(trade.get("trade_id", "")).strip()
                if trade_id and self.database.get_json(self.record_namespace, trade_id) is None:
                    self._record(trade_id, record_status, trade, message=state_status)
        self._set_state(state_status, "")

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as exc:
                self._set_state("error", f"{type(exc).__name__}: {exc}")

    def _paper_trades(self) -> list[dict[str, Any]]:
        return [item["value"] for item in list_json_items(self.database, self.paper_trade_namespace)]

    def _records(self) -> list[dict[str, Any]]:
        return [item["value"] for item in list_json_items(self.database, self.record_namespace)]

    def _record(self, trade_id: str, status: str, trade: dict[str, Any], **details: Any) -> None:
        if status not in _FINAL_RECORD_STATUSES:
            raise ValueError("invalid bridge record status")
        record = {
            "paper_trade_id": trade_id,
            "status": status,
            "recorded_at_ms": int(time.time() * 1000),
            "symbol": trade.get("symbol"),
            "side": trade.get("side"),
            **details,
        }
        try:
            self.database.put_json(self.record_namespace, trade_id, record, expected_version=0)
        except VersionConflict:
            existing = self.database.get_json(self.record_namespace, trade_id)
            if existing is None or existing["value"] != record:
                raise RuntimeError(f"bridge record conflict for {trade_id}")

    def _load_state(self) -> dict[str, Any]:
        current = self.database.get_json(self.state_namespace, self.bridge_scope)
        if current is not None:
            self._state_version = int(current["version"])
            return self._normalize_state(current["value"])
        state: dict[str, Any] | None = None
        if self.state_file.exists():
            try:
                raw = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    state = self._normalize_state(raw)
            except Exception:
                state = None
        if state is None:
            state = self._normalize_state({})
        self._state = state
        self._save_database_state()
        return state

    def _normalize_state(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise RuntimeError("testnet bridge state must be an object")
        return {
            "last_status": str(value.get("last_status", "initialized")),
            "last_error": str(value.get("last_error", "")),
            "last_trade_id": str(value.get("last_trade_id", "")),
            "last_order_id": str(value.get("last_order_id", "")),
            "updated_at_ms": int(value.get("updated_at_ms", 0) or 0),
        }

    def _set_state(self, status: str, error: str, *, trade_id: str = "", order_id: str = "") -> None:
        self._state["last_status"] = str(status)
        self._state["last_error"] = str(error)
        if trade_id:
            self._state["last_trade_id"] = trade_id
        if order_id:
            self._state["last_order_id"] = order_id
        self._state["updated_at_ms"] = int(time.time() * 1000)
        self._persist_state()

    def _persist_state(self) -> None:
        self._save_database_state()
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp = self.state_file.with_name(f".{self.state_file.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                temp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
                os.replace(temp, self.state_file)
            finally:
                temp.unlink(missing_ok=True)
        except Exception as exc:
            self._last_backup_error = f"{type(exc).__name__}: {exc}"
        else:
            self._last_backup_error = ""

    def _save_database_state(self) -> None:
        try:
            self._state_version = self.database.put_json(
                self.state_namespace,
                self.bridge_scope,
                self._state,
                expected_version=self._state_version,
            )
        except VersionConflict as exc:
            raise RuntimeError("testnet bridge state changed concurrently; update blocked") from exc

    def _migrate_legacy_paper_trades(self) -> None:
        if list_json_items(self.database, self.paper_trade_namespace, limit=1):
            return
        if not self.paper_file.exists():
            return
        try:
            raw = json.loads(self.paper_file.read_text(encoding="utf-8"))
            trades = raw.get("trades", []) if isinstance(raw, dict) else []
        except Exception:
            return
        if not isinstance(trades, list):
            return
        for index, item in enumerate(trades):
            if not isinstance(item, dict):
                continue
            trade = normalize_trade(item, scope=self.paper_scope, index=index)
            try:
                self.database.put_json(self.paper_trade_namespace, trade["trade_id"], trade, expected_version=0)
            except VersionConflict:
                existing = self.database.get_json(self.paper_trade_namespace, trade["trade_id"])
                if existing is None or existing["value"] != trade:
                    raise RuntimeError(f"legacy paper trade conflict: {trade['trade_id']}")


def _truthy(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _finite_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _finite_number(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed
