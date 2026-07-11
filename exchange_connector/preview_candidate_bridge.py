"""Bind a verified non-executing OrderPreview to the canonical TradingCandidate.

This module performs no network or execution action. A successful result proves
only that both evidence objects are internally consistent; ``execution_allowed``
is always false and downstream Risk/Security/Stage gates remain mandatory.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from trading_candidate import TradingCandidate, TradingDecision, validate_trading_candidate

from .order_preview import OrderPreview

_PREFIX = "preview_sha256:"
_TOLERANCE = 1e-8


@dataclass(frozen=True, slots=True)
class PreviewCandidateValidation:
    valid: bool
    decision: TradingDecision
    errors: tuple[str, ...]
    preview_digest: str
    execution_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "decision": self.decision.value,
            "errors": list(self.errors),
            "preview_digest": self.preview_digest,
            "execution_allowed": False,
        }


def preview_digest(preview: OrderPreview) -> str:
    payload = asdict(preview)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bind_preview_to_candidate(
    preview: OrderPreview,
    candidate: TradingCandidate,
    *,
    now_ms: int,
    max_instrument_age_ms: int = 60_000,
    trusted_security_approvals: Mapping[str, Any] | None = None,
) -> PreviewCandidateValidation:
    errors: list[str] = []
    try:
        digest = preview_digest(preview)
    except (TypeError, ValueError) as exc:
        return PreviewCandidateValidation(False, TradingDecision.BLOCK, (f"preview serialization failed: {exc}",), "")

    tokens = [item.strip() for item in candidate.signal_evidence if isinstance(item, str) and item.strip().startswith(_PREFIX)]
    expected = f"{_PREFIX}{digest}"
    if tokens != [expected]:
        errors.append("candidate must contain exactly one matching preview SHA-256 evidence token")

    _validate_preview_numbers(preview, errors)
    if preview.symbol != candidate.symbol:
        errors.append("preview symbol does not match candidate")
    if preview.category != candidate.category.value:
        errors.append("preview category does not match candidate")
    if preview.side.title() != candidate.side.value:
        errors.append("preview side does not match candidate")
    if not _close(preview.reference_price, candidate.reference_price):
        errors.append("preview reference price does not match candidate")
    if not _close(preview.estimated_entry_fee + preview.estimated_exit_fee_at_stop, candidate.estimated_fees):
        errors.append("preview fees do not match candidate cost evidence")
    if not _close(preview.estimated_slippage, candidate.estimated_slippage):
        errors.append("preview slippage does not match candidate cost evidence")

    for flag in ("risk_approved", "executable", "executed", "sends_order"):
        if getattr(preview, flag) is not False:
            errors.append(f"preview {flag} must remain false")
    for flag in ("funding_included", "liquidation_checked", "correlation_checked"):
        if getattr(preview, flag) is not False:
            errors.append(f"preview cannot self-assert {flag}")

    effective_age = min(max(int(max_instrument_age_ms), 1_000), 300_000)
    fetched_at = _finite(preview.instrument_rules_fetched_at_ms, "instrument_rules_fetched_at_ms", errors)
    if now_ms <= 0:
        errors.append("now_ms must be positive")
    elif fetched_at is not None:
        if fetched_at > now_ms + 1_000:
            errors.append("instrument rules timestamp is in the future")
        elif now_ms - fetched_at > effective_age:
            errors.append("instrument rules are stale")

    _recalculate_preview(preview, errors)

    try:
        candidate_result = validate_trading_candidate(
            candidate,
            now_ms=now_ms,
            trusted_security_approvals=trusted_security_approvals,
        )
    except Exception as exc:
        errors.append(f"canonical candidate validator failed: {type(exc).__name__}: {exc}")
    else:
        if not candidate_result.valid:
            errors.extend(f"candidate: {item}" for item in candidate_result.errors)
        if candidate_result.decision is not TradingDecision.ALLOW:
            errors.append("canonical candidate decision is not ALLOW")

    return PreviewCandidateValidation(
        valid=not errors,
        decision=TradingDecision.ALLOW if not errors else TradingDecision.BLOCK,
        errors=tuple(errors),
        preview_digest=digest,
        execution_allowed=False,
    )


def _validate_preview_numbers(preview: OrderPreview, errors: list[str]) -> None:
    positive = {
        "quantity", "reference_price", "entry_price", "notional", "stop_loss",
        "take_profit", "maximum_loss", "potential_reward", "risk_reward_ratio",
        "max_risk_percent", "leverage", "available_balance",
    }
    nonnegative = {
        "estimated_entry_fee", "estimated_exit_fee_at_stop", "estimated_slippage",
        "risk_percent_of_equity", "required_capital",
    }
    for name in sorted(positive | nonnegative):
        value = getattr(preview, name)
        parsed = _finite(value, name, errors)
        if parsed is None:
            continue
        if name in positive and parsed <= 0:
            errors.append(f"preview {name} must be positive")
        if name in nonnegative and parsed < 0:
            errors.append(f"preview {name} must not be negative")
    if preview.max_risk_percent > 5:
        errors.append("preview max risk percent exceeds hard cap")
    if preview.risk_percent_of_equity > preview.max_risk_percent + _TOLERANCE:
        errors.append("preview risk exceeds configured maximum")


def _recalculate_preview(preview: OrderPreview, errors: list[str]) -> None:
    quantity = float(preview.quantity)
    entry = float(preview.entry_price)
    reference = float(preview.reference_price)
    stop = float(preview.stop_loss)
    take = float(preview.take_profit)
    notional = quantity * entry
    if not _close(notional, preview.notional):
        errors.append("preview notional is inconsistent")

    if preview.side == "buy" and not (stop < entry < take):
        errors.append("buy preview price ordering is invalid")
    if preview.side == "sell" and not (take < entry < stop):
        errors.append("sell preview price ordering is invalid")

    if preview.order_type == "market":
        expected_slippage = quantity * abs(entry - reference)
        if preview.side == "buy" and entry + _TOLERANCE < reference:
            errors.append("market buy slippage is favorable instead of adverse")
        if preview.side == "sell" and entry - _TOLERANCE > reference:
            errors.append("market sell slippage is favorable instead of adverse")
    elif preview.order_type == "limit":
        expected_slippage = 0.0
    else:
        errors.append("preview order_type is unsupported")
        expected_slippage = float(preview.estimated_slippage)
    if not _close(expected_slippage, preview.estimated_slippage):
        errors.append("preview slippage calculation is inconsistent")

    entry_fee_rate = preview.estimated_entry_fee / preview.notional if preview.notional > 0 else math.nan
    stop_exit_notional = quantity * stop
    exit_fee_rate = preview.estimated_exit_fee_at_stop / stop_exit_notional if stop_exit_notional > 0 else math.nan
    if not math.isfinite(entry_fee_rate) or entry_fee_rate < 0 or entry_fee_rate > 0.05:
        errors.append("preview entry fee rate is invalid")
    if not math.isfinite(exit_fee_rate) or exit_fee_rate < 0 or exit_fee_rate > 0.05:
        errors.append("preview exit fee rate is invalid")

    expected_loss = quantity * abs(entry - stop) + preview.estimated_entry_fee + preview.estimated_exit_fee_at_stop
    take_exit_fee = quantity * take * exit_fee_rate if math.isfinite(exit_fee_rate) else math.nan
    expected_reward = quantity * abs(take - entry) - preview.estimated_entry_fee - take_exit_fee
    if not _close(expected_loss, preview.maximum_loss):
        errors.append("preview maximum loss is inconsistent")
    if not _close(expected_reward, preview.potential_reward):
        errors.append("preview potential reward is inconsistent")
    expected_ratio = expected_reward / expected_loss if expected_loss > 0 else math.nan
    if not _close(expected_ratio, preview.risk_reward_ratio):
        errors.append("preview risk/reward ratio is inconsistent")

    if preview.category == "linear":
        expected_capital = preview.notional / preview.leverage + preview.estimated_entry_fee
    elif preview.category == "spot" and preview.side == "buy":
        expected_capital = preview.notional + preview.estimated_entry_fee
    elif preview.category == "spot" and preview.side == "sell":
        expected_capital = 0.0
    else:
        errors.append("preview category/side capital model is unsupported")
        expected_capital = preview.required_capital
    if not _close(expected_capital, preview.required_capital):
        errors.append("preview required capital is inconsistent")
    if preview.required_capital > preview.available_balance + _TOLERANCE:
        errors.append("preview required capital exceeds available balance")


def _finite(value: Any, name: str, errors: list[str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        errors.append(f"preview {name} must be a finite number")
        return None
    return float(value)


def _close(left: float, right: float) -> bool:
    try:
        left_value = float(left)
        right_value = float(right)
    except (TypeError, ValueError):
        return False
    return math.isfinite(left_value) and math.isfinite(right_value) and math.isclose(
        left_value,
        right_value,
        rel_tol=1e-8,
        abs_tol=1e-8,
    )


__all__ = ["PreviewCandidateValidation", "bind_preview_to_candidate", "preview_digest"]
