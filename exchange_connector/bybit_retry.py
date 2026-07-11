"""Bounded retry policy for idempotent Bybit GET requests only."""
from __future__ import annotations

import os
import random
import time
from collections.abc import Callable

import httpx

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class BybitRetryError(RuntimeError):
    """Raised when a safe GET request exhausts transport retries."""


def request_with_safe_get_retries(
    request: Callable[[], httpx.Response],
    *,
    sleep: Callable[[float], None] = time.sleep,
    random_value: Callable[[], float] = random.random,
) -> httpx.Response:
    """Retry a caller-provided idempotent GET callback within hard limits.

    The callback must create a fresh timestamp and signature on every attempt.
    This helper is intentionally not parameterized with an HTTP method and is
    never used by order-create/amend/cancel code.
    """
    max_attempts = min(max(int(os.getenv("BYBIT_GET_MAX_ATTEMPTS", "3")), 1), 5)
    base_delay = min(max(float(os.getenv("BYBIT_GET_RETRY_BASE_SECONDS", "0.25")), 0.0), 2.0)
    max_delay = min(max(float(os.getenv("BYBIT_GET_RETRY_MAX_SECONDS", "2.0")), base_delay), 10.0)

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = request()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            sleep(_delay(attempt, base_delay, max_delay, random_value()))
            continue

        if response.status_code not in _RETRYABLE_STATUS_CODES or attempt >= max_attempts:
            return response

        retry_after = _retry_after_seconds(response)
        delay = retry_after if retry_after is not None else _delay(attempt, base_delay, max_delay, random_value())
        sleep(min(max(delay, 0.0), max_delay))

    raise BybitRetryError(
        f"Bybit GET failed after {max_attempts} attempts: {type(last_error).__name__}: {last_error}"
    )


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _delay(attempt: int, base_delay: float, max_delay: float, jitter: float) -> float:
    exponential = base_delay * (2 ** max(attempt - 1, 0))
    bounded_jitter = max(min(float(jitter), 1.0), 0.0)
    return min(exponential + base_delay * bounded_jitter, max_delay)
