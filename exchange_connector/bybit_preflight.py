"""Fail-closed preflight checks for the read-only Bybit account connector."""
from __future__ import annotations

import os
import time
from typing import Any

import httpx


class BybitPreflightError(RuntimeError):
    """Raised when the Bybit account configuration is unsafe or inconsistent."""


def run_bybit_preflight(client: Any) -> dict[str, Any]:
    """Validate endpoint, clock, API-key permissions, and account mode.

    The function performs only GET requests. It never creates, amends, or
    cancels orders. Unsafe or ambiguous configurations fail closed.
    """
    if not getattr(client, "api_key", "") or not getattr(client, "api_secret", ""):
        raise BybitPreflightError("Bybit account credentials are not configured")

    errors: list[str] = []
    for base_url in client._candidate_base_urls():
        try:
            if "testnet" in base_url.lower():
                raise BybitPreflightError("testnet endpoint is not allowed for live read-only account sync")

            server_time_ms = _fetch_server_time_ms(client, base_url)
            local_time_ms = int(time.time() * 1000)
            clock_skew_ms = abs(local_time_ms - server_time_ms)
            max_clock_skew_ms = max(int(os.getenv("BYBIT_MAX_CLOCK_SKEW_MS", "2000")), 250)
            if clock_skew_ms > max_clock_skew_ms:
                raise BybitPreflightError(
                    f"clock skew {clock_skew_ms}ms exceeds allowed {max_clock_skew_ms}ms"
                )

            key_payload = client._private_get(base_url, "/v5/user/query-api", {})
            key_info = key_payload.get("result", {}) or {}
            _validate_key_info(key_info)

            return {
                "status": "ok",
                "base_url": base_url,
                "clock_skew_ms": clock_skew_ms,
                "read_only": int(key_info.get("readOnly", -1)) == 1,
                "uta": int(key_info.get("uta", 0)) == 1,
                "is_master": bool(key_info.get("isMaster", False)),
                "ip_bound": bool(key_info.get("ips") or []),
                "deadline_day": int(key_info.get("deadlineDay", 0) or 0),
                "key_type": int(key_info.get("type", 0) or 0),
                "kyc_region": str(key_info.get("kycRegion", "")),
            }
        except Exception as exc:
            errors.append(f"{base_url}: {type(exc).__name__}: {exc}")

    raise BybitPreflightError("Bybit preflight failed; " + " | ".join(errors))


def _fetch_server_time_ms(client: Any, base_url: str) -> int:
    http_client = getattr(client, "_client", None) or httpx.Client(timeout=getattr(client, "timeout", 10.0))
    close_client = getattr(client, "_client", None) is None
    try:
        response = http_client.get(f"{base_url}/v5/market/time")
        response.raise_for_status()
        payload = response.json()
    finally:
        if close_client:
            http_client.close()

    if int(payload.get("retCode", -1)) != 0:
        raise BybitPreflightError(
            f"server-time request rejected: {payload.get('retMsg', 'unknown error')}"
        )
    result = payload.get("result", {}) or {}
    raw_ms = payload.get("time")
    if raw_ms is not None:
        return int(raw_ms)
    return int(str(result.get("timeSecond", "0"))) * 1000


def _validate_key_info(key_info: dict[str, Any]) -> None:
    if int(key_info.get("readOnly", -1)) != 1:
        raise BybitPreflightError("API key must be read-only for account synchronization")

    permissions = key_info.get("permissions", {}) or {}
    wallet_permissions = {str(value) for value in permissions.get("Wallet", []) or []}
    if "Withdraw" in wallet_permissions:
        raise BybitPreflightError("API key must not have withdrawal permission")

    if int(key_info.get("uta", 0)) != 1:
        raise BybitPreflightError("Bybit Unified Trading Account is required")

    if _truthy("BYBIT_REQUIRE_SUBACCOUNT") and bool(key_info.get("isMaster", False)):
        raise BybitPreflightError("a dedicated Bybit subaccount is required")

    deadline_day = int(key_info.get("deadlineDay", 0) or 0)
    min_deadline_day = max(int(os.getenv("BYBIT_MIN_KEY_VALIDITY_DAYS", "3")), 0)
    if deadline_day > 0 and deadline_day < min_deadline_day:
        raise BybitPreflightError(
            f"API key expires too soon: {deadline_day} day(s) remaining"
        )


def _truthy(name: str, *, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}
