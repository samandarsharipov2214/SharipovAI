"""Persistent demo trading state for SharipovAI Mini App.

This module stores a local paper/demo account in JSON. It is intentionally not a
real exchange integration and never touches real money. Every demo trade uses
the safe exchange preview layer, so commissions and commission-caused losses are
counted before the UI shows PnL.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from exchange_connector import SafeExchangeConnector

DEFAULT_BALANCE = 10_000.0
DEFAULT_PRICE = 50_000.0
DEFAULT_QUANTITY = 0.01


def state_file() -> Path:
    """Return demo state path."""

    return Path(os.getenv("DEMO_STATE_FILE", "data/demo_state.json"))


def exchange_connector() -> SafeExchangeConnector:
    """Return the safe exchange connector used by demo trading."""

    return SafeExchangeConnector()


def default_state() -> dict[str, Any]:
    """Return a funded default demo account."""

    now = int(time.time())
    exchange = exchange_connector()
    return {
        "mode": "DEMO",
        "currency": "USDT",
        "balance": DEFAULT_BALANCE,
        "cash": DEFAULT_BALANCE,
        "equity": DEFAULT_BALANCE,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "gross_pnl": 0.0,
        "net_pnl": 0.0,
        "total_fees": 0.0,
        "commission_drag": 0.0,
        "risk_level": "LOW",
        "decision": "WATCH",
        "confidence": 72.0,
        "last_price": DEFAULT_PRICE,
        "break_even_price": DEFAULT_PRICE,
        "updated_at": now,
        "positions": [],
        "trades": [],
        "exchange_status": exchange.status().to_dict(),
        "online_monitoring": online_monitoring_snapshot(),
        "message": "Демо-счёт готов. Реальные деньги не используются.",
    }


def online_monitoring_snapshot() -> dict[str, Any]:
    """Return online monitoring state for demo, exchange, and execution gates."""

    status = exchange_connector().status().to_dict()
    return {
        "demo_account_online": True,
        "exchange_connector_online": bool(status.get("connected")),
        "market_reading_online": bool(status.get("can_read_market")),
        "order_preview_online": bool(status.get("can_preview_orders")),
        "live_execution_enabled": bool(status.get("can_execute_orders")),
        "real_orders_blocked": not bool(status.get("can_execute_orders")),
        "mode": status.get("mode", "disabled"),
        "message": status.get("message", "Safe exchange monitoring active."),
    }


def load_state() -> dict[str, Any]:
    """Load demo state from disk, falling back to a funded account."""

    path = state_file()
    if not path.exists():
        return default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_state()
    if not isinstance(data, dict):
        return default_state()
    merged = default_state()
    merged.update(data)
    merged["positions"] = data.get("positions") if isinstance(data.get("positions"), list) else []
    merged["trades"] = data.get("trades") if isinstance(data.get("trades"), list) else []
    return recalculate_state(merged)


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    """Persist demo state and return a recalculated copy."""

    clean = recalculate_state(state)
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean


def reset_state(balance: float = DEFAULT_BALANCE) -> dict[str, Any]:
    """Reset demo account to a selected virtual balance."""

    balance = _positive_float(balance, DEFAULT_BALANCE)
    state = default_state()
    state["balance"] = balance
    state["cash"] = balance
    state["equity"] = balance
    state["message"] = f"Демо-баланс установлен: {balance:.2f} USDT."
    return save_state(state)


def set_balance(balance: float) -> dict[str, Any]:
    """Set virtual demo balance and clear positions for consistency."""

    return reset_state(balance)


def run_ai_command(command: str) -> dict[str, Any]:
    """Run a simple deterministic AI command against the demo account."""

    text = command.strip().lower()
    state = load_state()
    if any(word in text for word in ("сброс", "reset", "очист")):
        state = reset_state(float(state.get("balance", DEFAULT_BALANCE)))
        return {"reply": "Демо-счёт сброшен. Баланс снова доступен для тестов.", "state": state}
    if any(word in text for word in ("баланс", "поставь", "установи", "измени сумму", "поменяй сумму")):
        amount = _extract_amount(text)
        if amount is not None:
            state = set_balance(amount)
            return {"reply": f"Готово. Демо-баланс установлен на {amount:.2f} USDT.", "state": state}
        return {"reply": "Напиши сумму, например: «поставь баланс 20000». Это изменит только демо-счёт.", "state": state}
    if any(word in text for word in ("монитор", "онлайн", "боты", "состояние", "биржа")):
        return {"reply": monitoring_reply(state), "state": public_state()}
    if any(word in text for word in ("продай", "sell", "закрой", "зафикс")):
        state, reply = sell_demo_position(state)
        return {"reply": reply, "state": state}
    if any(word in text for word in ("купи", "buy", "покуп", "открой")):
        state, reply = buy_demo_position(state)
        return {"reply": reply, "state": state}
    if any(word in text for word in ("портфель", "pnl", "позици", "деньги", "сумма")):
        return {"reply": portfolio_reply(state), "state": public_state()}
    if any(word in text for word in ("риск", "опас", "лимит", "просад")):
        return {"reply": risk_reply(state), "state": public_state()}
    if any(word in text for word in ("анализ", "рынок", "btc", "битко")):
        state, reply = analyze_demo_market(state)
        return {"reply": reply, "state": state}
    return {"reply": portfolio_reply(state), "state": public_state()}


def analyze_demo_market(state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Refresh deterministic market analysis and optionally buy safely."""

    state = recalculate_state(state)
    cash = float(state.get("cash", 0.0))
    preview = exchange_connector().preview_order(
        symbol="BTCUSDT",
        side="BUY",
        quantity=DEFAULT_QUANTITY,
        price=float(state.get("last_price", DEFAULT_PRICE)),
    )
    if cash >= float(preview.total_cost) and not state.get("positions"):
        state, reply = buy_demo_position(state)
        return state, "AI проанализировал рынок, проверил комиссию через биржевой preview и открыл виртуальную BTC позицию. " + reply
    state["decision"] = "WATCH"
    state["confidence"] = 76.0
    state["message"] = "AI проанализировал рынок и биржевой preview. Сейчас безопаснее наблюдать или уже есть открытая позиция."
    return save_state(state), state["message"]


