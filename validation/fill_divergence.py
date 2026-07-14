"""Paper-versus-Testnet fill divergence analysis and persistence."""
from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from storage import ProjectDatabase, list_json_items

_NAMESPACE = "paper_testnet_fill_validation"
_EVENT_NAMESPACE = "paper_testnet_fill_validation_events"
_PARTIAL_STATUSES = {"PartiallyFilled", "PartiallyFilledCanceled", "partial", "partial_fill"}


@dataclass(frozen=True, slots=True)
class FillObservation:
    match_id: str
    source: str
    symbol: str
    side: str
    submitted_at_ms: int
    first_fill_at_ms: int
    completed_at_ms: int
    requested_quantity: float
    filled_quantity: float
    reference_price: float
    average_fill_price: float
    fee: float
    status: str

    @property
    def latency_ms(self) -> int:
        return max(0, self.first_fill_at_ms - self.submitted_at_ms)

    @property
    def fill_ratio(self) -> float:
        return min(max(self.filled_quantity / self.requested_quantity, 0.0), 1.0)

    @property
    def slippage_bps(self) -> float:
        if self.side == "BUY":
            raw = (self.average_fill_price - self.reference_price) / self.reference_price
        else:
            raw = (self.reference_price - self.average_fill_price) / self.reference_price
        return raw * 10_000.0

    @property
    def partial(self) -> bool:
        return self.status in _PARTIAL_STATUSES or (0.0 < self.fill_ratio < 0.999999)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DivergenceThresholds:
    minimum_matches: int = 20
    maximum_p95_latency_divergence_ms: float = 2_000.0
    maximum_p95_slippage_divergence_bps: float = 15.0
    maximum_partial_fill_rate_percent: float = 20.0
    maximum_fill_ratio_delta: float = 0.10
    maximum_fee_delta_bps: float = 10.0


