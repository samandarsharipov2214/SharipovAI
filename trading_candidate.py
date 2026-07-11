"""Canonical fail-closed contract for every SharipovAI trading candidate.

This module never places orders. It validates the evidence packet that must exist
before virtual, testnet, or mainnet execution can even be considered.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from math import isfinite
from typing import Iterable, Mapping


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
class TrustedSecurityApproval:
    """Approval supplied by Security Guard, never by the candidate itself."""

    approval_id: str
    candidate_id: str
    environment: TradingEnvironment
    approved_by: str
    approved_at_ms: int
    expires_at_ms: int
    manual_confirmation: bool
    security_guard_approved: bool
    kill_switch_off: bool


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
    news_assessment_id: str
    portfolio_snapshot_id: str
    cost_snapshot_id: str
    estimated_fees: float
    estimated_slippage: float
    risk_score: float
    risk_blocks: tuple[str, ...]
    confidence: float
    consensus: float
    decision: TradingDecision
    expires_at_ms: int
    security_approval_id: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["category"] = self.category.value
        payload["side"] = self.side.value
        payload["environment"] = self.environment.value
        payload["market_regime"] = self.market_regime.value
        payload["decision"] = self.decision.value
        return payload


@dataclass(frozen=True, slots=True)
class CandidateValidation:
    valid: bool
    decision: TradingDecision
    errors: tuple[str, ...]
    effective_min_confidence: float
    effective_min_consensus: float


def validate_trading_candidate(
    candidate: TradingCandidate,
    *,
    now_ms: int,
    max_market_age_ms: int = 2_500,
    min_confidence: float = 70.0,
    min_consensus: float = 70.0,
    trusted_security_approvals: Mapping[str, TrustedSecurityApproval] | None = None,
) -> CandidateValidation:
    """Validate a candidate and force BLOCK whenever required evidence is unsafe."""

    errors: list[str] = []
    effective_max_age = min(max(int(max_market_age_ms), 100), 5_000)
    effective_confidence = min(max(float(min_confidence), 70.0), 100.0)
    effective_consensus = min(max(float(min_consensus), 70.0), 100.0)

    _require_text(candidate.candidate_id, "candidate_id", errors)
    _require_text(candidate.portfolio_snapshot_id, "portfolio_snapshot_id", errors)
    _require_text(candidate.cost_snapshot_id, "cost_snapshot_id", errors)
    _require_text(candidate.news_assessment_id, "news_assessment_id", errors)

    if not candidate.symbol or candidate.symbol != candidate.symbol.upper() or not candidate.symbol.isalnum():
        errors.append("symbol must be uppercase alphanumeric")

    if now_ms <= 0:
        errors.append("now_ms must be positive")
    if candidate.market_timestamp_ms <= 0:
        errors.append("market_timestamp_ms must be positive")
    if candidate.received_timestamp_ms < candidate.market_timestamp_ms:
        errors.append("received_timestamp_ms must not precede market_timestamp_ms")
    if candidate.market_timestamp_ms > now_ms + 1_000:
        errors.append("market_timestamp_ms is too far in the future")
    if candidate.received_timestamp_ms > now_ms + 1_000:
        errors.append("received_timestamp_ms is too far in the future")
    if candidate.expires_at_ms <= now_ms:
        errors.append("candidate is expired")
    if candidate.expires_at_ms > now_ms + 10_000:
        errors.append("candidate lifetime exceeds hard 10 second limit")
    if now_ms - candidate.market_timestamp_ms > effective_max_age:
        errors.append("market data is stale")

    _require_positive_number(candidate.reference_price, "reference_price", errors)
    _require_non_negative_number(candidate.estimated_fees, "estimated_fees", errors)
    _require_non_negative_number(candidate.estimated_slippage, "estimated_slippage", errors)
    _require_range(candidate.risk_score, "risk_score", 0.0, 100.0, errors)
    _require_range(candidate.confidence, "confidence", 0.0, 100.0, errors)
    _require_range(candidate.consensus, "consensus", 0.0, 100.0, errors)

    _require_non_empty_unique(candidate.data_sources, "data_sources", errors)
    _require_non_empty_unique(candidate.signal_evidence, "signal_evidence", errors)
    _require_unique(candidate.news_evidence, "news_evidence", errors)
    _require_unique(candidate.risk_blocks, "risk_blocks", errors)

    if candidate.decision is TradingDecision.ALLOW:
        if len({item.strip() for item in candidate.data_sources if item.strip()}) < 3:
            errors.append("ALLOW requires at least three independent data sources")
        if candidate.confidence < effective_confidence:
            errors.append("confidence is below required threshold")
        if candidate.consensus < effective_consensus:
            errors.append("consensus is below required threshold")
        if candidate.risk_blocks:
            errors.append("risk_blocks require BLOCK decision")
        if candidate.market_regime in {MarketRegime.ILLIQUID, MarketRegime.UNKNOWN}:
            errors.append("unsafe or unknown market regime cannot be ALLOW")

    if candidate.environment is TradingEnvironment.MAINNET and candidate.decision is TradingDecision.ALLOW:
        approval = (trusted_security_approvals or {}).get(candidate.security_approval_id)
        if not candidate.security_approval_id or approval is None:
            errors.append("mainnet ALLOW requires an external trusted Security Guard approval")
        else:
            _validate_trusted_approval(candidate, approval, now_ms, errors)

    if errors:
        return CandidateValidation(
            False,
            TradingDecision.BLOCK,
            tuple(errors),
            effective_confidence,
            effective_consensus,
        )

    return CandidateValidation(
        True,
        candidate.decision,
        (),
        effective_confidence,
        effective_consensus,
    )


def _validate_trusted_approval(
    candidate: TradingCandidate,
    approval: TrustedSecurityApproval,
    now_ms: int,
    errors: list[str],
) -> None:
    _require_text(approval.approval_id, "approval_id", errors)
    _require_text(approval.approved_by, "approved_by", errors)
    if approval.approval_id != candidate.security_approval_id:
        errors.append("Security Guard approval id mismatch")
    if approval.candidate_id != candidate.candidate_id:
        errors.append("Security Guard approval candidate mismatch")
    if approval.environment is not TradingEnvironment.MAINNET:
        errors.append("Security Guard approval environment mismatch")
    if approval.approved_at_ms > now_ms or approval.expires_at_ms <= now_ms:
        errors.append("Security Guard approval is not currently valid")
    if approval.expires_at_ms - approval.approved_at_ms > 300_000:
        errors.append("Security Guard approval lifetime exceeds five minutes")
    if approval.manual_confirmation is not True:
        errors.append("trusted approval lacks manual confirmation")
    if approval.security_guard_approved is not True:
        errors.append("trusted approval lacks Security Guard decision")
    if approval.kill_switch_off is not True:
        errors.append("trusted approval confirms that kill switch is not off")


def _require_text(value: str, name: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{name} is required")


def _require_positive_number(value: float, name: str, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or value <= 0:
        errors.append(f"{name} must be a positive finite number")


def _require_non_negative_number(value: float, name: str, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or value < 0:
        errors.append(f"{name} must be a non-negative finite number")


def _require_range(
    value: float,
    name: str,
    lower: float,
    upper: float,
    errors: list[str],
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or not lower <= value <= upper:
        errors.append(f"{name} must be between {lower} and {upper}")


def _normalized(values: Iterable[str]) -> list[str]:
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


def _require_non_empty_unique(values: Iterable[str], name: str, errors: list[str]) -> None:
    normalized = _normalized(values)
    if not normalized:
        errors.append(f"{name} must contain at least one item")
    elif len(normalized) != len(set(normalized)):
        errors.append(f"{name} must not contain duplicates")


def _require_unique(values: Iterable[str], name: str, errors: list[str]) -> None:
    normalized = _normalized(values)
    if len(normalized) != len(set(normalized)):
        errors.append(f"{name} must not contain duplicates")
