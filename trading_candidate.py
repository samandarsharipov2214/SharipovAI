"""Canonical fail-closed contract for SharipovAI trading candidates."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Any, Iterable, Mapping


class TradingCategory(StrEnum):
    SPOT = "spot"
    LINEAR = "linear"


class TradingSide(StrEnum):
    BUY = "Buy"
    SELL = "Sell"


class TradingEnvironment(StrEnum):
    PAPER = "paper"
    TESTNET = "testnet"
    MAINNET = "mainnet"


class MarketRegime(StrEnum):
    TREND = "trend"
    RANGE = "range"
    HIGH_VOLATILITY = "high_volatility"
    ILLIQUID = "illiquid"
    UNKNOWN = "unknown"


class TradingDecision(StrEnum):
    ALLOW = "ALLOW"
    WAIT = "WAIT"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class TradingCandidate:
    candidate_id: str
    symbol: str
    category: TradingCategory
    side: TradingSide
    environment: TradingEnvironment
    market_timestamp_ms: int
    received_timestamp_ms: int
    reference_price: float
    data_sources: tuple[str, ...]
    market_regime: MarketRegime
    signal_evidence: tuple[str, ...]
    news_evidence: tuple[str, ...]
    portfolio_snapshot_id: str
    estimated_fees: float
    estimated_slippage: float
    risk_score: float
    risk_blocks: tuple[str, ...]
    confidence: float
    consensus: float
    decision: TradingDecision
    expires_at_ms: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for name in ("category", "side", "environment", "market_regime", "decision"):
            payload[name] = getattr(self, name).value
        return payload


@dataclass(frozen=True, slots=True)
class CandidateValidation:
    valid: bool
    decision: TradingDecision
    errors: tuple[str, ...]


def validate_trading_candidate(
    candidate: TradingCandidate,
    *,
    now_ms: int,
    max_market_age_ms: int = 2_500,
    max_candidate_ttl_ms: int = 30_000,
    min_confidence: float = 70.0,
    min_consensus: float = 70.0,
) -> CandidateValidation:
    errors: list[str] = []
    _require_text(candidate.candidate_id, "candidate_id", errors)
    _require_text(candidate.portfolio_snapshot_id, "portfolio_snapshot_id", errors)
    if not candidate.symbol or candidate.symbol != candidate.symbol.upper() or not candidate.symbol.isalnum():
        errors.append("symbol must be uppercase alphanumeric")
    if candidate.market_timestamp_ms <= 0:
        errors.append("market_timestamp_ms must be positive")
    if candidate.received_timestamp_ms < candidate.market_timestamp_ms:
        errors.append("received_timestamp_ms must not precede market_timestamp_ms")
    if candidate.received_timestamp_ms > now_ms + 1_000:
        errors.append("received_timestamp_ms is in the future")
    if candidate.expires_at_ms <= now_ms:
        errors.append("candidate is expired")
    ttl_ms = candidate.expires_at_ms - now_ms
    if ttl_ms > max_candidate_ttl_ms:
        errors.append("candidate TTL exceeds safe maximum")
    if now_ms - candidate.market_timestamp_ms > max_market_age_ms:
        errors.append("market data is stale")
    _require_positive_number(candidate.reference_price, "reference_price", errors)
    _require_non_negative_number(candidate.estimated_fees, "estimated_fees", errors)
    _require_non_negative_number(candidate.estimated_slippage, "estimated_slippage", errors)
    _require_range(candidate.risk_score, "risk_score", 0.0, 100.0, errors)
    _require_range(candidate.confidence, "confidence", 0.0, 100.0, errors)
    _require_range(candidate.consensus, "consensus", 0.0, 100.0, errors)
    _require_range(min_confidence, "min_confidence", 1.0, 100.0, errors)
    _require_range(min_consensus, "min_consensus", 1.0, 100.0, errors)
    _require_non_empty_unique(candidate.data_sources, "data_sources", errors)
    _require_non_empty_unique(candidate.signal_evidence, "signal_evidence", errors)
    if candidate.confidence < min_confidence:
        errors.append("confidence is below required threshold")
    if candidate.consensus < min_consensus:
        errors.append("consensus is below required threshold")
    if candidate.risk_blocks and candidate.decision is not TradingDecision.BLOCK:
        errors.append("risk_blocks require BLOCK decision")
    if candidate.market_regime in {MarketRegime.ILLIQUID, MarketRegime.UNKNOWN} and candidate.decision is TradingDecision.ALLOW:
        errors.append("unsafe or unknown market regime cannot be ALLOW")
    if candidate.environment is TradingEnvironment.MAINNET and candidate.decision is TradingDecision.ALLOW:
        errors.append("mainnet ALLOW is disabled until external approval verification is implemented")
    if errors:
        return CandidateValidation(False, TradingDecision.BLOCK, tuple(errors))
    return CandidateValidation(True, candidate.decision, ())


def _require_text(value: str, name: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{name} is required")


def _require_positive_number(value: float, name: str, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or value <= 0:
        errors.append(f"{name} must be a positive finite number")


def _require_non_negative_number(value: float, name: str, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or value < 0:
        errors.append(f"{name} must be a non-negative finite number")


def _require_range(value: float, name: str, lower: float, upper: float, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or not lower <= value <= upper:
        errors.append(f"{name} must be between {lower} and {upper}")


def _require_non_empty_unique(values: Iterable[str], name: str, errors: list[str]) -> None:
    normalized = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    if not normalized:
        errors.append(f"{name} must contain at least one item")
    elif len(normalized) != len(set(normalized)):
        errors.append(f"{name} must not contain duplicates")