def buy_demo_position(state: dict[str, Any], symbol: str = "BTCUSDT") -> tuple[dict[str, Any], str]:
    """Open or add a virtual BTC position with exchange-preview commission math."""

    state = recalculate_state(state)
    price = float(state.get("last_price", DEFAULT_PRICE))
    quantity = DEFAULT_QUANTITY
    preview = exchange_connector().preview_order(symbol=symbol, side="BUY", quantity=quantity, price=price)
    total_cost = float(preview.total_cost)
    cash = float(state.get("cash", 0.0))
    if total_cost > cash:
        state["decision"] = "WATCH"
        state["message"] = "Недостаточно демо-кэша для виртуальной покупки с учётом комиссии. Увеличь демо-баланс или продай позицию."
        return save_state(state), state["message"]

    positions = list(state.get("positions", []))
    existing = next((item for item in positions if item.get("symbol") == symbol), None)
    if existing:
        old_qty = float(existing.get("quantity", 0.0))
        old_entry = float(existing.get("entry_price", price))
        new_qty = old_qty + quantity
        existing["entry_price"] = ((old_qty * old_entry) + preview.notional) / new_qty
        existing["quantity"] = new_qty
        existing["current_price"] = price
        existing["entry_fee"] = float(existing.get("entry_fee", 0.0)) + float(preview.entry_fee)
        existing["break_even_price"] = float(preview.break_even_price)
    else:
        positions.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "entry_price": price,
                "current_price": price,
                "entry_fee": float(preview.entry_fee),
                "break_even_price": float(preview.break_even_price),
            }
        )
    state["positions"] = positions
    state["cash"] = cash - total_cost
    state["total_fees"] = float(state.get("total_fees", 0.0)) + float(preview.entry_fee)
    state["commission_drag"] = float(state.get("commission_drag", 0.0)) + float(preview.entry_fee)
    state["break_even_price"] = float(preview.break_even_price)
    trade = _trade_from_preview(preview=preview, side="BUY", pnl=0.0, status="OPEN")
    state.setdefault("trades", []).append(trade)
    state["decision"] = "BUY"
    state["confidence"] = 82.0
    state["message"] = (
        f"AI купил виртуально {quantity:.4f} BTC по {price:.2f} USDT. "
        f"Комиссия входа {float(preview.entry_fee):.2f} USDT учтена как расход. "
        f"Безубыток после комиссии: {float(preview.break_even_price):.2f} USDT."
    )
    return save_state(state), state["message"]


