"""Fail-closed preflight checks for the read-only Bybit account connector."""
from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlsplit

import httpx


class BybitPreflightError(RuntimeError):
    """Raised when the Bybit account configuration is unsafe or inconsistent."""


OFFICIAL_MAINNET_HOSTS = frozenset(
    {
        "api.bybit.com",
        "api.bytick.com",
        "api.bybit.nl",
        "api.bybit.tr",
        "api.bybit.kz",
        "api.bybitgeorgia.ge",
        "api.bybit.ae",
        "api.bybit.eu",
        "api.bybit.id",
        "api.moneypartners.co.jp",
        "api2.moneypartners.co.jp",
        "api3.moneypartners.co.jp",
    }
)


def validate_official_bybit_base_url(value: Any) -> str:
    """Return a normalized official HTTPS mainnet endpoint or fail closed."""
    raw = str(value or "").strip()
    if not raw:
        raise BybitPreflightError("Bybit base URL is empty")
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https":
        raise BybitPreflightError("Bybit base URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise BybitPreflightError("Bybit base URL must not contain userinfo")
    if parsed.port not in (None, 443):
        raise BybitPreflightError("Bybit base URL must not use a non-standard port")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise BybitPreflightError("Bybit base URL must not contain path, query, or fragment")
    if host not in OFFICIAL_MAINNET_HOSTS:
        raise BybitPreflightError(f"Bybit host is not in the official allowlist: {host or 'missing'}")
    return f"https://{host}"


def run_bybit_preflight(client: Any) -> dict[str, Any]:
    """Validate every candidate URL before the first network request, then check the key."""
    if not getattr(client, "api_key", "") or not getattr(client, "api_secret", ""):
        raise BybitPreflightError("Bybit account credentials are not configured")

    raw_candidates = list(client._candidate_base_urls())
    if not raw_candidates:
        raise BybitPreflightError("No Bybit account endpoint is configured")

    # Validate the complete list first. One unsafe configured URL blocks the whole
    # operation instead of silently falling back after a possible exfiltration risk.
    candidates = [validate_official_bybit_base_url(value) for value in raw_candidates]

    errors: list[str] = []
    for base_url in candidates:
        try:
            server_time_ms = _fetch_server_time_ms(client, base_url)
            local_time_ms = int(time.time() * 1000)
            clock_skew_ms = abs(local_time_ms - server_time_ms)
            max_clock_skew_ms = min(max(int(os.getenv("BYBIT_MAX_CLOCK_SKEW_MS", "2000")), 250), 10_000)
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
                "read_only": True,
                "uta": True,
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
    if payload.get("time") is not None:
        return int(payload["time"])
    if result.get("timeNano"):
        return int(str(result["timeNano"])) // 1_000_000
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
    min_deadline_day = min(max(int(os.getenv("BYBIT_MIN_KEY_VALIDITY_DAYS", "3")), 0), 30)
    if deadline_day > 0 and deadline_day < min_deadline_day:
        raise BybitPreflightError(f"API key expires too soon: {deadline_day} day(s) remaining")


def _truthy(name: str, *, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}
