"""Strict, fail-closed contract for SharipovAI trading candidates.

The contract validates data passed between AI organs. It does not place orders.
Malformed, stale, contradictory, or Mainnet candidates are reduced to BLOCK.
"""
from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

_ALLOWED_CATEGORIES = {"spot", "linear"}
_ALLOWED_SIDES = {"Buy", "Sell"}
_ALLOWED_ENVIRONMENTS = {"paper", "testnet", "mainnet"}
_ALLOWED_REGIMES = {"trend", "range", "high_volatility", "illiquid", "unknown"}
_ALLOWED_DECISIONS = {"ALLOW", "WAIT", "BLOCK"}
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{3,30}$")

_REQUIRED_FIELDS = {
    "candidate_id",
    "symbol",
    "category",
    "side",
    "environment",
    "market_timestamp_ms",
    "received_timestamp_ms",
    "reference_price",
    "data_sources",
    "market_regime",
    "signal_evidence",
    "news_evidence",
    "portfolio_snapshot_id",
    "estimated_fees",
    "estimated_slippage",
    "risk_score",
    "risk_blocks",
    "confidence",
    "consensus",
    "decision",
    "expires_at_ms",
}

_MAX_MARKET_AGE_MS = {
    "paper": 30_000,
    "testnet": 5_000,
    "mainnet": 1_000,
}
_MAX_TTL_MS = {
    "paper": 60_000,
    "testnet": 15_000,
    "mainnet": 5_000,
}
_FUTURE_CLOCK_TOLERANCE_MS = 1_000


@dataclass(frozen=True, slots=True)
class TradingCandidate:
    candidate_id: str
    symbol: str
    category: str
    side: str
    environment: str
    market_timestamp_ms: int
    received_timestamp_ms: int
    reference_price: float
    data_sources: tuple[str, ...]
    market_regime: str
    signal_evidence: tuple[str, ...]
    news_evidence: tuple[str, ...]
    portfolio_snapshot_id: str
    estimated_fees: float
    estimated_slippage: float
    risk_score: float
    risk_blocks: tuple[str, ...]
    confidence: float
    consensus: float
    decision: str
    expires_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for field in ("data_sources", "signal_evidence", "news_evidence", "risk_blocks"):
            data[field] = list(data[field])
        return data


@dataclass(frozen=True, slots=True)
class CandidateValidationResult:
    status: str
    valid: bool
    execution_allowed: bool
    declared_decision: str | None
    effective_decision: str
    errors: tuple[str, ...]
    policy_blocks: tuple[str, ...]
    warnings: tuple[str, ...]
    candidate: TradingCandidate | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "valid": self.valid,
            "execution_allowed": self.execution_allowed,
            "declared_decision": self.declared_decision,
            "effective_decision": self.effective_decision,
            "errors": list(self.errors),
            "policy_blocks": list(self.policy_blocks),
            "warnings": list(self.warnings),
            "candidate": self.candidate.to_dict() if self.candidate else None,
        }