def sell_demo_position(state: dict[str, Any], symbol: str = "BTCUSDT") -> tuple[dict[str, Any], str]:
    """Close a virtual position with exchange-preview net PnL after commissions."""

    state = recalculate_state(state)
    positions = list(state.get("positions", []))
    position = next((item for item in positions if item.get("symbol") == symbol), None)
    if not position:
        state["decision"] = "WATCH"
        state["message"] = "Открытой BTC позиции нет. Нечего продавать в демо-счёте."
        return save_state(state), state["message"]

    price = float(state.get("last_price", DEFAULT_PRICE))
    quantity = float(position.get("quantity", 0.0))
    entry = float(position.get("entry_price", price))
    entry_fee = float(position.get("entry_fee", 0.0))
    preview = exchange_connector().preview_order(
        symbol=symbol,
        side="BUY",
        quantity=quantity,
        price=entry,
        expected_exit_price=price,
    )
    exit_fee = float(preview.expected_exit_fee)
    gross_pnl = float(preview.gross_result or 0.0)
    net_pnl = gross_pnl - entry_fee - exit_fee
    notional = quantity * price
    state["cash"] = float(state.get("cash", 0.0)) + notional - exit_fee
    state["realized_pnl"] = float(state.get("realized_pnl", 0.0)) + net_pnl
    state["gross_pnl"] = float(state.get("gross_pnl", 0.0)) + gross_pnl
    state["net_pnl"] = float(state.get("net_pnl", 0.0)) + net_pnl
    state["total_fees"] = float(state.get("total_fees", 0.0)) + exit_fee
    state["commission_drag"] = float(state.get("commission_drag", 0.0)) + exit_fee
    state["positions"] = [item for item in positions if item is not position]
    state.setdefault("trades", []).append(
        _trade(
            symbol=symbol,
            side="SELL",
            quantity=quantity,
            price=price,
            fee=exit_fee,
            pnl=net_pnl,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            status="CLOSED",
            break_even_price=float(preview.break_even_price),
            warning=str(preview.warning),
        )
    )
    state["decision"] = "SELL"
    state["confidence"] = 78.0
    state["message"] = (
        f"AI закрыл виртуальную BTC позицию. Gross PnL: {gross_pnl:.2f} USDT, "
        f"комиссии: {entry_fee + exit_fee:.2f} USDT, net PnL после комиссий: {net_pnl:.2f} USDT."
    )
    return save_state(state), state["message"]


