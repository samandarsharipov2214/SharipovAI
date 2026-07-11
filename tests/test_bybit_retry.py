from __future__ import annotations

import httpx
import pytest

from exchange_connector.bybit_retry import BybitRetryError, request_with_safe_get_retries


def _response(status_code: int, *, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else None
    return httpx.Response(
        status_code,
        headers=headers,
        request=httpx.Request("GET", "https://api.bybit.eu/v5/test"),
    )


def test_rate_limit_retries_and_respects_retry_after(monkeypatch):
    monkeypatch.setenv("BYBIT_GET_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("BYBIT_GET_RETRY_MAX_SECONDS", "2")
    responses = iter([_response(429, retry_after="0.5"), _response(200)])
    sleeps: list[float] = []
    calls = 0

    def request():
        nonlocal calls
        calls += 1
        return next(responses)

    response = request_with_safe_get_retries(request, sleep=sleeps.append, random_value=lambda: 0.0)

    assert response.status_code == 200
    assert calls == 2
    assert sleeps == [0.5]


def test_non_retryable_auth_error_returns_immediately(monkeypatch):
    monkeypatch.setenv("BYBIT_GET_MAX_ATTEMPTS", "3")
    calls = 0

    def request():
        nonlocal calls
        calls += 1
        return _response(401)

    response = request_with_safe_get_retries(request, sleep=lambda _: None)

    assert response.status_code == 401
    assert calls == 1


def test_transport_errors_are_bounded(monkeypatch):
    monkeypatch.setenv("BYBIT_GET_MAX_ATTEMPTS", "2")
    calls = 0

    def request():
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout", request=httpx.Request("GET", "https://api.bybit.eu/v5/test"))

    with pytest.raises(BybitRetryError, match="2 attempts"):
        request_with_safe_get_retries(request, sleep=lambda _: None, random_value=lambda: 0.0)

    assert calls == 2


def test_retry_after_is_capped(monkeypatch):
    monkeypatch.setenv("BYBIT_GET_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("BYBIT_GET_RETRY_MAX_SECONDS", "1")
    responses = iter([_response(503, retry_after="30"), _response(200)])
    sleeps: list[float] = []

    response = request_with_safe_get_retries(
        lambda: next(responses),
        sleep=sleeps.append,
        random_value=lambda: 0.0,
    )

    assert response.status_code == 200
    assert sleeps == [1.0]
