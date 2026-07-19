"""Expected-versus-actual Paper fill validation under explicit tolerances."""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class ExpectedPaperFill:
    match_id: str
    symbol: str
    side: str
    submitted_at_ms: int
    requested_quantity: float
    reference_price: float
    expected_fill_price: float
    expected_latency_ms: float
    expected_fee: float


@dataclass(frozen=True, slots=True)
class PaperFillValidationThresholds:
    minimum_matches: int = 20
    maximum_p95_latency_error_ms: float = 1_000.0
    maximum_p95_price_error_bps: float = 10.0
    maximum_fill_ratio_delta: float = 0.05
    maximum_p95_fee_delta_bps: float = 5.0


@dataclass(frozen=True, slots=True)
class PaperFillValidationReport:
    report_id: str
    matched_count: int
    unmatched_expected_ids: tuple[str, ...]
    unmatched_actual_ids: tuple[str, ...]
    p95_latency_error_ms: float
    p95_price_error_bps: float
    maximum_fill_ratio_delta: float
    p95_fee_delta_bps: float
    validation_passed: bool
    failed_gates: tuple[str, ...]
    pairs: tuple[dict[str, Any], ...]
    created_at_ms: int
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExpectedPaperFillAnalyzer:
    def __init__(self, thresholds: PaperFillValidationThresholds | None = None) -> None:
        self.thresholds = thresholds or PaperFillValidationThresholds()

    def analyze(
        self,
        expected_fills: Iterable[ExpectedPaperFill | Mapping[str, Any]],
        actual_fills: Iterable[Mapping[str, Any]],
        *,
        report_id: str | None = None,
        created_at_ms: int | None = None,
    ) -> PaperFillValidationReport:
        expected_items = [_expected(item) for item in expected_fills]
        actual_items = [_actual(item) for item in actual_fills]
        expected = {item.match_id: item for item in expected_items}
        actual = {item["match_id"]: item for item in actual_items}
        if len(expected) != len(expected_items) or len(actual) != len(actual_items):
            raise ValueError("duplicate fill identity is forbidden")
        if not expected and not actual:
            raise ValueError("paper fill validation requires observations")
        common = sorted(set(expected) & set(actual))
        unmatched_expected = sorted(set(expected) - set(actual))
        unmatched_actual = sorted(set(actual) - set(expected))
        latency_errors: list[float] = []
        price_errors: list[float] = []
        ratio_errors: list[float] = []
        fee_errors: list[float] = []
        pairs: list[dict[str, Any]] = []
        for match_id in common:
            planned = expected[match_id]
            observed = actual[match_id]
            if planned.symbol != observed["symbol"] or planned.side != observed["side"]:
                raise ValueError(f"paper fill identity mismatch for {match_id}")
            actual_latency = max(0.0, float(observed["first_fill_at_ms"] - planned.submitted_at_ms))
            latency_error = abs(actual_latency - planned.expected_latency_ms)
            if planned.side == "BUY":
                price_error = (observed["average_fill_price"] - planned.expected_fill_price) / planned.expected_fill_price * 10_000.0
            else:
                price_error = (planned.expected_fill_price - observed["average_fill_price"]) / planned.expected_fill_price * 10_000.0
            price_error = abs(price_error)
            fill_ratio = min(max(observed["filled_quantity"] / planned.requested_quantity, 0.0), 1.0)
            ratio_error = abs(1.0 - fill_ratio)
            expected_notional = max(planned.expected_fill_price * planned.requested_quantity, 1e-12)
            actual_notional = max(observed["average_fill_price"] * observed["filled_quantity"], 1e-12)
            fee_error = abs(observed["fee"] / actual_notional * 10_000.0 - planned.expected_fee / expected_notional * 10_000.0)
            latency_errors.append(latency_error)
            price_errors.append(price_error)
            ratio_errors.append(ratio_error)
            fee_errors.append(fee_error)
            pairs.append({
                "match_id": match_id,
                "symbol": planned.symbol,
                "side": planned.side,
                "expected_latency_ms": round(planned.expected_latency_ms, 8),
                "actual_latency_ms": round(actual_latency, 8),
                "latency_error_ms": round(latency_error, 8),
                "expected_fill_price": round(planned.expected_fill_price, 12),
                "actual_fill_price": round(observed["average_fill_price"], 12),
                "price_error_bps": round(price_error, 8),
                "fill_ratio": round(fill_ratio, 8),
                "fill_ratio_delta": round(ratio_error, 8),
                "fee_delta_bps": round(fee_error, 8),
            })
        p95_latency = _percentile(latency_errors, 95.0)
        p95_price = _percentile(price_errors, 95.0)
        max_ratio = max(ratio_errors, default=1.0)
        p95_fee = _percentile(fee_errors, 95.0)
        failed: list[str] = []
        if len(common) < self.thresholds.minimum_matches:
            failed.append("insufficient_expected_actual_matches")
        if unmatched_expected:
            failed.append("missing_actual_paper_fills")
        if unmatched_actual:
            failed.append("unexpected_actual_paper_fills")
        if p95_latency > self.thresholds.maximum_p95_latency_error_ms:
            failed.append("paper_latency_error_exceeded")
        if p95_price > self.thresholds.maximum_p95_price_error_bps:
            failed.append("paper_price_error_exceeded")
        if max_ratio > self.thresholds.maximum_fill_ratio_delta:
            failed.append("paper_fill_ratio_error_exceeded")
        if p95_fee > self.thresholds.maximum_p95_fee_delta_bps:
            failed.append("paper_fee_error_exceeded")
        timestamp = int(time.time() * 1000) if created_at_ms is None else int(created_at_ms)
        if timestamp <= 0:
            raise ValueError("created_at_ms must be positive")
        base = {
            "matched_count": len(common),
            "unmatched_expected_ids": unmatched_expected,
            "unmatched_actual_ids": unmatched_actual,
            "p95_latency_error_ms": round(p95_latency, 8),
            "p95_price_error_bps": round(p95_price, 8),
            "maximum_fill_ratio_delta": round(max_ratio, 8),
            "p95_fee_delta_bps": round(p95_fee, 8),
            "failed_gates": sorted(failed),
            "pairs": pairs,
        }
        evidence_sha = _digest(base)
        identifier = _identifier(report_id or f"paperfill_{evidence_sha[:24]}", "report_id")
        return PaperFillValidationReport(
            report_id=identifier,
            matched_count=len(common),
            unmatched_expected_ids=tuple(unmatched_expected),
            unmatched_actual_ids=tuple(unmatched_actual),
            p95_latency_error_ms=round(p95_latency, 8),
            p95_price_error_bps=round(p95_price, 8),
            maximum_fill_ratio_delta=round(max_ratio, 8),
            p95_fee_delta_bps=round(p95_fee, 8),
            validation_passed=not failed,
            failed_gates=tuple(sorted(failed)),
            pairs=tuple(pairs),
            created_at_ms=timestamp,
            evidence_sha256=evidence_sha,
        )


