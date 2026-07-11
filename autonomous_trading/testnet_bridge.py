"""Mirror new autonomous paper trades to Bybit testnet after all gates pass."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from exchange_connector.bybit_execution import BybitExecutionClient

from .execution_journal import ExecutionJournal
from .stage_controller import StageController
from .trade_identity import paper_trade_id, raw_trade_fingerprint


class AutonomousTestnetBridge:
    def __init__(self, execution_client: BybitExecutionClient | None = None) -> None:
        self.paper_file = Path(os.getenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json"))
        self.state_file = Path(os.getenv("TESTNET_BRIDGE_STATE_FILE", "data/testnet_bridge.json"))
        self.interval = max(float(os.getenv("TESTNET_BRIDGE_TICK_SECONDS", "5")), 1.0)
        self.client = execution_client or BybitExecutionClient()
        self.journal = ExecutionJournal()
        self.stages = StageController(journal=self.journal)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = self._load_state()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="testnet-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict[str, Any]:
        return {
            **self._state,
            "enabled": _truthy("AUTONOMOUS_TESTNET_ENABLED"),
            "execution": self.client.status(),
            "stage_assessment": self.stages.assess().to_dict(),
            "journal": self.journal.summary(),
        }

    def tick(self) -> None:
        trades = self._paper_trades()
        self._migrate_processed_ids(trades)
        if not _truthy("AUTONOMOUS_TESTNET_ENABLED"):
            self._baseline(trades, "disabled")
            return

        assessment = self.stages.assess()
        if assessment.eligible_stage < 3:
            self._baseline(trades, "blocked_by_stage_evidence")
            return

        processed = set(self._state.get("processed_trade_ids", []))
        for index, trade in enumerate(trades):
            trade_key = self._trade_key(trade)
            if trade_key in processed:
                continue
            if not isinstance(trade, dict) or trade.get("side") not in {"BUY", "SELL"}:
                self._mark_processed(trade_key)
                continue
            try:
                candidate_id = paper_trade_id(trade)
            except (TypeError, ValueError) as exc:
                self.journal.append({
                    "status": "blocked_or_error",
                    "mode": self.client.mode,
                    "paper_trade_index": index,
                    "paper_trade_id": trade_key,
                    "message": f"Invalid paper trade identity: {exc}",
                    "origin": "autonomous_bridge",
                })
                self._mark_processed(trade_key)
                continue

            price = float(trade.get("price", 0) or 0)
            paper_quantity = float(trade.get("quantity", 0) or 0)
            safe_quantity = min(paper_quantity, self.client.max_notional / price) if price > 0 else 0
            if safe_quantity <= 0:
                self.journal.append({
                    "status": "blocked_or_error",
                    "mode": self.client.mode,
                    "symbol": trade.get("symbol"),
                    "side": trade.get("side"),
                    "quantity": safe_quantity,
                    "paper_trade_index": index,
                    "paper_trade_id": candidate_id,
                    "message": "Invalid paper trade price or quantity",
                    "origin": "autonomous_bridge",
                })
                self._mark_processed(candidate_id)
                self._state["last_status"] = "skipped_invalid_trade"
                self._persist()
                continue
            try:
                result = self.client.place_market_order(
                    candidate_id=candidate_id,
                    symbol=str(trade.get("symbol", "")),
                    side=str(trade.get("side", "")),
                    quantity=safe_quantity,
                    reference_price=price,
                )
                self.journal.append({
                    **result.to_dict(),
                    "paper_trade_index": index,
                    "paper_trade_id": candidate_id,
                    "paper_quantity": paper_quantity,
                    "mirrored_quantity": safe_quantity,
                    "signal_reason": trade.get("reason"),
                    "origin": "autonomous_bridge",
                })
                self._mark_processed(candidate_id)
                self._state["last_status"] = "accepted"
                self._state["last_order_id"] = result.order_id
                self._state["last_error"] = ""
                self._persist()
            except Exception as exc:
                self.journal.append({
                    "status": "blocked_or_error",
                    "mode": self.client.mode,
                    "symbol": trade.get("symbol"),
                    "side": trade.get("side"),
                    "quantity": safe_quantity,
                    "paper_trade_index": index,
                    "paper_trade_id": candidate_id,
                    "message": f"{type(exc).__name__}: {exc}",
                    "origin": "autonomous_bridge",
                })
                self._state["last_status"] = "blocked_or_error"
                self._state["last_error"] = f"{type(exc).__name__}: {exc}"
                self._persist()
                break

    def _baseline(self, trades: list[dict[str, Any]], status: str) -> None:
        if not _truthy("TESTNET_REPLAY_HISTORICAL_TRADES"):
            for trade in trades:
                self._mark_processed(self._trade_key(trade))
        self._state["last_status"] = status
        self._persist()

    def _migrate_processed_ids(self, trades: list[dict[str, Any]]) -> None:
        if isinstance(self._state.get("processed_trade_ids"), list):
            return
        count = min(max(int(self._state.get("processed_trade_count", 0) or 0), 0), len(trades))
        self._state["processed_trade_ids"] = [self._trade_key(trade) for trade in trades[:count]]
        self._state["processed_trade_count"] = len(self._state["processed_trade_ids"])

    def _mark_processed(self, trade_id: str) -> None:
        values = [str(item) for item in self._state.get("processed_trade_ids", []) if str(item)]
        if trade_id not in values:
            values.append(trade_id)
        self._state["processed_trade_ids"] = values[-5000:]
        self._state["processed_trade_count"] = len(self._state["processed_trade_ids"])

    @staticmethod
    def _trade_key(trade: Any) -> str:
        try:
            return paper_trade_id(trade)
        except (TypeError, ValueError):
            return raw_trade_fingerprint(trade)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as exc:
                self._state["last_status"] = "error"
                self._state["last_error"] = f"{type(exc).__name__}: {exc}"
                self._persist()

    def _paper_trades(self) -> list[dict[str, Any]]:
        if not self.paper_file.exists():
            return []
        try:
            data = json.loads(self.paper_file.read_text(encoding="utf-8"))
            return list(data.get("trades", [])) if isinstance(data, dict) else []
        except Exception:
            return []

    def _load_state(self) -> dict[str, Any]:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {
            "processed_trade_count": 0,
            "processed_trade_ids": [],
            "last_status": "initialized",
            "last_error": "",
        }

    def _persist(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        temp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.state_file)


def _truthy(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}
