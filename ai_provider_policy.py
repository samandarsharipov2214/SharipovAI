"""Fail-closed cost policy; remote inference is never an automatic fallback."""
from __future__ import annotations
import ipaddress
import os
from urllib.parse import urlsplit


def provider_policy() -> dict[str, object]:
    mode = os.getenv("AI_PROVIDER_MODE", "offline").strip().lower()
    remote = mode == "external" and os.getenv("AI_REMOTE_LLM_ENABLED", "0") == "1"
    return {"mode": mode, "remote_enabled": remote, "paid_api_required": False,
            "fallback": "deterministic_evidence", "automatic_paid_fallback": False}


def provider_block_reason(url: str) -> str:
    policy = provider_policy()
    if policy["mode"] == "offline":
        return "offline_policy_no_model_requests"
    try:
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            return "invalid_provider_endpoint"
        if policy["mode"] == "local":
            # Literal loopback only: never resolve an untrusted name or reuse
            # remote memory credentials as a local-model fallback.
            if parsed.scheme in {"http", "https"} and ipaddress.ip_address(parsed.hostname).is_loopback:
                return ""
            return "local_provider_requires_loopback"
        if policy["remote_enabled"] and parsed.scheme == "https":
            return ""
    except ValueError:
        return "invalid_provider_endpoint"
    return "external_provider_not_authorized"


def require_provider(url: str) -> None:
    reason = provider_block_reason(url)
    if reason:
        raise RuntimeError(reason)