def _expected(value: ExpectedPaperFill | Mapping[str, Any]) -> ExpectedPaperFill:
    if isinstance(value, ExpectedPaperFill):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("expected fill must be an object")
    side = str(value.get("side") or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    return ExpectedPaperFill(
        match_id=_identifier(_first(value, "match_id", "order_link_id"), "match_id"),
        symbol=_identifier(str(value.get("symbol") or "").upper(), "symbol"),
        side=side,
        submitted_at_ms=_positive_int(_first(value, "submitted_at_ms"), "submitted_at_ms"),
        requested_quantity=_positive(_first(value, "requested_quantity"), "requested_quantity"),
        reference_price=_positive(_first(value, "reference_price"), "reference_price"),
        expected_fill_price=_positive(_first(value, "expected_fill_price"), "expected_fill_price"),
        expected_latency_ms=_nonnegative(_first(value, "expected_latency_ms"), "expected_latency_ms"),
        expected_fee=_nonnegative(_first(value, "expected_fee"), "expected_fee"),
    )


def _actual(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("actual fill must be an object")
    side = str(value.get("side") or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    return {
        "match_id": _identifier(_first(value, "match_id", "order_link_id", "trade_id"), "match_id"),
        "symbol": _identifier(str(value.get("symbol") or "").upper(), "symbol"),
        "side": side,
        "first_fill_at_ms": _positive_int(_first(value, "first_fill_at_ms", "filled_at_ms"), "first_fill_at_ms"),
        "filled_quantity": _nonnegative(_first(value, "filled_quantity", "quantity"), "filled_quantity"),
        "average_fill_price": _positive(_first(value, "average_fill_price", "price"), "average_fill_price"),
        "fee": _nonnegative(_first(value, "fee", "actual_fee", default=0.0), "fee"),
    }


def _first(value: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in value and value[name] is not None:
            return value[name]
    return default


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"invalid {name}")
    return clean


def _positive_int(value: Any, name: str) -> int:
    parsed = int(value or 0)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _positive(value: Any, name: str) -> float:
    parsed = _finite(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _nonnegative(value: Any, name: str) -> float:
    parsed = _finite(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must be nonnegative")
    return parsed


def _finite(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


__all__ = ["ExpectedPaperFill", "ExpectedPaperFillAnalyzer", "PaperFillValidationReport", "PaperFillValidationThresholds"]