def validate_trading_candidate(
    payload: Mapping[str, Any] | Any,
    *,
    now_ms: int | None = None,
) -> CandidateValidationResult:
    """Validate and normalize a candidate without executing it.

    Validation is strict: required fields must exist, unknown fields are rejected,
    timestamps must be fresh for the selected environment, and contradictions are
    converted to an effective ``BLOCK`` decision.
    """
    errors: list[str] = []
    policy_blocks: list[str] = []
    warnings: list[str] = []
    if not isinstance(payload, Mapping):
        return _result(errors=("payload must be an object",))

    keys = set(payload)
    missing = sorted(_REQUIRED_FIELDS - keys)
    unknown = sorted(keys - _REQUIRED_FIELDS)
    if missing:
        errors.append("missing required fields: " + ", ".join(missing))
    if unknown:
        errors.append("unknown fields: " + ", ".join(unknown))
    if errors:
        return _result(errors=tuple(errors))

    try:
        candidate = TradingCandidate(
            candidate_id=_identifier(payload["candidate_id"], "candidate_id"),
            symbol=_symbol(payload["symbol"]),
            category=_choice(payload["category"], "category", _ALLOWED_CATEGORIES, lower=True),
            side=_side(payload["side"]),
            environment=_choice(payload["environment"], "environment", _ALLOWED_ENVIRONMENTS, lower=True),
            market_timestamp_ms=_positive_int(payload["market_timestamp_ms"], "market_timestamp_ms"),
            received_timestamp_ms=_positive_int(payload["received_timestamp_ms"], "received_timestamp_ms"),
            reference_price=_finite_number(payload["reference_price"], "reference_price", minimum=0.0, strict_minimum=True),
            data_sources=_string_list(payload["data_sources"], "data_sources", allow_empty=False),
            market_regime=_choice(payload["market_regime"], "market_regime", _ALLOWED_REGIMES, lower=True),
            signal_evidence=_string_list(payload["signal_evidence"], "signal_evidence", allow_empty=False),
            news_evidence=_string_list(payload["news_evidence"], "news_evidence", allow_empty=True),
            portfolio_snapshot_id=_identifier(payload["portfolio_snapshot_id"], "portfolio_snapshot_id"),
            estimated_fees=_finite_number(payload["estimated_fees"], "estimated_fees", minimum=0.0),
            estimated_slippage=_finite_number(payload["estimated_slippage"], "estimated_slippage", minimum=0.0),
            risk_score=_finite_number(payload["risk_score"], "risk_score", minimum=0.0, maximum=100.0),
            risk_blocks=_string_list(payload["risk_blocks"], "risk_blocks", allow_empty=True),
            confidence=_finite_number(payload["confidence"], "confidence", minimum=0.0, maximum=100.0),
            consensus=_finite_number(payload["consensus"], "consensus", minimum=0.0, maximum=100.0),
            decision=_choice(payload["decision"], "decision", _ALLOWED_DECISIONS, upper=True),
            expires_at_ms=_positive_int(payload["expires_at_ms"], "expires_at_ms"),
        )
    except (TypeError, ValueError) as exc:
        return _result(errors=(str(exc),))

    current_ms = _now_ms(now_ms)
    if candidate.market_timestamp_ms > current_ms + _FUTURE_CLOCK_TOLERANCE_MS:
        errors.append("market_timestamp_ms is too far in the future")
    if candidate.received_timestamp_ms > current_ms + _FUTURE_CLOCK_TOLERANCE_MS:
        errors.append("received_timestamp_ms is too far in the future")
    if candidate.received_timestamp_ms < candidate.market_timestamp_ms:
        errors.append("received_timestamp_ms must not be earlier than market_timestamp_ms")

    market_age = current_ms - candidate.market_timestamp_ms
    if market_age > _MAX_MARKET_AGE_MS[candidate.environment]:
        errors.append(
            f"market data is stale for {candidate.environment}: "
            f"age={market_age}ms limit={_MAX_MARKET_AGE_MS[candidate.environment]}ms"
        )
    if candidate.expires_at_ms <= current_ms:
        errors.append("candidate has expired")
    if candidate.expires_at_ms < candidate.received_timestamp_ms:
        errors.append("expires_at_ms must not be earlier than received_timestamp_ms")
    ttl = candidate.expires_at_ms - candidate.received_timestamp_ms
    if ttl > _MAX_TTL_MS[candidate.environment]:
        errors.append(
            f"candidate TTL is too long for {candidate.environment}: "
            f"ttl={ttl}ms limit={_MAX_TTL_MS[candidate.environment]}ms"
        )

    if candidate.risk_blocks:
        policy_blocks.extend(candidate.risk_blocks)
    if candidate.decision == "ALLOW":
        if candidate.confidence < 70.0:
            policy_blocks.append("confidence below 70")
        if candidate.consensus < 70.0:
            policy_blocks.append("consensus below 70")
        if candidate.risk_score > 50.0:
            policy_blocks.append("risk_score above 50")
    if candidate.environment == "mainnet":
        policy_blocks.append("Mainnet execution requires a separate Security Guard approval")
    if candidate.decision != "ALLOW":
        warnings.append(f"candidate declared {candidate.decision}; execution is not requested")

    valid = not errors
    effective_decision = "BLOCK" if errors or policy_blocks else candidate.decision
    execution_allowed = valid and not policy_blocks and candidate.decision == "ALLOW"
    status = "invalid" if errors else "blocked" if policy_blocks or candidate.decision != "ALLOW" else "ok"
    return CandidateValidationResult(
        status=status,
        valid=valid,
        execution_allowed=execution_allowed,
        declared_decision=candidate.decision,
        effective_decision=effective_decision,
        errors=tuple(errors),
        policy_blocks=tuple(_deduplicate(policy_blocks)),
        warnings=tuple(warnings),
        candidate=candidate,
    )


def _result(*, errors: tuple[str, ...]) -> CandidateValidationResult:
    return CandidateValidationResult(
        status="invalid",
        valid=False,
        execution_allowed=False,
        declared_decision=None,
        effective_decision="BLOCK",
        errors=errors,
        policy_blocks=(),
        warnings=(),
        candidate=None,
    )


def _now_ms(value: int | None) -> int:
    if value is None:
        return int(time.time() * 1000)
    return _positive_int(value, "now_ms")


def _identifier(value: Any, name: str) -> str:
    text = str(value).strip()
    if not _ID_PATTERN.fullmatch(text):
        raise ValueError(f"{name} has invalid format")
    return text


def _symbol(value: Any) -> str:
    text = str(value).strip().upper().replace("/", "").replace("-", "")
    if not _SYMBOL_PATTERN.fullmatch(text):
        raise ValueError("symbol has invalid format")
    return text


def _side(value: Any) -> str:
    text = str(value).strip().title()
    if text not in _ALLOWED_SIDES:
        raise ValueError("side must be Buy or Sell")
    return text


def _choice(
    value: Any,
    name: str,
    allowed: set[str],
    *,
    lower: bool = False,
    upper: bool = False,
) -> str:
    text = str(value).strip()
    if lower:
        text = text.lower()
    if upper:
        text = text.upper()
    if text not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return text


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _finite_number(
    value: Any,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    strict_minimum: bool = False,
) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a number") from exc
    if not isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and (parsed <= minimum if strict_minimum else parsed < minimum):
        operator = "greater than" if strict_minimum else "at least"
        raise ValueError(f"{name} must be {operator} {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return parsed


def _string_list(value: Any, name: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{name} values must be strings")
        text = item.strip()
        if not text:
            raise ValueError(f"{name} must not contain empty values")
        if len(text) > 256:
            raise ValueError(f"{name} values must be at most 256 characters")
        normalized.append(text)
    normalized = _deduplicate(normalized)
    if not allow_empty and not normalized:
        raise ValueError(f"{name} must contain at least one value")
    return tuple(normalized)


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
