"""Strict allowlist for every Bybit HTTP endpoint used with credentials."""
from __future__ import annotations

from urllib.parse import urlparse

_LIVE_HOSTS = {"api.bybit.com", "api.bybit.eu", "api.bybit.nl"}
_TESTNET_HOSTS = {"api-testnet.bybit.com"}


def validate_bybit_base_url(value: str, *, environment: str) -> str:
    clean = str(value).strip().rstrip("/")
    parsed = urlparse(clean)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Bybit base URL must be an HTTPS origin without credentials")
    if parsed.port not in (None, 443) or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Bybit base URL must not contain a custom port, path, query, or fragment")

    mode = str(environment).strip().lower()
    allowed = _TESTNET_HOSTS if mode in {"sandbox", "testnet"} else _LIVE_HOSTS if mode in {"live", "mainnet", "live_read_only"} else set()
    if parsed.hostname.lower() not in allowed:
        raise ValueError(f"Bybit host is not approved for {mode or 'unknown'} mode")
    return f"https://{parsed.hostname.lower()}"


def approved_live_base_urls() -> tuple[str, ...]:
    return tuple(f"https://{host}" for host in sorted(_LIVE_HOSTS))
