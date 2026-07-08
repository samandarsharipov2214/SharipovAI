"""Persistent demo trading state for SharipovAI Mini App.

This module stores a local paper/demo account in JSON. It is intentionally not a
real exchange integration and never touches real money.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_BALANCE = 10_000.0
DEFAULT_PRICE = 50_000.0
DEFAULT_FEE_RATE = 0.001


def state_file() -> Path:
    """Return demo state path."""

    return Path(os.getenv("DEMO_STATE_FILE", "data/demo_state.json"))


def default_state() -> dict[str, Any]:
    """Return a funded default demo account."""

    now = int(time.time())
    return {
        "mode": "DEMO",
        "currency": "USDT",
        "balance": DEFAULT_BALANCE,
        "cash": DEFAULT_BALANCE,
        "equity": DEFAULT_BALANCE,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_fees": 0.0,
        "risk_level": "LOW",
        "decision": "WATCH",
        "confidence": 72.0,
        "last_price": DEFAULT_PRICE,
        "updated_at": now,
        "positions": [],
        "trades": [],
        "message": "Демо-счёт готов. Реальные деньги не используются.",
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
    if any(word in text for word in ("продай", "sell", "закрой", "зафикс")):
        state, reply = sell_demo_position(state)
        return {"reply": reply, "state": state}
    if any(word in text for word in ("купи", "buy", "покуп", "открой")):
        state, reply = buy_demo_position(state)
        return {"reply": reply, "state": state}
    if any(word in text for word in ("портфель", "pnl", "позици", "деньги", "сумма")):
        return {"reply": portfolio_reply(state), "state": state}
    if any(word in text for word in ("риск", "опас", "лимит", "просад")):
        return {"reply": risk_reply(state), "state": state}
    if any(word in text for word in ("анализ", "рынок", "btc", "битко")):
        state, reply = analyze_demo_market(state)
        return {"reply": reply, "state": state}
    return {"reply": portfolio_reply(state), "state": state}


def analyze_demo_market(state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Refresh deterministic market analysis and optionally buy safely."""

    state = recalculate_state(state)
    cash = float(state.get("cash", 0.0))
    if cash >= DEFAULT_PRICE * 0.01 * (1 + DEFAULT_FEE_RATE) and not state.get("positions"):
        state, reply = buy_demo_position(state)
        return state, "AI проанализировал рынок и открыл виртуальную BTC позицию. " + reply
    state["decision"] = "WATCH"
    state["confidence"] = 76.0
    state["message"] = "AI проанализировал рынок. Сейчас безопаснее наблюдать или уже есть открытая позиция."
    return save_state(state), state["message"]


def buy_demo_position(state: dict[str, Any], symbol: str = "BTCUSDT") -> tuple[dict[str, Any], str]:
    """Open or add a virtual BTC position."""

    state = recalculate_state(state)
    price = float(state.get("last_price", DEFAULT_PRICE))
    quantity = 0.01
    notional = quantity * price
    fee = notional * DEFAULT_FEE_RATE
    total_cost = notional + fee
    cash = float(state.get("cash", 0.0))
    if total_cost > cash:
        state["decision"] = "WATCH"
        state["message"] = "Недостаточно демо-кэша для виртуальной покупки. Увеличь demo balance или продай позицию."
        return save_state(state), state["message"]

    positions = list(state.get("positions", []))
    existing = next((item for item in positions if item.get("symbol") == symbol), None)
    if existing:
        old_qty = float(existing.get("quantity", 0.0))
        old_entry = float(existing.get("entry_price", price))
        new_qty = old_qty + quantity
        existing["entry_price"] = ((old_qty * old_entry) + notional) / new_qty
        existing["quantity"] = new_qty
        existing["current_price"] = price
    else:
        positions.append({"symbol": symbol, "quantity": quantity, "entry_price": price, "current_price": price})
    state["positions"] = positions
    state["cash"] = cash - total_cost
    state["total_fees"] = float(state.get("total_fees", 0.0)) + fee
    trade = _trade(symbol=symbol, side="BUY", quantity=quantity, price=price, fee=fee, pnl=0.0)
    state.setdefault("trades", []).append(trade)
    state["decision"] = "BUY"
    state["confidence"] = 82.0
    state["message"] = f"AI купил виртуально {quantity:.4f} BTC по {price:.2f} USDT. Комиссия {fee:.2f} USDT учтена как расход."
    return save_state(state), state["message"]


def sell_demo_position(state: dict[str, Any], symbol: str = "BTCUSDT") -> tuple[dict[str, Any], str]:
    """Close a virtual position."""

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
    notional = quantity * price
    fee = notional * DEFAULT_FEE_RATE
    gross_pnl = (price - entry) * quantity
    net_pnl = gross_pnl - fee
    state["cash"] = float(state.get("cash", 0.0)) + notional - fee
    state["realized_pnl"] = float(state.get("realized_pnl", 0.0)) + net_pnl
    state["total_fees"] = float(state.get("total_fees", 0.0)) + fee
    state["positions"] = [item for item in positions if item is not position]
    state.setdefault("trades", []).append(_trade(symbol=symbol, side="SELL", quantity=quantity, price=price, fee=fee, pnl=net_pnl))
    state["decision"] = "SELL"
    state["confidence"] = 78.0
    state["message"] = f"AI закрыл виртуальную BTC позицию. PnL после комиссии: {net_pnl:.2f} USDT."
    return save_state(state), state["message"]


def recalculate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Recalculate equity and unrealized PnL."""

    positions = list(state.get("positions", []))
    last_price = float(state.get("last_price", DEFAULT_PRICE) or DEFAULT_PRICE)
    unrealized = 0.0
    positions_value = 0.0
    for position in positions:
        quantity = float(position.get("quantity", 0.0))
        entry = float(position.get("entry_price", last_price))
        current = float(position.get("current_price", last_price) or last_price)
        position["current_price"] = current
        positions_value += quantity * current
        unrealized += (current - entry) * quantity
    state["positions"] = positions
    state["unrealized_pnl"] = unrealized
    state["equity"] = float(state.get("cash", DEFAULT_BALANCE)) + positions_value
    state["updated_at"] = int(time.time())
    return state


def portfolio_reply(state: dict[str, Any]) -> str:
    """Return portfolio summary."""

    state = recalculate_state(state)
    return (
        f"💼 Демо-портфель:\n"
        f"Баланс/equity: {float(state['equity']):.2f} USDT\n"
        f"Кэш: {float(state['cash']):.2f} USDT\n"
        f"PnL: {float(state['realized_pnl']) + float(state['unrealized_pnl']):.2f} USDT\n"
        f"Комиссии: {float(state['total_fees']):.2f} USDT\n"
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


def public_state() -> dict[str, Any]:
    """Return current state with computed summary."""

    state = save_state(load_state())
    pnl = float(state.get("realized_pnl", 0.0)) + float(state.get("unrealized_pnl", 0.0))
    return {**state, "pnl": pnl, "open_positions": len(state.get("positions", []))}


def _trade(*, symbol: str, side: str, quantity: float, price: float, fee: float, pnl: float) -> dict[str, Any]:
    return {
        "id": f"{symbol}-{int(time.time())}",
        "symbol": symbol,
        "asset": symbol.replace("USDT", "/USDT"),
        "side": side,
        "quantity": quantity,
        "price": price,
        "fee": fee,
        "pnl_usdt": pnl,
        "status": "OPEN" if side == "BUY" else "CLOSED",
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
