"""Market-backed virtual account execution for SharipovAI.

The account and orders are virtual. Quotes, fees, timestamps and PnL come from
verified public exchange data. This module never places real exchange orders.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from paper_activity_engine import (
    PaperActivityEngine as LegacyPaperActivityEngine,
    max_open_positions,
    paper_tick_seconds,
    reason_ru,
)
from sharipovai_constitution import EXECUTION_MODE, virtual_account_state
from trading_intelligence import trade_gate, verified_market_payload

SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT")
FEE_RATE = 0.001
STARTING_CASH = 10_000.0
DEFAULT_NOTIONAL = 100.0
MIN_ABS_CHANGE_PERCENT = 0.35
TAKE_PROFIT_PERCENT = 1.2
STOP_LOSS_PERCENT = 0.8
MAX_HOLD_SECONDS = 60 * 60

MarketPayloadFactory = Callable[[str], dict[str, Any]]


class MarketPaperActivityEngine(LegacyPaperActivityEngine):
    """Persistent paper account with verified market-price accounting."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        market_payload_factory: MarketPayloadFactory | None = None,
    ) -> None:
        super().__init__(path=path)
        self._market_payload_factory = market_payload_factory or verified_market_payload

    def state(self, *, catch_up: bool = False) -> dict[str, Any]:
        if catch_up:
            self.catch_up()
        state = self._load()
        self._refresh_open_positions(state)
        self._save(state)
        state["summary"] = self._summary(state)
        state["config"] = {
            "tick_seconds": paper_tick_seconds(),
            "max_open_positions": max_open_positions(),
            "mode": EXECUTION_MODE,
            "strategy": "verified_market_trend_baseline_v1",
            "market_prices": "verified_public_exchange_quotes",
            "historical_backfill": "disabled_no_fake_prices",
            "take_profit_percent": TAKE_PROFIT_PERCENT,
            "stop_loss_percent": STOP_LOSS_PERCENT,
            "max_hold_seconds": MAX_HOLD_SECONDS,
        }
        return virtual_account_state(state)

    def tick(
        self,
        *,
        force: bool = False,
        now: int | None = None,
        gate_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = int(time.time()) if now is None else int(now)
        state = self._load()
        elapsed = now - int(state.get("last_tick_at", 0) or 0)
        if not force and elapsed < paper_tick_seconds():
            state["last_reason"] = f"waiting_interval:{paper_tick_seconds() - elapsed}s_left"
            state["last_reason_ru"] = reason_ru(state["last_reason"])
            self._save(state)
            return {"status": "waiting", "state": self.state()}

        tick_count = max(
            int(state.get("tick_count", 0) or 0),
            int(state.get("skipped_count", 0) or 0),
        )
        state["tick_count"] = tick_count + 1
        state["last_tick_at"] = now

        self._refresh_open_positions(state)
        closed = self._close_triggered_position(state, now)
        if closed is not None:
            state["last_reason"] = str(closed.get("close_reason", "position_exit"))
            state["last_reason_ru"] = str(closed.get("close_reason_ru", "виртуальная позиция закрыта"))
            state["last_tick_status"] = "closed_position"
            self._save(state)
            return {"status": "closed_position", "closed_trade": closed, "state": self.state()}

        symbol = SYMBOLS[tick_count % len(SYMBOLS)]
        market = self._market_payload(symbol, gate_payload)
        gate = trade_gate(market)
        state["last_gate"] = gate

        if not bool(gate.get("market_data_verified", False)):
            return self._block(state, gate, "market_data_unavailable")
        if _critical_gate_block(gate):
            return self._block(state, gate, "trade_gate_blocked_virtual_execution")

        change = float(market.get("price_change_24h_percent", 0.0) or 0.0)
        if abs(change) < MIN_ABS_CHANGE_PERCENT:
            state["skipped_count"] = int(state.get("skipped_count", 0) or 0) + 1
            state["last_reason"] = "market_signal_too_weak"
            state["last_reason_ru"] = (
                f"движение {change:.3f}% слабее порога {MIN_ABS_CHANGE_PERCENT:.2f}% — вход пропущен"
            )
            state["last_tick_status"] = "wait_signal"
            state.setdefault("skipped_signals", []).append(
                {"time": now, "symbol": symbol, "change_24h_percent": change, "gate": gate}
            )
            state["skipped_signals"] = state["skipped_signals"][-100:]
            self._save(state)
            return {"status": "wait", "reason": state["last_reason"], "state": self.state()}

        open_trades = [trade for trade in state.get("trades", []) if trade.get("status") == "OPEN"]
        if len(open_trades) >= max_open_positions():
            oldest = sorted(open_trades, key=lambda item: int(item.get("opened_at", 0) or 0))[0]
            closed = self._close_trade(state, oldest, now, reason="max_open_position_rotation")
            if closed is None:
                return self._block(state, gate, "market_data_unavailable")
            state["last_reason"] = "max_open_position_rotation"
            state["last_reason_ru"] = "лимит позиций: закрыта самая старая по текущей рыночной цене"
            state["last_tick_status"] = "closed_position"
            self._save(state)
            return {"status": "closed_position", "closed_trade": closed, "state": self.state()}

        side = "BUY" if change > 0 else "SELL"
        trade = self._open_trade(state, now, symbol=symbol, side=side, market=market, gate=gate)
        state["last_reason"] = "opened_market_backed_virtual_trade"
        state["last_reason_ru"] = (
            f"открыта виртуальная {side} {symbol} по подтверждённой цене {trade['entry_price']}"
        )
        state["last_tick_status"] = "ok"
        self._save(state)
        return {"status": "ok", "action": "opened_virtual_trade", "trade": trade, "gate": gate, "state": self.state()}

    def catch_up(self, *, now: int | None = None, max_ticks: int | None = None) -> dict[str, Any]:
        """Run one current tick after downtime; never fabricate past prices."""

        now = int(time.time()) if now is None else int(now)
        state = self._load()
        last_tick = int(state.get("last_tick_at", 0) or 0)
        elapsed = max(0, now - last_tick) if last_tick else paper_tick_seconds()
        due = max(1, elapsed // paper_tick_seconds()) if last_tick <= 0 else elapsed // paper_tick_seconds()
        if due <= 0:
            return {"status": "ok", "catch_up_ticks": 0, "missed_intervals": 0, "due_ticks": 0}
        result = self.tick(force=True, now=now)
        state = self._load()
        state["last_reason"] = "catch_up_current_market_tick"
        state["last_reason_ru"] = (
            f"после простоя выполнен 1 текущий цикл; {int(due)} прошлых интервалов не подделывались"
        )
        self._save(state)
        return {
            "status": "ok",
            "catch_up_ticks": 1,
            "missed_intervals": int(due),
            "historical_prices_fabricated": False,
            "due_ticks": int(due),
            "last_result": result,
        }

    def _market_payload(
        self,
        symbol: str,
        supplied: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = dict(supplied or {})
        if data.get("market_quote") and data.get("price"):
            data.setdefault("market_data_verified", True)
            data.setdefault("exchange_ok", True)
        else:
            try:
                live = self._market_payload_factory(_exchange_symbol(symbol))
                data = {**live, **data}
            except Exception as exc:
                data.update(
                    {
                        "symbol": _exchange_symbol(symbol),
                        "market_data_verified": False,
                        "exchange_ok": False,
                        "market_data_error": f"{type(exc).__name__}: {exc}",
                    }
                )
        data.setdefault("ai_consensus_score", 75)
        data.setdefault("risk_per_trade_percent", 1.0)
        data.setdefault("strategy_approved", True)
        data.setdefault("live_requested", False)
        return data

    def _open_trade(
        self,
        state: dict[str, Any],
        now: int,
        *,
        symbol: str,
        side: str,
        market: dict[str, Any],
        gate: dict[str, Any],
    ) -> dict[str, Any]:
        price = _price(market)
        notional = DEFAULT_NOTIONAL
        quantity = round(notional / price, 12)
        entry_fee = round(notional * FEE_RATE, 4)
        estimated_exit_fee = entry_fee
        trade = {
            "id": f"VA-{now}-{int(state.get('tick_count', 0) or 0)}",
            "asset": symbol,
            "symbol": symbol,
            "side": side,
            "status": "OPEN",
            "notional": notional,
            "quantity": quantity,
            "entry_price": price,
            "current_price": price,
            "exit_price": None,
            "entry_fee": entry_fee,
            "exit_fee": 0.0,
            "fee": entry_fee,
            "gross_pnl": 0.0,
            "pnl_usdt": 0.0,
            "unrealized_pnl": 0.0,
            "unrealized_net_pnl": round(-entry_fee - estimated_exit_fee, 4),
            "equity_contribution": round(-estimated_exit_fee, 4),
            "net_pnl": round(-entry_fee - estimated_exit_fee, 4),
            "opened_at": now,
            "closed_at": 0,
            "signal_change_24h_percent": float(market.get("price_change_24h_percent", 0.0) or 0.0),
            "market_regime": gate.get("market_regime", {}),
            "quote_source": _quote_field(market, "source"),
            "quote_received_at": _quote_field(market, "received_at"),
            "source": "market_backed_virtual_account_engine",
            "source_ru": "виртуальный счёт с реальными рыночными котировками",
            "execution_mode": EXECUTION_MODE,
            "real_order_placed": False,
        }
        state.setdefault("trades", []).append(trade)
        state["cash"] = round(float(state.get("cash", STARTING_CASH)) - entry_fee, 4)
        state["equity"] = round(float(state["cash"]) + _open_equity_contribution(state), 4)
        return trade

    def _refresh_open_positions(self, state: dict[str, Any]) -> None:
        for trade in state.get("trades", []):
            if not isinstance(trade, dict) or trade.get("status") != "OPEN":
                continue
            market = self._market_payload(str(trade.get("symbol", trade.get("asset", "BTC/USDT"))))
            if not bool(market.get("market_data_verified", False)):
                continue
            current_price = _price(market)
            gross = _gross_pnl(trade, current_price)
            entry_fee = float(trade.get("entry_fee", trade.get("fee", 0.0)) or 0.0)
            exit_fee = round(float(trade.get("notional", DEFAULT_NOTIONAL)) * FEE_RATE, 4)
            trade["current_price"] = current_price
            trade["gross_pnl"] = gross
            trade["pnl_usdt"] = gross
            trade["unrealized_pnl"] = gross
            trade["unrealized_net_pnl"] = round(gross - entry_fee - exit_fee, 4)
            trade["equity_contribution"] = round(gross - exit_fee, 4)
            trade["net_pnl"] = trade["unrealized_net_pnl"]
            trade["last_quote_source"] = _quote_field(market, "source")
            trade["last_quote_received_at"] = _quote_field(market, "received_at")
        state["equity"] = round(float(state.get("cash", STARTING_CASH)) + _open_equity_contribution(state), 4)

    def _close_triggered_position(self, state: dict[str, Any], now: int) -> dict[str, Any] | None:
        for trade in sorted(
            [item for item in state.get("trades", []) if item.get("status") == "OPEN"],
            key=lambda item: int(item.get("opened_at", 0) or 0),
        ):
            entry = float(trade.get("entry_price", 0.0) or 0.0)
            current = float(trade.get("current_price", entry) or entry)
            if entry <= 0:
                continue
            signed_percent = (current - entry) / entry * 100.0
            if str(trade.get("side", "BUY")).upper() == "SELL":
                signed_percent = -signed_percent
            age = max(0, now - int(trade.get("opened_at", now) or now))
            if signed_percent >= TAKE_PROFIT_PERCENT:
                return self._close_trade(state, trade, now, reason="take_profit")
            if signed_percent <= -STOP_LOSS_PERCENT:
                return self._close_trade(state, trade, now, reason="stop_loss")
            if age >= MAX_HOLD_SECONDS:
                return self._close_trade(state, trade, now, reason="max_hold_time")
        return None

    def _close_trade(
        self,
        state: dict[str, Any],
        trade: dict[str, Any],
        now: int,
        *,
        reason: str,
    ) -> dict[str, Any] | None:
        market = self._market_payload(str(trade.get("symbol", trade.get("asset", "BTC/USDT"))))
        if not bool(market.get("market_data_verified", False)):
            return None
        exit_price = _price(market)
        gross = _gross_pnl(trade, exit_price)
        entry_fee = float(trade.get("entry_fee", trade.get("fee", 0.0)) or 0.0)
        exit_fee = round(float(trade.get("notional", DEFAULT_NOTIONAL)) * FEE_RATE, 4)
        net = round(gross - entry_fee - exit_fee, 4)
        trade.update(
            {
                "status": "CLOSED",
                "current_price": exit_price,
                "exit_price": exit_price,
                "gross_pnl": gross,
                "pnl_usdt": gross,
                "unrealized_pnl": 0.0,
                "unrealized_net_pnl": 0.0,
                "equity_contribution": 0.0,
                "exit_fee": exit_fee,
                "fee": round(entry_fee + exit_fee, 4),
                "net_pnl": net,
                "closed_at": now,
                "close_reason": reason,
                "close_reason_ru": _close_reason_ru(reason),
                "close_quote_source": _quote_field(market, "source"),
                "close_quote_received_at": _quote_field(market, "received_at"),
            }
        )
        state["cash"] = round(float(state.get("cash", STARTING_CASH)) + gross - exit_fee, 4)
        state["equity"] = round(float(state["cash"]) + _open_equity_contribution(state), 4)
        return trade

    def _block(self, state: dict[str, Any], gate: dict[str, Any], reason: str) -> dict[str, Any]:
        state["skipped_count"] = int(state.get("skipped_count", 0) or 0) + 1
        state["last_reason"] = reason
        state["last_reason_ru"] = reason_ru(reason)
        state["last_tick_status"] = "blocked"
        self._save(state)
        return {"status": "blocked", "reason": reason, "gate": gate, "state": self.state()}

    def _summary(self, state: dict[str, Any]) -> dict[str, Any]:
        trades = [trade for trade in state.get("trades", []) if isinstance(trade, dict)]
        open_trades = [trade for trade in trades if trade.get("status") == "OPEN"]
        closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
        profitable = [trade for trade in closed if float(trade.get("net_pnl", 0.0) or 0.0) > 0]
        losing = [trade for trade in closed if float(trade.get("net_pnl", 0.0) or 0.0) < 0]
        cash = round(float(state.get("cash", STARTING_CASH) or STARTING_CASH), 4)
        equity = round(float(state.get("equity", cash) or cash), 4)
        last_tick = int(state.get("last_tick_at", 0) or 0)
        return {
            "trade_count": len(trades),
            "buy_count": sum(str(t.get("side", "")).upper() == "BUY" for t in trades),
            "sell_count": sum(str(t.get("side", "")).upper() == "SELL" for t in trades),
            "open_positions": len(open_trades),
            "closed_positions": len(closed),
            "profitable_closed": len(profitable),
            "losing_closed": len(losing),
            "win_rate_percent": round(len(profitable) / len(closed) * 100.0, 2) if closed else 0.0,
            "skipped_count": int(state.get("skipped_count", 0) or 0),
            "net_pnl": round(sum(float(t.get("net_pnl", 0.0) or 0.0) for t in trades), 4),
            "closed_net_pnl": round(sum(float(t.get("net_pnl", 0.0) or 0.0) for t in closed), 4),
            "unrealized_net_pnl": round(sum(float(t.get("unrealized_net_pnl", 0.0) or 0.0) for t in open_trades), 4),
            "cash": cash,
            "equity": equity,
            "return_percent": round((equity - STARTING_CASH) / STARTING_CASH * 100.0, 4),
            "total_fees": round(sum(float(t.get("fee", 0.0) or 0.0) for t in trades), 4),
            "last_reason": str(state.get("last_reason", "not_started")),
            "last_reason_ru": str(state.get("last_reason_ru", "")),
            "last_tick_at": last_tick,
            "last_tick_age_seconds": max(0, int(time.time()) - last_tick) if last_tick else None,
            "last_tick_status": state.get("last_tick_status", "not_started"),
            "execution_mode": EXECUTION_MODE,
            "market_price_accounting": True,
            "real_orders_blocked": True,
        }


def _critical_gate_block(gate: dict[str, Any]) -> bool:
    if not bool(gate.get("market_data_verified", False)):
        return True
    action = str((gate.get("market_regime") or {}).get("recommended_action", "BLOCK"))
    if action == "BLOCK":
        return True
    critical = (
        "Актуальная рыночная котировка не подтверждена",
        "AI consensus ниже",
        "Достоверность новостей ниже",
        "Риск на сделку выше",
        "Exchange/API нестабилен",
    )
    return any(any(marker in str(blocker) for marker in critical) for blocker in gate.get("blockers", []))


def _gross_pnl(trade: dict[str, Any], current_price: float) -> float:
    entry = float(trade.get("entry_price", current_price) or current_price)
    quantity = float(trade.get("quantity", 0.0) or 0.0)
    if quantity <= 0:
        quantity = float(trade.get("notional", DEFAULT_NOTIONAL) or DEFAULT_NOTIONAL) / entry
    gross = (current_price - entry) * quantity
    if str(trade.get("side", "BUY")).upper() == "SELL":
        gross = -gross
    return round(gross, 4)


def _open_equity_contribution(state: dict[str, Any]) -> float:
    return round(
        sum(
            float(trade.get("equity_contribution", 0.0) or 0.0)
            for trade in state.get("trades", [])
            if isinstance(trade, dict) and trade.get("status") == "OPEN"
        ),
        4,
    )


def _price(payload: dict[str, Any]) -> float:
    quote = payload.get("market_quote") if isinstance(payload.get("market_quote"), dict) else {}
    price = float(payload.get("price", quote.get("price", 0.0)) or 0.0)
    if price <= 0:
        raise ValueError("verified market price must be positive")
    return price


def _quote_field(payload: dict[str, Any], field: str) -> str:
    quote = payload.get("market_quote") if isinstance(payload.get("market_quote"), dict) else {}
    return str(quote.get(field, ""))


def _exchange_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("/", "").replace("-", "")


def _close_reason_ru(reason: str) -> str:
    return {
        "take_profit": "фиксация виртуальной прибыли по take-profit",
        "stop_loss": "ограничение виртуального убытка по stop-loss",
        "max_hold_time": "закрытие по максимальному времени удержания",
        "max_open_position_rotation": "ротация при лимите открытых позиций",
    }.get(reason, reason)


PaperActivityEngine = MarketPaperActivityEngine
