"""Runtime collection of Paper fills and private Testnet order evidence."""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from autonomous_trading.trade_identity import scope_for_path
from exchange_connector.bybit_order_state import BybitOrderStateStore
from storage import ProjectDatabase, list_json_items

from .fill_divergence import (
    FillDivergenceAnalyzer,
    FillValidationRepository,
)

_STATE_NAMESPACE = "runtime_fill_harvester_state"


class RuntimeFillHarvester:
    """Build immutable divergence evidence from canonical runtime state."""

    def __init__(
        self,
        *,
        database: ProjectDatabase | None = None,
        private_orders: BybitOrderStateStore | None = None,
        analyzer: FillDivergenceAnalyzer | None = None,
        repository: FillValidationRepository | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        paper_file = Path(
            os.getenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json")
        )
        bridge_file = Path(
            os.getenv("TESTNET_BRIDGE_STATE_FILE", "data/testnet_bridge.json")
        )
        self.paper_namespace = f"paper_trades:{scope_for_path(paper_file)}"
        self.bridge_namespace = f"testnet_bridge_records:{scope_for_path(bridge_file)}"
        self.private_orders = private_orders or BybitOrderStateStore(
            database=self.database,
            environment="testnet",
        )
        self.analyzer = analyzer or FillDivergenceAnalyzer()
        self.repository = repository or FillValidationRepository(self.database)
        self.interval = min(
            max(_finite_env("FILL_HARVEST_INTERVAL_SECONDS", 15.0), 5.0),
            300.0,
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_result: dict[str, Any] = {
            "status": "not_run",
            "matched_count": 0,
            "report_id": "",
            "error": "",
        }

    def enabled(self) -> bool:
        return _truthy("RUNTIME_FILL_HARVESTER_ENABLED")

    def start(self) -> None:
        if not self.enabled():
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="runtime-fill-harvester",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)

    def snapshot(self) -> dict[str, Any]:
        return {
            **self._last_result,
            "enabled": self.enabled(),
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "paper_namespace": self.paper_namespace,
            "bridge_namespace": self.bridge_namespace,
            "private_order_source": "ProjectDatabase/bybit_private_orders",
            "interval_seconds": self.interval,
        }

    def harvest(
        self,
        *,
        experiment_id: str,
        actor: str = "runtime-fill-harvester",
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        clean_experiment = _identifier(experiment_id, "experiment_id")
        timestamp = int(time.time() * 1000) if now_ms is None else _positive_int(now_ms, "now_ms")
        paper_rows = {
            str(item["key"]): dict(item["value"])
            for item in list_json_items(self.database, self.paper_namespace)
            if isinstance(item.get("value"), Mapping)
        }
        bridge_records = [
            dict(item["value"])
            for item in list_json_items(self.database, self.bridge_namespace)
            if isinstance(item.get("value"), Mapping)
        ]
        private_snapshot = self.private_orders.snapshot()
        private_by_link = {
            str(item.get("order_link_id") or ""): dict(item)
            for item in private_snapshot.get("managed_orders", [])
            if isinstance(item, Mapping) and str(item.get("order_link_id") or "")
        }

        paper_fills: list[dict[str, Any]] = []
        testnet_fills: list[dict[str, Any]] = []
        evidence_keys: list[str] = []
        for record in bridge_records:
            if str(record.get("status")) not in {"accepted", "unresolved"}:
                continue
            record_experiment = str(record.get("experiment_id") or "").strip()
            if record_experiment and record_experiment != clean_experiment:
                continue
            trade_id = str(record.get("paper_trade_id") or "").strip()
            link = str(record.get("order_link_id") or "").strip()
            if not trade_id or not link:
                continue
            trade = paper_rows.get(trade_id)
            if trade is None:
                continue
            requested = _positive(
                record.get("mirrored_quantity") or trade.get("quantity"),
                "mirrored quantity",
            )
            reference = _positive(
                _first(
                    record.get("trading_reference") if isinstance(record.get("trading_reference"), Mapping) else {},
                    "reference_price",
                    default=_first(trade, "price", "entry_price"),
                ),
                "paper reference price",
            )
            submitted = _timestamp_ms(
                _first(trade, "created_at_ms", "opened_at", "created_at")
            )
            paper_fee_rate = _paper_fee_rate(trade)
            paper_fills.append(
                {
                    "match_id": link,
                    "source": "paper",
                    "symbol": _first(trade, "symbol", "asset"),
                    "side": trade.get("side"),
                    "submitted_at_ms": submitted,
                    "first_fill_at_ms": submitted,
                    "completed_at_ms": submitted,
                    "requested_quantity": requested,
                    "filled_quantity": requested,
                    "reference_price": reference,
                    "average_fill_price": _positive(
                        _first(trade, "price", "entry_price", default=reference),
                        "paper fill price",
                    ),
                    "fee": requested * reference * paper_fee_rate,
                    "status": "Filled",
                }
            )
            private = private_by_link.get(link)
            if private is None:
                evidence_keys.append(f"{link}:paper-only")
                continue
            trading_reference = (
                record.get("trading_reference")
                if isinstance(record.get("trading_reference"), Mapping)
                else {}
            )
            taker_rate = _nonnegative(
                trading_reference.get("taker_fee_rate", 0.0),
                "taker fee rate",
            )
            filled = _nonnegative(private.get("cum_exec_qty"), "cum_exec_qty")
            average = _positive(
                private.get("avg_price") or reference,
                "Testnet average fill price",
            )
            created = _timestamp_ms(private.get("created_time_ms") or submitted)
            updated = _timestamp_ms(private.get("updated_time_ms") or created)
            testnet_fills.append(
                {
                    "match_id": link,
                    "source": "testnet",
                    "symbol": private.get("symbol"),
                    "side": private.get("side"),
                    "submitted_at_ms": created,
                    "first_fill_at_ms": updated if filled > 0 else created,
                    "completed_at_ms": updated,
                    "requested_quantity": _positive(private.get("qty"), "Testnet quantity"),
                    "filled_quantity": filled,
                    "reference_price": reference,
                    "average_fill_price": average,
                    "fee": filled * average * taker_rate,
                    "status": private.get("status"),
                }
            )
            evidence_keys.append(
                f"{link}:{private.get('status')}:{private.get('updated_time_ms')}:{filled}"
            )

        if not paper_fills and not testnet_fills:
            result = {
                "status": "waiting_for_shadow_fills",
                "experiment_id": clean_experiment,
                "matched_count": 0,
                "report_id": "",
                "collected_at_ms": timestamp,
            }
            self._save_state(clean_experiment, result)
            self._last_result = result
            return result

        report_id = "fillval_" + hashlib.sha256(
            json.dumps(
                {
                    "experiment_id": clean_experiment,
                    "evidence": sorted(evidence_keys),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:32]
        existing = self.repository.get(report_id)
        if existing is not None:
            result = {**existing, "status": "unchanged"}
            self._last_result = result
            return result

        report = self.analyzer.analyze(
            paper_fills,
            testnet_fills,
            report_id=report_id,
            created_at_ms=timestamp,
        )
        saved = self.repository.save(
            report,
            experiment_id=clean_experiment,
            actor=actor,
        )
        result = {**saved, "status": "saved"}
        self._save_state(clean_experiment, result)
        self._last_result = result
        return result

    def _save_state(self, experiment_id: str, payload: Mapping[str, Any]) -> None:
        current = self.database.get_json(_STATE_NAMESPACE, experiment_id)
        version = int(current["version"]) if current else 0
        self.database.put_json(
            _STATE_NAMESPACE,
            experiment_id,
            dict(payload),
            expected_version=version,
        )

    def _run(self) -> None:
        experiment_id = os.getenv("SHADOW_EXPERIMENT_ID", "").strip()
        while not self._stop.is_set():
            if experiment_id:
                try:
                    self.harvest(experiment_id=experiment_id)
                except Exception as exc:
                    self._last_result = {
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                        "experiment_id": experiment_id,
                        "updated_at_ms": int(time.time() * 1000),
                    }
            self._stop.wait(self.interval)


def _paper_fee_rate(trade: Mapping[str, Any]) -> float:
    notional = _nonnegative(trade.get("notional"), "paper notional")
    fee = _nonnegative(
        _first(trade, "entry_fee", "fee", default=0.0),
        "paper fee",
    )
    if notional > 0:
        return fee / notional
    return _nonnegative(trade.get("fee_rate", 0.001), "paper fee rate")


def _timestamp_ms(value: Any) -> int:
    parsed = int(float(value))
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed * 1000 if parsed < 10_000_000_000 else parsed


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return default


def _positive(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return parsed


def _nonnegative(value: Any, name: str) -> float:
    parsed = float(value or 0.0)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{name} must be non-negative and finite")
    return parsed


def _positive_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"invalid {name}")
    return clean


def _truthy(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _finite_env(name: str, default: float) -> float:
    try:
        parsed = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


__all__ = ["RuntimeFillHarvester"]
