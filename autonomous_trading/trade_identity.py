"""Stable identities for persisted autonomous paper trades."""
from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Any, Mapping


def paper_trade_id(trade: Mapping[str, Any]) -> str:
    if not isinstance(trade, Mapping):
        raise TypeError("paper trade must be an object")
    existing = str(trade.get("trade_id") or "").strip()
    if existing:
        if not existing.startswith("paper_") or len(existing) > 64 or not existing[6:].isalnum():
            raise ValueError("paper trade_id has invalid format")
        return existing
    payload = {
        "time": _text(trade.get("time"), "time"),
        "symbol": _text(trade.get("symbol"), "symbol").upper(),
        "side": _side(trade.get("side")),
        "quantity": _positive(trade.get("quantity"), "quantity"),
        "price": _positive(trade.get("price"), "price"),
        "reason": _text(trade.get("reason"), "reason"),
        "source": _text(trade.get("source"), "source"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "paper_" + hashlib.sha256(encoded.encode()).hexdigest()[:32]


def raw_trade_fingerprint(trade: Any) -> str:
    try:
        encoded = json.dumps(trade, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)
    except Exception:
        encoded = repr(trade)
    return "invalid_" + hashlib.sha256(encoded.encode()).hexdigest()[:32]


def _text(value: Any, name: str) -> str:
    if value is None or isinstance(value, bool):
        raise ValueError(f"paper trade {name} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"paper trade {name} is required")
    return text


def _side(value: Any) -> str:
    side = _text(value, "side").upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("paper trade side is invalid")
    return side


def _positive(value: Any, name: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"paper trade {name} is invalid")
    parsed = float(value)
    if not isfinite(parsed) or parsed <= 0:
        raise ValueError(f"paper trade {name} must be positive and finite")
    return format(parsed, ".12g")
