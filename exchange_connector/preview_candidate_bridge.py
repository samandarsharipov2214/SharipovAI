"""Fail-closed bridge between a verified order preview and trading candidate.

This module does not execute orders. It binds the immutable preview fields to a
candidate through a SHA-256 evidence token and delegates candidate validation to
the existing trading_candidate validator supplied by the caller.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from math import isclose
from typing import Any


class PreviewCandidateError(ValueError):
    """Raised when preview and candidate cannot be linked safely."""


@dataclass(frozen=True, slots=True)
class PreviewCandidateLink:
    status: str
    linked: bool
    execution_allowed: bool
    preview_digest: str
    candidate_result: dict[str, Any]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["blockers"] = list(self.blockers)
        return data


_PREVIEW_FIELDS = (
    "symbol",
    "side",
    "order_type",
    "quantity",
    "entry_price",
    "notional",
    "estimated_entry_fee",
    "estimated_exit_fee",
    "estimated_slippage",
    "stop_loss",
    "take_profit",
    "maximum_loss",
    "potential_reward",
    "risk_reward_ratio",
    "risk_percent_of_equity",
    "leverage",
    "margin_required",
)


def preview_digest(preview: Mapping[str, Any]) -> str:
    """Return a deterministic digest of the safety-relevant preview fields."""
    if not isinstance(preview, Mapping):
        raise PreviewCandidateError("preview must be an object")
    missing = [field for field in _PREVIEW_FIELDS if field not in preview]
    if missing:
        raise PreviewCandidateError("preview is missing fields: " + ", ".join(missing))
    if preview.get("executed") is not False:
        raise PreviewCandidateError("preview must declare executed=false")
    if preview.get("executable") is not False:
        raise PreviewCandidateError("preview must declare executable=false")
    if preview.get("sends_order") is not False:
        raise PreviewCandidateError("preview must declare sends_order=false")
    canonical = {field: preview[field] for field in _PREVIEW_FIELDS}
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_preview_candidate(
    preview: Mapping[str, Any],
    candidate_payload: Mapping[str, Any],
    *,
    validator: Callable[..., Any],
    now_ms: int | None = None,
) -> PreviewCandidateLink:
    """Validate candidate contract and prove that it references this preview.

    The validator must be the existing ``validate_trading_candidate`` function.
    No executor is called and execution_allowed is always false at this bridge.
    """
    digest = preview_digest(preview)
    blockers: list[str] = []
    if not isinstance(candidate_payload, Mapping):
        raise PreviewCandidateError("candidate_payload must be an object")

    evidence = candidate_payload.get("signal_evidence")
    token = f"preview_sha256:{digest}"
    if not isinstance(evidence, list) or token not in evidence:
        blockers.append("candidate is not bound to the verified preview digest")

    _compare_text(preview, candidate_payload, "symbol", blockers)
    preview_side = str(preview.get("side", "")).strip().lower()
    candidate_side = str(candidate_payload.get("side", "")).strip().lower()
    if preview_side != candidate_side:
        blockers.append("candidate side does not match preview")

    _compare_number(preview.get("entry_price"), candidate_payload.get("reference_price"), "reference price", blockers)
    expected_fees = _number(preview.get("estimated_entry_fee")) + _number(preview.get("estimated_exit_fee"))
    _compare_number(expected_fees, candidate_payload.get("estimated_fees"), "estimated fees", blockers)
    _compare_number(preview.get("estimated_slippage"), candidate_payload.get("estimated_slippage"), "estimated slippage", blockers)

    try:
        result = validator(candidate_payload, now_ms=now_ms)
    except TypeError:
        result = validator(candidate_payload)
    result_dict = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    if not bool(result_dict.get("valid")):
        blockers.append("trading candidate contract is invalid")
    if str(result_dict.get("effective_decision", "BLOCK")).upper() != "ALLOW":
        blockers.append("trading candidate effective decision is not ALLOW")

    return PreviewCandidateLink(
        status="linked" if not blockers else "blocked",
        linked=not blockers,
        execution_allowed=False,
        preview_digest=digest,
        candidate_result=result_dict,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _compare_text(
    preview: Mapping[str, Any], candidate: Mapping[str, Any], field: str, blockers: list[str]
) -> None:
    if str(preview.get(field, "")).strip().upper() != str(candidate.get(field, "")).strip().upper():
        blockers.append(f"candidate {field} does not match preview")


def _compare_number(expected: Any, actual: Any, label: str, blockers: list[str]) -> None:
    try:
        left = _number(expected)
        right = _number(actual)
    except PreviewCandidateError:
        blockers.append(f"candidate {label} is invalid")
        return
    tolerance = max(abs(left) * 1e-9, 1e-9)
    if not isclose(left, right, rel_tol=1e-9, abs_tol=tolerance):
        blockers.append(f"candidate {label} does not match preview")


def _number(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise PreviewCandidateError("numeric value is invalid") from exc
    if parsed < 0 or parsed != parsed or parsed in {float("inf"), float("-inf")}:
        raise PreviewCandidateError("numeric value must be finite and non-negative")
    return parsed
