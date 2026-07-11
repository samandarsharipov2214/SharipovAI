from __future__ import annotations

import httpx
import pytest

from exchange_connector.bybit_retry import BybitRetryError, request_with_safe_get_retries


def _response(status: int, *, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(status, headers=headers, request=httpx.Request("GET", "https://api.bybit.eu/test"))


def test_retries_429_then_returns_success(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_GET_MAX_ATTEMPTS", "3")
    calls = iter([_response(429), _response(200)])
    sleeps: list[float] = []
    result = request_with_safe_get_retries(
        lambda: next(calls), sleep=sleeps.append, random_value=lambda: 0.0
    )
    assert result.status_code == 200
    assert len(sleeps) == 1


def test_does_not_retry_auth_failure() -> None:
    count = 0

    def request() -> httpx.Response:
        nonlocal count
        count += 1
        return _response(401)

    result = request_with_safe_get_retries(request, sleep=lambda _: None)
    assert result.status_code == 401
    assert count == 1


def test_transport_timeout_exhaustion_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_GET_MAX_ATTEMPTS", "99")
    count = 0
    sleeps: list[float] = []

    def request() -> httpx.Response:
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("timeout")

    with pytest.raises(BybitRetryError):
        request_with_safe_get_retries(request, sleep=sleeps.append, random_value=lambda: 0.0)
    assert count == 5
    assert len(sleeps) == 4


def test_retry_after_and_environment_delays_are_hard_capped(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_GET_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("BYBIT_GET_RETRY_BASE_SECONDS", "999")
    monkeypatch.setenv("BYBIT_GET_RETRY_MAX_SECONDS", "999")
    calls = iter([_response(429, retry_after="3600"), _response(200)])
    sleeps: list[float] = []
    result = request_with_safe_get_retries(
        lambda: next(calls), sleep=sleeps.append, random_value=lambda: 1.0
    )
    assert result.status_code == 200
    assert sleeps == [10.0]


def test_negative_or_invalid_retry_after_falls_back_safely(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_GET_MAX_ATTEMPTS", "2")
    for value in ("-5", "not-a-number"):
        calls = iter([_response(503, retry_after=value), _response(200)])
        sleeps: list[float] = []
        result = request_with_safe_get_retries(
            lambda: next(calls), sleep=sleeps.append, random_value=lambda: 0.0
        )
        assert result.status_code == 200
        assert sleeps and 0 <= sleeps[0] <= 10
