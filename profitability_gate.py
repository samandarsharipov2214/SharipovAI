"""Profitability gate for SharipovAI virtual account execution.

The virtual account must not create trades just because a timer tick happened.
Before every virtual entry, this gate checks whether the expected edge is large
enough to pay fees and risk. If not, the tick becomes WAIT and no new position
is opened.
"""

from __future__ import annotations

import os
from typing import Any


DEFAULT_MIN_EXPECTED_NET_USDT = 0.35
DEFAULT_MIN_EDGE_TO_FEE_RATIO = 2.5
DEFAULT_MIN_CONFIDENCE = 72
DEFAULT_MAX_NEGATIVE_STREAK = 3


def min_expected_net_usdt() -> float:
    return float(os.getenv("VIRTUAL_MIN_EXPECTED_NET_USDT", str(DEFAULT_MIN_EXPECTED_NET_USDT)) or DEFAULT_MIN_EXPECTED_NET_USDT)


def min_edge_to_fee_ratio() -> float:
    return float(os.getenv("VIRTUAL_MIN_EDGE_TO_FEE_RATIO", str(DEFAULT_MIN_EDGE_TO_FEE_RATIO)) or DEFAULT_MIN_EDGE_TO_FEE_RATIO)


def min_confidence() -> int:
    return int(os.getenv("VIRTUAL_MIN_CONFIDENCE", str(DEFAULT_MIN_CONFIDENCE)) or DEFAULT_MIN_CONFIDENCE)


def max_negative_streak() -> int:
    return int(os.getenv("VIRTUAL_MAX_NEGATIVE_STREAK", str(DEFAULT_MAX_NEGATIVE_STREAK)) or DEFAULT_MAX_NEGATIVE_STREAK)


def evaluate_profitability_candidate(
    *,
    symbol: str,
    side: str,
    tick_count: int,
    notional: float,
    estimated_fee: float,
    state: dict[str, Any],
    gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ALLOW or WAIT for a virtual trade candidate."""

    gate = gate or {}
    confidence = int(gate.get("confidence", gate.get("ai_consensus_score", 75)) or 75)
    expected_gross = _expected_gross_edge(symbol=symbol, side=side, tick_count=tick_count, confidence=confidence)
    expected_net = round(expected_gross - estimated_fee * 2, 4)
    edge_to_fee = round(expected_gross / max(estimated_fee * 2, 0.0001), 4)
    negative_streak = _negative_streak(state)
    blockers: list[str] = []
    warnings: list[str] = []

    if confidence < min_confidence():
        blockers.append(f"confidence {confidence}% ниже минимума {min_confidence()}%")
    if expected_net < min_expected_net_usdt():
        blockers.append(f"ожидаемая чистая прибыль {expected_net:.2f} USDT ниже минимума {min_expected_net_usdt():.2f} USDT")
    if edge_to_fee < min_edge_to_fee_ratio():
        blockers.append(f"преимущество к комиссии {edge_to_fee:.2f}x ниже минимума {min_edge_to_fee_ratio():.2f}x")
    if negative_streak >= max_negative_streak():
        blockers.append(f"серия минусовых сделок {negative_streak}; нужен режим ожидания")
    if _open_count(state) >= int(gate.get("max_open_positions", 999) or 999):
        warnings.append("лимит открытых позиций близко")

    decision = "WAIT" if blockers else "ALLOW"
    return {
        "status": "ok",
        "decision": decision,
        "symbol": symbol,
        "side": side,
        "confidence": confidence,
        "estimated_gross_edge_usdt": round(expected_gross, 4),
        "estimated_fee_roundtrip_usdt": round(estimated_fee * 2, 4),
        "expected_net_usdt": expected_net,
        "edge_to_fee_ratio": edge_to_fee,
        "negative_streak": negative_streak,
        "blockers": blockers,
        "warnings": warnings,
        "reason_ru": _reason_ru(decision, blockers, expected_net, edge_to_fee),
    }


def _expected_gross_edge(*, symbol: str, side: str, tick_count: int, confidence: int) -> float:
    """Deterministic virtual edge model.

    This is not market prediction. It gives the simulator a stricter entry
    filter so it can avoid obvious fee-only churn until real signal models are
    wired in.
    """

    symbol_score = ((sum(ord(ch) for ch in symbol) + tick_count * 17) % 11) - 3
    side_boost = 1.0 if side.upper() == "BUY" else 0.35
    confidence_boost = max(0, confidence - 70) * 0.04
    return round(max(0.0, symbol_score * 0.18 + side_boost + confidence_boost), 4)


def _negative_streak(state: dict[str, Any]) -> int:
    streak = 0
    for trade in reversed(list(state.get("trades", []))):
        if trade.get("status") != "CLOSED":
            continue
        if float(trade.get("net_pnl", 0.0) or 0.0) < 0:
            streak += 1
        else:
            break
    return streak


def _open_count(state: dict[str, Any]) -> int:
    return len([trade for trade in state.get("trades", []) if trade.get("status") == "OPEN"])


def _reason_ru(decision: str, blockers: list[str], expected_net: float, edge_to_fee: float) -> str:
    if decision == "ALLOW":
        return f"вход разрешён: ожидаемый чистый результат {expected_net:.2f} USDT, преимущество к комиссии {edge_to_fee:.2f}x"
    return "вход пропущен: " + "; ".join(blockers[:3])