@dataclass(frozen=True, slots=True)
class FillDivergenceReport:
    report_id: str
    matched_count: int
    unmatched_paper_count: int
    unmatched_testnet_count: int
    unmatched_paper_ids: tuple[str, ...]
    unmatched_testnet_ids: tuple[str, ...]
    average_latency_divergence_ms: float
    p95_latency_divergence_ms: float
    average_slippage_divergence_bps: float
    p95_slippage_divergence_bps: float
    average_fill_ratio_delta: float
    maximum_fill_ratio_delta: float
    average_fee_delta_bps: float
    p95_fee_delta_bps: float
    testnet_partial_fill_rate_percent: float
    promotion_eligible: bool
    failed_gates: tuple[str, ...]
    pairs: tuple[dict[str, Any], ...]
    created_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FillDivergenceAnalyzer:
    """Compare matched paper and Testnet observations under explicit tolerances."""

    def __init__(self, thresholds: DivergenceThresholds | None = None) -> None:
        self.thresholds = thresholds or DivergenceThresholds()

    def analyze(
        self,
        paper_fills: Iterable[FillObservation | Mapping[str, Any]],
        testnet_fills: Iterable[FillObservation | Mapping[str, Any]],
        *,
        report_id: str | None = None,
        created_at_ms: int | None = None,
    ) -> FillDivergenceReport:
        paper = {_observation(item, source="paper").match_id: _observation(item, source="paper") for item in paper_fills}
        testnet = {
            _observation(item, source="testnet").match_id: _observation(item, source="testnet")
            for item in testnet_fills
        }
        if len(paper) == 0 and len(testnet) == 0:
            raise ValueError("fill divergence analysis requires observations")
        common = sorted(set(paper) & set(testnet))
        unmatched_paper = sorted(set(paper) - set(testnet))
        unmatched_testnet = sorted(set(testnet) - set(paper))
        latency_deltas: list[float] = []
        slippage_deltas: list[float] = []
        fill_ratio_deltas: list[float] = []
        fee_deltas: list[float] = []
        partial_count = 0
        pairs: list[dict[str, Any]] = []

        for match_id in common:
            paper_fill = paper[match_id]
            testnet_fill = testnet[match_id]
            if paper_fill.symbol != testnet_fill.symbol or paper_fill.side != testnet_fill.side:
                raise ValueError(f"fill identity mismatch for {match_id}")
            latency_delta = abs(float(testnet_fill.latency_ms - paper_fill.latency_ms))
            slippage_delta = abs(testnet_fill.slippage_bps - paper_fill.slippage_bps)
            fill_ratio_delta = abs(testnet_fill.fill_ratio - paper_fill.fill_ratio)
            notional = max(testnet_fill.average_fill_price * testnet_fill.filled_quantity, 1e-12)
            paper_notional = max(paper_fill.average_fill_price * paper_fill.filled_quantity, 1e-12)
            testnet_fee_bps = testnet_fill.fee / notional * 10_000.0
            paper_fee_bps = paper_fill.fee / paper_notional * 10_000.0
            fee_delta = abs(testnet_fee_bps - paper_fee_bps)
            latency_deltas.append(latency_delta)
            slippage_deltas.append(slippage_delta)
            fill_ratio_deltas.append(fill_ratio_delta)
            fee_deltas.append(fee_delta)
            partial_count += int(testnet_fill.partial)
            pairs.append(
                {
                    "match_id": match_id,
                    "symbol": paper_fill.symbol,
                    "side": paper_fill.side,
                    "paper_latency_ms": paper_fill.latency_ms,
                    "testnet_latency_ms": testnet_fill.latency_ms,
                    "latency_divergence_ms": round(latency_delta, 8),
                    "paper_slippage_bps": round(paper_fill.slippage_bps, 8),
                    "testnet_slippage_bps": round(testnet_fill.slippage_bps, 8),
                    "slippage_divergence_bps": round(slippage_delta, 8),
                    "paper_fill_ratio": round(paper_fill.fill_ratio, 8),
                    "testnet_fill_ratio": round(testnet_fill.fill_ratio, 8),
                    "fill_ratio_delta": round(fill_ratio_delta, 8),
                    "fee_delta_bps": round(fee_delta, 8),
                    "testnet_partial": testnet_fill.partial,
                }
            )

        matched = len(common)
        partial_rate = partial_count / matched * 100.0 if matched else 100.0
        p95_latency = _percentile(latency_deltas, 95.0)
        p95_slippage = _percentile(slippage_deltas, 95.0)
        p95_fee = _percentile(fee_deltas, 95.0)
        maximum_fill_ratio_delta = max(fill_ratio_deltas, default=1.0)
        failed: list[str] = []
        if matched < self.thresholds.minimum_matches:
            failed.append("insufficient_matched_fills")
        if unmatched_paper:
            failed.append("unmatched_paper_fills")
        if unmatched_testnet:
            failed.append("unmatched_testnet_fills")
        if p95_latency > self.thresholds.maximum_p95_latency_divergence_ms:
            failed.append("latency_divergence_exceeded")
        if p95_slippage > self.thresholds.maximum_p95_slippage_divergence_bps:
            failed.append("slippage_divergence_exceeded")
        if partial_rate > self.thresholds.maximum_partial_fill_rate_percent:
            failed.append("partial_fill_rate_exceeded")
        if maximum_fill_ratio_delta > self.thresholds.maximum_fill_ratio_delta:
            failed.append("fill_ratio_divergence_exceeded")
        if p95_fee > self.thresholds.maximum_fee_delta_bps:
            failed.append("fee_divergence_exceeded")
        timestamp = _timestamp(created_at_ms)
        identifier = _identifier(
            report_id or f"fillval_{timestamp}_{matched}",
            "report_id",
        )
        return FillDivergenceReport(
            report_id=identifier,
            matched_count=matched,
            unmatched_paper_count=len(unmatched_paper),
            unmatched_testnet_count=len(unmatched_testnet),
            unmatched_paper_ids=tuple(unmatched_paper),
            unmatched_testnet_ids=tuple(unmatched_testnet),
            average_latency_divergence_ms=round(_mean(latency_deltas), 8),
            p95_latency_divergence_ms=round(p95_latency, 8),
            average_slippage_divergence_bps=round(_mean(slippage_deltas), 8),
            p95_slippage_divergence_bps=round(p95_slippage, 8),
            average_fill_ratio_delta=round(_mean(fill_ratio_deltas), 8),
            maximum_fill_ratio_delta=round(maximum_fill_ratio_delta, 8),
            average_fee_delta_bps=round(_mean(fee_deltas), 8),
            p95_fee_delta_bps=round(p95_fee, 8),
            testnet_partial_fill_rate_percent=round(partial_rate, 8),
            promotion_eligible=not failed,
            failed_gates=tuple(failed),
            pairs=tuple(pairs),
            created_at_ms=timestamp,
        )