def recalculate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Recalculate equity, unrealized PnL, fees, and online monitoring."""

    positions = list(state.get("positions", []))
    last_price = float(state.get("last_price", DEFAULT_PRICE) or DEFAULT_PRICE)
    unrealized_gross = 0.0
    unrealized_net = 0.0
    positions_value = 0.0
    for position in positions:
        quantity = float(position.get("quantity", 0.0))
        entry = float(position.get("entry_price", last_price))
        current = float(position.get("current_price", last_price) or last_price)
        entry_fee = float(position.get("entry_fee", 0.0))
        position["current_price"] = current
        positions_value += quantity * current
        gross = (current - entry) * quantity
        exit_preview = exchange_connector().preview_order(
            symbol=str(position.get("symbol", "BTCUSDT")),
            side="BUY",
            quantity=quantity,
            price=entry,
            expected_exit_price=current,
        )
        exit_fee = float(exit_preview.expected_exit_fee)
        position["gross_pnl"] = gross
        position["estimated_exit_fee"] = exit_fee
        position["net_pnl_after_fees"] = gross - entry_fee - exit_fee
        position["break_even_price"] = float(exit_preview.break_even_price)
        unrealized_gross += gross
        unrealized_net += gross - entry_fee - exit_fee
    state["positions"] = positions
    state["unrealized_pnl"] = unrealized_net
    state["gross_pnl"] = float(state.get("realized_gross_pnl", state.get("gross_pnl", 0.0))) + unrealized_gross
    state["net_pnl"] = float(state.get("realized_pnl", 0.0)) + unrealized_net
    state["equity"] = float(state.get("cash", DEFAULT_BALANCE)) + positions_value
    state["exchange_status"] = exchange_connector().status().to_dict()
    state["online_monitoring"] = online_monitoring_snapshot()
    state["updated_at"] = int(time.time())
    return state


def portfolio_reply(state: dict[str, Any]) -> str:
    """Return portfolio summary."""

    state = recalculate_state(state)
    return (
        f"💼 Демо-портфель:\n"
        f"Баланс/equity: {float(state['equity']):.2f} USDT\n"
        f"Кэш: {float(state['cash']):.2f} USDT\n"
        f"Net PnL после комиссий: {float(state['net_pnl']):.2f} USDT\n"
        f"Комиссии всего: {float(state['total_fees']):.2f} USDT\n"
        f"Потери от комиссий: {float(state['commission_drag']):.2f} USDT\n"
        f"Открытых позиций: {len(state.get('positions', []))}"
    )


def risk_reply(state: dict[str, Any]) -> str:
    """Return risk summary."""

    state = recalculate_state(state)
    exposure = 0.0
    equity = max(float(state.get("equity", 0.0)), 1.0)
    for position in state.get("positions", []):
        exposure += float(position.get("quantity", 0.0)) * float(position.get("current_price", DEFAULT_PRICE))
    exposure_percent = exposure / equity * 100
    level = "LOW" if exposure_percent < 25 else "MEDIUM" if exposure_percent < 50 else "HIGH"
    state["risk_level"] = level
    save_state(state)
    return f"⚠️ Риск: {level}. Экспозиция: {exposure_percent:.1f}% от demo equity. Реальные ордера заблокированы."


def monitoring_reply(state: dict[str, Any]) -> str:
    """Return online monitoring summary."""

    state = recalculate_state(state)
    monitor = state.get("online_monitoring", {})
    exchange = state.get("exchange_status", {})
    return (
        "🟢 Онлайн-мониторинг:\n"
        f"Демо-счёт: {'онлайн' if monitor.get('demo_account_online') else 'оффлайн'}\n"
        f"Биржевой connector: {'онлайн' if monitor.get('exchange_connector_online') else 'ограничен'}\n"
        f"Preview ордеров: {'онлайн' if monitor.get('order_preview_online') else 'недоступен'}\n"
        f"Live-исполнение: {'включено' if monitor.get('live_execution_enabled') else 'выключено'}\n"
        f"Режим биржи: {exchange.get('mode', 'disabled')}\n"
        "Реальные ордера остаются заблокированы."
    )


def public_state() -> dict[str, Any]:
    """Return current state with computed summary."""

    state = save_state(load_state())
    pnl = float(state.get("realized_pnl", 0.0)) + float(state.get("unrealized_pnl", 0.0))
    return {**state, "pnl": pnl, "open_positions": len(state.get("positions", []))}


def _trade_from_preview(*, preview: Any, side: str, pnl: float, status: str) -> dict[str, Any]:
    return _trade(
        symbol=str(preview.symbol),
        side=side,
        quantity=float(preview.quantity),
        price=float(preview.price),
        fee=float(preview.entry_fee if side == "BUY" else preview.expected_exit_fee),
        pnl=pnl,
        gross_pnl=float(preview.gross_result or 0.0),
        net_pnl=float(preview.net_result_after_fees or pnl),
        status=status,
        break_even_price=float(preview.break_even_price),
        warning=str(preview.warning),
    )


def _trade(
    *,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    fee: float,
    pnl: float,
    gross_pnl: float = 0.0,
    net_pnl: float = 0.0,
    status: str | None = None,
    break_even_price: float | None = None,
    warning: str = "",
) -> dict[str, Any]:
    return {
        "id": f"{symbol}-{int(time.time())}",
        "symbol": symbol,
        "asset": symbol.replace("USDT", "/USDT"),
        "side": side,
        "quantity": quantity,
        "price": price,
        "fee": fee,
        "pnl_usdt": pnl,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "status": status or ("OPEN" if side == "BUY" else "CLOSED"),
        "break_even_price": break_even_price,
        "warning": warning,
        "created_at": int(time.time()),
    }


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _extract_amount(text: str) -> float | None:
    for raw in text.replace(",", ".").split():
        cleaned = "".join(ch for ch in raw if ch.isdigit() or ch == ".")
        if not cleaned:
            continue
        try:
            amount = float(cleaned)
        except ValueError:
            continue
        if amount > 0:
            return amount
    return None
