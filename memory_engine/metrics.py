"""Prometheus metrics for the opt-in Memory Layer."""
from __future__ import annotations

from typing import Any, Callable

from prometheus_client import REGISTRY, Counter, Gauge, Histogram


def _existing_or_create(name: str, factory: Callable[[], Any]) -> Any:
    try:
        return factory()
    except ValueError:
        collector = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
        if collector is None:
            raise
        return collector


_RAW_LOGS = _existing_or_create(
    "sharipovai_memory_raw_logs",
    lambda: Counter(
        "sharipovai_memory_raw_logs_total",
        "Raw memory logs accepted by the passive Memory Layer.",
    ),
)
_FACTS = _existing_or_create(
    "sharipovai_memory_facts",
    lambda: Counter(
        "sharipovai_memory_facts_total",
        "Memory facts persisted by status.",
        ("status",),
    ),
)
_SEARCH_SECONDS = _existing_or_create(
    "sharipovai_memory_search_seconds",
    lambda: Histogram(
        "sharipovai_memory_search_seconds",
        "Time spent retrieving bounded memory context.",
        ("strategy",),
    ),
)
_DUPLICATE_WAIT = _existing_or_create(
    "sharipovai_wait_duplicates",
    lambda: Counter(
        "sharipovai_wait_duplicates_total",
        "Repeated WAIT events suppressed by canonical runtime deduplication.",
    ),
)
_CIRCUIT_OPEN = _existing_or_create(
    "sharipovai_memory_circuit_breaker_open",
    lambda: Gauge(
        "sharipovai_memory_circuit_breaker_open",
        "Whether Memory Layer has disabled itself after bounded failures.",
    ),
)


def record_memory_raw_log() -> None:
    _RAW_LOGS.inc()


def record_memory_fact(status: str) -> None:
    _FACTS.labels(status=str(status)).inc()


def observe_memory_search(seconds: float, strategy: str) -> None:
    _SEARCH_SECONDS.labels(strategy=str(strategy)).observe(max(float(seconds), 0.0))


def record_wait_duplicate() -> None:
    _DUPLICATE_WAIT.inc()


def set_memory_circuit_open(value: bool) -> None:
    _CIRCUIT_OPEN.set(1 if value else 0)


__all__ = [
    "observe_memory_search",
    "record_memory_fact",
    "record_memory_raw_log",
    "record_wait_duplicate",
    "set_memory_circuit_open",
]
