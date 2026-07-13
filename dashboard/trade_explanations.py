"""Explain virtual market operations without inventing missing market facts."""
from __future__ import annotations

from typing import Any

MIN_SIGNAL_PERCENT = 0.35


def explain_trade(trade: dict[str, Any]) -> dict[str, Any]:
    """Attach stable Russian explanations to one virtual trade record."""

    side = str(trade.get("side", "")).upper()
    symbol = str(trade.get("symbol") or trade.get("asset") or "актив")
    change = _number(trade.get("signal_change_24h_percent"))
    source = str(trade.get("quote_source") or trade.get("last_quote_source") or "публичная котировка Bybit")

    if not trade.get("entry_reason_ru"):
        if change is None:
            entry_reason = (
                f"{_action_word(side)} {symbol}: в старой записи не сохранено числовое значение сигнала; "
                "решение нельзя детализировать без выдумывания данных."
            )
        elif side == "BUY":
            entry_reason = (
                f"Покупка {symbol}: рост за 24 часа составил {change:.3f}% и превысил порог "
                f"{MIN_SIGNAL_PERCENT:.2f}%. Стратегия следования тренду открыла BUY по подтверждённой "
                f"котировке {source}."
            )
        elif side == "SELL":
            entry_reason = (
                f"Продажа {symbol}: изменение за 24 часа составило {change:.3f}% и по модулю превысило "
                f"порог {MIN_SIGNAL_PERCENT:.2f}%. Стратегия следования тренду открыла виртуальный SELL "
                f"по подтверждённой котировке {source}."
            )
        else:
            entry_reason = f"Операция {symbol}: направление сделки в записи не определено."
        trade["entry_reason_ru"] = entry_reason

    trade.setdefault("decision_model_ru", "базовая стратегия следования суточному тренду")
    trade.setdefault("decision_rule_ru", f"вход только при движении за 24 часа не слабее {MIN_SIGNAL_PERCENT:.2f}%")
    trade.setdefault(
        "decision_factors",
        {
            "change_24h_percent": change,
            "minimum_abs_change_percent": MIN_SIGNAL_PERCENT,
            "market_data_verified": True,
            "quote_source": source,
        },
    )

    close_reason = str(trade.get("close_reason_ru") or "").strip()
    status = str(trade.get("status", "")).upper()
    if status == "CLOSED":
        if not close_reason:
            close_reason = _close_reason_ru(str(trade.get("close_reason", "")))
            trade["close_reason_ru"] = close_reason
        trade["operation_explanation_ru"] = f"{trade['entry_reason_ru']} Закрытие: {close_reason}."
    else:
        trade["operation_explanation_ru"] = f"{trade['entry_reason_ru']} Позиция ещё открыта."
    return trade


def enrich_virtual_state(state: dict[str, Any]) -> dict[str, Any]:
    trades = state.get("trades", [])
    if isinstance(trades, list):
        for trade in trades:
            if isinstance(trade, dict):
                explain_trade(trade)
    return state


def enrich_tick_result(result: dict[str, Any]) -> dict[str, Any]:
    for key in ("trade", "closed_trade"):
        value = result.get(key)
        if isinstance(value, dict):
            explain_trade(value)
    nested = result.get("state")
    if isinstance(nested, dict):
        payload = nested.get("state") if isinstance(nested.get("state"), dict) else nested
        enrich_virtual_state(payload)
    return result


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _action_word(side: str) -> str:
    if side == "BUY":
        return "Покупка"
    if side == "SELL":
        return "Продажа"
    return "Операция"


def _close_reason_ru(reason: str) -> str:
    return {
        "take_profit": "достигнута цель прибыли",
        "stop_loss": "сработал лимит убытка",
        "max_hold_time": "истёк максимальный срок удержания",
        "max_open_position_rotation": "освобождено место из-за лимита открытых позиций",
    }.get(reason, "причина закрытия не была сохранена")
