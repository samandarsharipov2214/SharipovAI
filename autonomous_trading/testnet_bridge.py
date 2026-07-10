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


class AutonomousTestnetBridge:
    def __init__(self, execution_client: BybitExecutionClient | None = None) -> None:
        self.paper_file = Path(os.getenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json"))
        self.state_file = Path(os.getenv("TESTNET_BRIDGE_STATE_FILE", "data/testnet_bridge.json"))
        self.interval = max(float(os.getenv("TESTNET_BRIDGE_TICK_SECONDS", "5")), 1.0)
        self.client = execution_client or BybitExecutionClient()
        self.journal = ExecutionJournal()
        self.stages = StageController()
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
        assessment = self.stages.assess().to_dict()
        return {
            **self._state,
            "enabled": _truthy("AUTONOMOUS_TESTNET_ENABLED"),
            "execution": self.client.status(),
            "stage_assessment": assessment,
            "journal": self.journal.summary(),
        }

    def tick(self) -> None:
        if not _truthy("AUTONOMOUS_TESTNET_ENABLED"):
            self._state["last_status"] = "disabled"
            self._persist()
            return
        assessment = self.stages.assess()
        if assessment.eligible_stage < 3:
            self._state["last_status"] = "blocked_by_stage_evidence"
            self._persist()
            return
        trades = self._paper_trades()
        processed = int(self._state.get("processed_trade_count", 0))
        for index, trade in enumerate(trades[processed:], start=processed):
            if trade.get("side") not in {"BUY", "SELL"}:
                continue
            try:
                result = self.client.place_market_order(
                    symbol=str(trade.get("symbol", "")),
                    side=str(trade.get("side", "")),
                    quantity=float(trade.get("quantity", 0)),
                    reference_price=float(trade.get("price", 0)),
                )
                self.journal.append({**result.to_dict(), "paper_trade_index": index, "signal_reason": trade.get("reason")})
                self._state["last_status"] = "accepted"
                self._state["last_order_id"] = result.order_id
            except Exception as exc:
                self.journal.append({
                    "status": "blocked_or_error", "mode": self.client.mode,
                    "symbol": trade.get("symbol"), "side": trade.get("side"),
                    "quantity": trade.get("quantity"), "paper_trade_index": index,
                    "message": f"{type(exc).__name__}: {exc}",
                })
                self._state["last_status"] = "blocked_or_error"
                self._state["last_error"] = f"{type(exc).__name__}: {exc}"
                break
            finally:
                self._state["processed_trade_count"] = index + 1
                self._persist()

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
        return {"processed_trade_count": 0, "last_status": "initialized", "last_error": ""}

    def _persist(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        temp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.state_file)


def _truthy(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}
