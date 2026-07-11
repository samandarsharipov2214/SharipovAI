"""Autonomous paper-trading loop driven only by verified streamed prices."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .market_stream import MarketStream


class AutonomousPaperLoop:
    def __init__(self, stream: MarketStream) -> None:
        self.stream = stream
        self.state_file = Path(os.getenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json"))
        self.tick_seconds = max(float(os.getenv("AUTONOMOUS_PAPER_TICK_SECONDS", "5")), 1.0)
        self.initial_cash = float(os.getenv("AUTONOMOUS_PAPER_INITIAL_CASH", "10000"))
        self.fee_rate = max(float(os.getenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001")), 0.0)
        self.max_position_percent = min(max(float(os.getenv("AUTONOMOUS_PAPER_MAX_POSITION_PERCENT", "10")), 0.1), 25.0)
        self.stop_loss_percent = min(max(float(os.getenv("AUTONOMOUS_PAPER_STOP_LOSS_PERCENT", "1.5")), 0.2), 10.0)
        self.take_profit_percent = min(max(float(os.getenv("AUTONOMOUS_PAPER_TAKE_PROFIT_PERCENT", "3.0")), 0.3), 20.0)
        self.entry_change_percent = float(os.getenv("AUTONOMOUS_PAPER_ENTRY_CHANGE_PERCENT", "0.8"))
        self.exit_change_percent = float(os.getenv("AUTONOMOUS_PAPER_EXIT_CHANGE_PERCENT", "-0.4"))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
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
            state = json.loads(json.dumps(self._state))
        state["market_stream"] = {k: market.get(k) for k in ("status", "connected", "verified", "age_seconds", "last_error")}
        state["real_execution_enabled"] = False
        return state

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
                    entry = float(position["entry_price"])
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
        cash = float(self._state["cash"])
        budget = min(cash * self.max_position_percent / 100, cash / max(len(self.stream.symbols), 1))
        fee = budget * self.fee_rate
        if budget <= fee or cash < budget + fee:
            return
        quantity = budget / price
        self._state["cash"] = cash - budget - fee
        self._state["positions"][symbol] = {
            "quantity": quantity,
            "entry_price": price,
            "opened_at": self._now(),
            "entry_fee": fee,
            "reason": reason,
        }
        self._state["total_fees"] += fee
        self._trade(symbol, "BUY", quantity, price, fee, reason, None)

    def _close(self, symbol: str, price: float, reason: str) -> None:
        position = self._state["positions"].pop(symbol)
        quantity = float(position["quantity"])
        proceeds = quantity * price
        fee = proceeds * self.fee_rate
        gross = (price - float(position["entry_price"])) * quantity
        net = gross - float(position["entry_fee"]) - fee
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
        self._state["trades"].append({
            "time": self._now(),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "fee": fee,
            "net_pnl": net_pnl,
            "reason": reason,
            "source": "bybit_websocket",
            "verified_market_data": True,
        })
        self._state["trades"] = self._state["trades"][-500:]
        self._event(side, reason, symbol)

    def _event(self, action: str, reason: str, symbol: str | None = None) -> None:
        with self._lock:
            self._state["events"].append({
                "time": self._now(),
                "action": action,
                "symbol": symbol,
                "reason": reason,
            })
            self._state["events"] = self._state["events"][-1000:]
            self._state["last_action"] = action
            self._state["last_reason"] = reason
            self._state["updated_at"] = self._now()
            self._persist()

    def _mark_to_market(self, market: dict[str, Any]) -> None:
        positions_value = 0.0
        unrealized = 0.0
        quotes = market.get("quotes", {}) if isinstance(market, dict) else {}
        for symbol, position in self._state["positions"].items():
            quote = quotes.get(symbol)
            current = float(quote["price"]) if quote and float(quote.get("price", 0)) > 0 else float(position["entry_price"])
            quantity = float(position["quantity"])
            positions_value += current * quantity
            unrealized += (current - float(position["entry_price"])) * quantity
        self._state["unrealized_pnl"] = round(unrealized, 8)
        self._state["equity"] = round(float(self._state["cash"]) + positions_value, 8)
        self._state["updated_at"] = self._now()

    def _run(self) -> None:
        while not self._stop.wait(self.tick_seconds):
            try:
                self.tick()
            except Exception as exc:
                try:
                    self._event("ERROR", f"{type(exc).__name__}: {exc}")
                except Exception:
                    # A transient Windows sharing violation must not terminate the daemon loop.
                    continue

    def _load(self) -> dict[str, Any]:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "cash" in data and "positions" in data:
                    return data
            except Exception:
                pass
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
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._state, ensure_ascii=False, indent=2)
        temp = self.state_file.with_name(
            f".{self.state_file.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
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