class FillValidationRepository:
    """Persist immutable validation reports in the canonical project database."""

    def __init__(self, database: ProjectDatabase | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()

    def save(
        self,
        report: FillDivergenceReport | Mapping[str, Any],
        *,
        experiment_id: str,
        actor: str,
    ) -> dict[str, Any]:
        payload = report.to_dict() if isinstance(report, FillDivergenceReport) else _jsonable(report)
        report_id = _identifier(payload.get("report_id"), "report_id")
        experiment = _identifier(experiment_id, "experiment_id")
        clean_actor = _identifier(actor, "actor")
        document = {
            **_jsonable(payload),
            "experiment_id": experiment,
            "actor": clean_actor,
        }
        version = self.database.put_json(
            _NAMESPACE,
            report_id,
            document,
            expected_version=0,
        )
        event_id = self.database.append_event(
            _EVENT_NAMESPACE,
            "fill_validation",
            report_id,
            {
                "experiment_id": experiment,
                "actor": clean_actor,
                "promotion_eligible": bool(document.get("promotion_eligible")),
                "matched_count": int(document.get("matched_count", 0)),
                "version": version,
            },
            created_at_ms=int(document.get("created_at_ms") or time.time() * 1000),
        )
        return {**document, "version": version, "event_id": event_id}

    def get(self, report_id: str) -> dict[str, Any] | None:
        current = self.database.get_json(_NAMESPACE, _identifier(report_id, "report_id"))
        if current is None:
            return None
        return {**dict(current["value"]), "version": int(current["version"])}

    def list(self, *, experiment_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        rows = [
            {**dict(item["value"]), "version": int(item["version"])}
            for item in list_json_items(
                self.database,
                _NAMESPACE,
                limit=min(max(int(limit), 1), 2_000),
                newest_first=True,
            )
        ]
        if experiment_id is None:
            return rows
        clean = _identifier(experiment_id, "experiment_id")
        return [item for item in rows if item.get("experiment_id") == clean]


def _observation(value: FillObservation | Mapping[str, Any], *, source: str) -> FillObservation:
    if isinstance(value, FillObservation):
        if value.source != source:
            return FillObservation(**{**value.to_dict(), "source": source})
        return value
    if not isinstance(value, Mapping):
        raise TypeError("fill observation must be an object")
    match_id = _first(value, "order_link_id", "orderLinkId", "candidate_id", "paper_trade_id", "trade_id", "match_id")
    symbol = str(_first(value, "symbol", "asset")).strip().upper()
    side = str(_first(value, "side")).strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("fill side must be BUY or SELL")
    submitted = _positive_int(_first(value, "submitted_at_ms", "created_at_ms", "createdTime", "opened_at"), "submitted_at_ms")
    first_fill = _positive_int(
        _first(value, "first_fill_at_ms", "filled_at_ms", "updated_time_ms", "updatedTime", "closed_at", default=submitted),
        "first_fill_at_ms",
    )
    completed = _positive_int(
        _first(value, "completed_at_ms", "updated_time_ms", "updatedTime", "closed_at", default=first_fill),
        "completed_at_ms",
    )
    requested = _positive_number(_first(value, "requested_quantity", "requested_qty", "quantity", "qty", "paper_quantity"), "requested_quantity")
    filled = _nonnegative_number(
        _first(value, "filled_quantity", "filled_qty", "cum_exec_qty", "cumExecQty", "quantity", default=requested),
        "filled_quantity",
    )
    reference = _positive_number(_first(value, "reference_price", "price", "entry_price"), "reference_price")
    average = _positive_number(
        _first(value, "average_fill_price", "avg_fill_price", "avg_price", "avgPrice", "execution_price", "price"),
        "average_fill_price",
    )
    fee = _nonnegative_number(_first(value, "fee", "fees", "execution_fee", default=0.0), "fee")
    status = str(_first(value, "status", "order_status", "orderStatus", default="Filled")).strip()
    if first_fill < submitted or completed < first_fill:
        raise ValueError("fill timestamps must be monotonic")
    return FillObservation(
        match_id=_identifier(match_id, "match_id"),
        source=source,
        symbol=_identifier(symbol, "symbol"),
        side=side,
        submitted_at_ms=submitted,
        first_fill_at_ms=first_fill,
        completed_at_ms=completed,
        requested_quantity=requested,
        filled_quantity=filled,
        reference_price=reference,
        average_fill_price=average,
        fee=fee,
        status=status,
    )


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return default


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (percentile / 100.0) * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True))


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"{name} must contain 1..200 characters")
    return clean


def _positive_number(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return parsed


def _nonnegative_number(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{name} must be a non-negative finite number")
    return parsed


def _positive_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _timestamp(value: int | None) -> int:
    return _positive_int(int(time.time() * 1000) if value is None else value, "timestamp")


__all__ = [
    "DivergenceThresholds",
    "FillDivergenceAnalyzer",
    "FillDivergenceReport",
    "FillObservation",
    "FillValidationRepository",
]
