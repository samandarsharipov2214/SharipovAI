"""Prometheus-ready metrics for SharipovAI runtime and research."""
from __future__ import annotations

import math
from typing import Any, Mapping

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "sharipovai_http_requests_total",
    "HTTP requests handled by SharipovAI",
    ("method", "path", "status"),
)
HTTP_DURATION = Histogram(
    "sharipovai_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ("method", "path"),
)
EXECUTION_BLOCKED = Gauge(
    "sharipovai_execution_blocked",
    "1 when exchange execution is blocked",
)
EXECUTION_JOURNAL_RECORDS = Gauge(
    "sharipovai_execution_journal_records",
    "Execution journal record count",
)
PAPER_EQUITY = Gauge("sharipovai_paper_equity", "Current paper-account equity")
PAPER_CASH = Gauge("sharipovai_paper_cash", "Current paper-account cash")
PAPER_NET_PNL = Gauge("sharipovai_paper_net_pnl", "Current paper-account net PnL")
PAPER_EXPOSURE_PERCENT = Gauge(
    "sharipovai_paper_exposure_percent",
    "Current paper-account deployed exposure percent",
)
PAPER_RESERVE = Gauge("sharipovai_paper_reserve", "Current paper-account protected reserve")
BACKTEST_RUNS = Counter("sharipovai_backtest_runs_total", "Completed backtest runs")
BACKTEST_FAILURES = Counter("sharipovai_backtest_failures_total", "Failed backtest runs")
BACKTEST_DURATION = Histogram("sharipovai_backtest_duration_seconds", "Backtest runtime in seconds")
BACKTEST_RETURN = Gauge("sharipovai_backtest_last_return_percent", "Last completed backtest return percent")
BACKTEST_DRAWDOWN = Gauge("sharipovai_backtest_last_max_drawdown_percent", "Last completed backtest maximum drawdown percent")
BACKTEST_FEES = Gauge("sharipovai_backtest_last_fees", "Last completed backtest fees")
BACKTEST_FUNDING = Gauge("sharipovai_backtest_last_funding_cost", "Last completed backtest funding cost")
HISTORICAL_DATA_VALID = Gauge(
    "sharipovai_historical_data_valid",
    "1 when the last historical dataset validation passed",
    ("dataset_id",),
)
HISTORICAL_DATA_ROWS = Gauge(
    "sharipovai_historical_data_rows",
    "Rows in the last validated historical dataset",
    ("dataset_id",),
)


def observe_http(*, method: str, path: str, status_code: int, duration_seconds: float) -> None:
    clean_path = _bounded_path(path)
    HTTP_REQUESTS.labels(
        method=str(method).upper(),
        path=clean_path,
        status=str(int(status_code)),
    ).inc()
    HTTP_DURATION.labels(method=str(method).upper(), path=clean_path).observe(
        max(0.0, float(duration_seconds))
    )


def update_runtime_metrics(
    *,
    execution: Mapping[str, Any],
    journal: Mapping[str, Any],
    paper: Mapping[str, Any],
) -> None:
    blocked = not bool(
        execution.get("testnet_execution_enabled")
        or execution.get("live_execution_enabled")
    )
    EXECUTION_BLOCKED.set(1 if blocked else 0)
    EXECUTION_JOURNAL_RECORDS.set(
        _number(journal.get("record_count", journal.get("records", 0)))
    )
    PAPER_EQUITY.set(_number(paper.get("equity")))
    PAPER_CASH.set(_number(paper.get("cash")))
    PAPER_NET_PNL.set(_number(paper.get("net_pnl")))
    PAPER_EXPOSURE_PERCENT.set(
        _number(
            paper.get(
                "capital_utilization_percent",
                paper.get("exposure_percent", 0.0),
            )
        )
    )
    PAPER_RESERVE.set(_number(paper.get("reserve_amount")))


def record_backtest_result(result: Any) -> None:
    BACKTEST_RUNS.inc()
    duration = _number(getattr(result, "metadata", {}).get("duration_seconds", 0.0))
    BACKTEST_DURATION.observe(max(0.0, duration))
    BACKTEST_RETURN.set(_number(getattr(result, "return_percent", 0.0)))
    BACKTEST_DRAWDOWN.set(_number(getattr(result, "max_drawdown_percent", 0.0)))
    BACKTEST_FEES.set(_number(getattr(result, "total_fees", 0.0)))
    BACKTEST_FUNDING.set(_number(getattr(result, "total_funding_cost", 0.0)))


def record_backtest_failure() -> None:
    BACKTEST_FAILURES.inc()


def record_dataset_validation(report: Any) -> None:
    dataset_id = str(getattr(report, "dataset_id", "unknown") or "unknown")[:128]
    valid = bool(getattr(report, "valid", False))
    rows = _number(getattr(report, "row_count", 0))
    HISTORICAL_DATA_VALID.labels(dataset_id=dataset_id).set(1 if valid else 0)
    HISTORICAL_DATA_ROWS.labels(dataset_id=dataset_id).set(rows)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _bounded_path(path: str) -> str:
    value = str(path or "/")
    return value[:200]


__all__ = [
    "observe_http",
    "record_backtest_failure",
    "record_backtest_result",
    "record_dataset_validation",
    "update_runtime_metrics",
]
