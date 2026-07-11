"""Fail-closed binding between a verified preview and TradingCandidate.

The bridge proves that the candidate references the exact non-executing preview.
It never grants execution permission and never calls an exchange.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from math import isclose, isfinite
from typing import Any, Mapping

from exchange_connector.order_preview import OrderPreview
from trading_candidate import (
    CandidateValidation,
    TradingCandidate,
    TradingDecision,
    TrustedSecurityApproval,
    validate_trading_candidate,
)

_TOKEN_PREFIX = "preview_sha256:"


@dataclass(frozen=True, slots=True)
class PreviewCandidateBinding:
    valid: bool
    decision: TradingDecision
    errors: tuple[str, ...]
    preview_digest: str
    candidate_validation: CandidateValidation
    execution_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "decision": self.decision.value,
            "errors": list(self.errors),
            "preview_digest": self.preview_digest,
            "candidate_validation": {
                "valid": self.candidate_validation.valid,
                "decision": self.candidate_validation.decision.value,
                "errors": list(self.candidate_validation.errors),
            },
            "execution_allowed": False,
        }


def preview_digest(preview: OrderPreview) -> str:
    """Digest the complete preview dataclass using canonical JSON."""
    if not isinstance(preview, OrderPreview):
        raise TypeError("preview must be an OrderPreview")
    payload = asdict(preview)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def evidence_token(preview: OrderPreview) -> str:
    return f"{_TOKEN_PREFIX}{preview_digest(preview)}"


def bind_preview_to_candidate(
    preview: OrderPreview,
    candidate: TradingCandidate,
    *,
    now_ms: int,
    max_instrument_rules_age_ms: int = 60_000,
    trusted_security_approvals: Mapping[str, TrustedSecurityApproval] | None = None,
) -> PreviewCandidateBinding:
    if not isinstance(candidate, TradingCandidate):
        raise TypeError("candidate must be a TradingCandidate")
    errors: list[str] = []
    try:
        digest = preview_digest(preview)
    except (TypeError, ValueError) as exc:
        digest = ""
        errors.append(f"preview digest is invalid: {exc}")
    token = f"{_TOKEN_PREFIX}{digest}" if digest else ""

    if isinstance(preview, OrderPreview):
        errors.extend(_preview_errors(preview))
    else:
        errors.append("preview must be an OrderPreview")

    evidence = candidate.signal_evidence
    if not isinstance(evidence, (tuple, list)):
        errors.append("candidate signal_evidence must be a list or tuple")
        preview_tokens: list[str] = []
    else:
        preview_tokens = [
            item for item in evidence
            if isinstance(item, str) and item.startswith(_TOKEN_PREFIX)
        ]
    if len(preview_tokens) != 1:
        errors.append("candidate must contain exactly one preview digest evidence token")
    elif not token or preview_tokens[0] != token:
        errors.append("candidate preview digest evidence does not match")

    if isinstance(preview, OrderPreview):
        if preview.symbol != candidate.symbol:
            errors.append("preview and candidate symbol mismatch")
        if preview.category != candidate.category.value:
            errors.append("preview and candidate category mismatch")
        if preview.side.title() != candidate.side.value:
            errors.append("preview and candidate side mismatch")
        if not _same(preview.reference_price, candidate.reference_price):
            errors.append("preview and candidate reference price mismatch")

        expected_fees = preview.estimated_entry_fee + preview.estimated_exit_fee_at_stop
        if not _same(expected_fees, candidate.estimated_fees):
            errors.append("preview and candidate estimated fees mismatch")
        if not _same(preview.estimated_slippage, candidate.estimated_slippage):
            errors.append("preview and candidate estimated slippage mismatch")

    try:
        if isinstance(max_instrument_rules_age_ms, bool):
            raise TypeError
        configured_rules_age = int(max_instrument_rules_age_ms)
    except (TypeError, ValueError):
        configured_rules_age = 60_000
        errors.append("max_instrument_rules_age_ms is invalid")
    effective_rules_age = min(max(configured_rules_age, 1_000), 300_000)
    if now_ms <= 0:
        errors.append("now_ms must be positive")
    if isinstance(preview, OrderPreview):
        if preview.instrument_rules_fetched_at_ms <= 0:
            errors.append("preview instrument rules timestamp is invalid")
        elif preview.instrument_rules_fetched_at_ms > now_ms + 1_000:
            errors.append("preview instrument rules timestamp is in the future")
        elif now_ms - preview.instrument_rules_fetched_at_ms > effective_rules_age:
            errors.append("preview instrument rules are stale")

    try:
        validation = validate_trading_candidate(
            candidate,
            now_ms=now_ms,
            trusted_security_approvals=trusted_security_approvals,
        )
    except (TypeError, ValueError, AttributeError) as exc:
        validation = CandidateValidation(
            False,
            TradingDecision.BLOCK,
            (f"candidate validator failed: {type(exc).__name__}",),
            70.0,
            70.0,
        )
    if not validation.valid:
        errors.extend(f"candidate: {error}" for error in validation.errors)
    if validation.decision is not TradingDecision.ALLOW:
        errors.append("candidate effective decision is not ALLOW")

    unique_errors = tuple(dict.fromkeys(errors))
    return PreviewCandidateBinding(
        valid=not unique_errors,
        decision=TradingDecision.ALLOW if not unique_errors else TradingDecision.BLOCK,
        errors=unique_errors,
        preview_digest=digest,
        candidate_validation=validation,
        execution_allowed=False,
    )


def _preview_errors(preview: OrderPreview) -> list[str]:
    errors: list[str] = []
    if any((preview.risk_approved, preview.executable, preview.executed, preview.sends_order)):
        errors.append("preview contains an execution or approval flag")
    if not preview.symbol or preview.symbol != preview.symbol.upper() or not preview.symbol.isalnum():
        errors.append("preview symbol is invalid")
    if preview.category not in {"spot", "linear"}:
        errors.append("preview category is invalid")
    if preview.side not in {"buy", "sell"}:
        errors.append("preview side is invalid")
    if preview.order_type not in {"market", "limit"}:
        errors.append("preview order_type is invalid")

    positive_fields = (
        "quantity", "reference_price", "entry_price", "notional", "stop_loss",
        "take_profit", "maximum_loss", "potential_reward", "risk_reward_ratio",
        "max_risk_percent", "leverage",
    )
    nonnegative_fields = (
        "estimated_entry_fee", "estimated_exit_fee_at_stop", "estimated_slippage",
        "risk_percent_of_equity", "required_capital", "available_balance",
    )
    for name in positive_fields:
        value = getattr(preview, name)
        if not _finite(value) or float(value) <= 0:
            errors.append(f"preview {name} must be a positive finite number")
    for name in nonnegative_fields:
        value = getattr(preview, name)
        if not _finite(value) or float(value) < 0:
            errors.append(f"preview {name} must be a non-negative finite number")

    if _finite(preview.quantity) and _finite(preview.entry_price) and _finite(preview.notional):
        if not _same(preview.notional, preview.quantity * preview.entry_price):
            errors.append("preview notional is inconsistent")
    if _finite(preview.maximum_loss) and _finite(preview.potential_reward) and _finite(preview.risk_reward_ratio):
        if preview.maximum_loss > 0 and not _same(
            preview.risk_reward_ratio,
            preview.potential_reward / preview.maximum_loss,
        ):
            errors.append("preview risk_reward_ratio is inconsistent")
    if preview.order_type == "limit" and not _same(preview.estimated_slippage, 0.0):
        errors.append("limit preview must have zero estimated slippage")
    if preview.order_type == "market" and all(
        _finite(value) for value in (preview.quantity, preview.entry_price, preview.reference_price, preview.estimated_slippage)
    ):
        expected_slippage = preview.quantity * abs(preview.entry_price - preview.reference_price)
        if not _same(preview.estimated_slippage, expected_slippage):
            errors.append("market preview estimated slippage is inconsistent")
    if preview.side == "buy" and not (preview.stop_loss < preview.entry_price < preview.take_profit):
        errors.append("buy preview price ordering is invalid")
    if preview.side == "sell" and not (preview.take_profit < preview.entry_price < preview.stop_loss):
        errors.append("sell preview price ordering is invalid")
    return errors


def _finite(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _same(left: float, right: float) -> bool:
    return _finite(left) and _finite(right) and isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
