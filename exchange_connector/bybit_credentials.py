"""Fail-closed separation of Bybit read-only and execution credentials."""
from __future__ import annotations

import os
from dataclasses import dataclass

_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class BybitCredentials:
    api_key: str
    api_secret: str
    profile: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


def account_credentials() -> BybitCredentials:
    return _load(
        key_name="BYBIT_READONLY_API_KEY",
        secret_name="BYBIT_READONLY_API_SECRET",
        profile="live_read_only",
    )


def execution_credentials(mode: str) -> BybitCredentials:
    normalized = str(mode).strip().lower()
    if normalized == "sandbox":
        return _load(
            key_name="BYBIT_TESTNET_API_KEY",
            secret_name="BYBIT_TESTNET_API_SECRET",
            profile="testnet_execution",
        )
    if normalized == "live":
        return _load(
            key_name="BYBIT_MAINNET_API_KEY",
            secret_name="BYBIT_MAINNET_API_SECRET",
            profile="mainnet_execution",
        )
    return BybitCredentials("", "", "disabled")


def private_stream_credentials(environment: str) -> BybitCredentials:
    normalized = str(environment).strip().lower()
    if normalized in {"sandbox", "testnet"}:
        return execution_credentials("sandbox")
    if normalized in {"live", "mainnet", "live_read_only"}:
        return account_credentials()
    return BybitCredentials("", "", "disabled")


def _load(*, key_name: str, secret_name: str, profile: str) -> BybitCredentials:
    api_key = os.getenv(key_name, "").strip()
    api_secret = os.getenv(secret_name, "").strip()
    if bool(api_key) != bool(api_secret):
        raise RuntimeError(f"{profile} credentials are incomplete")
    if api_key and api_secret:
        return BybitCredentials(api_key, api_secret, profile)
    if os.getenv("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS", "0").strip().lower() in _TRUE:
        legacy_key = os.getenv("EXCHANGE_API_KEY", "").strip()
        legacy_secret = os.getenv("EXCHANGE_API_SECRET", "").strip()
        if bool(legacy_key) != bool(legacy_secret):
            raise RuntimeError("legacy exchange credentials are incomplete")
        return BybitCredentials(legacy_key, legacy_secret, f"{profile}_legacy")
    return BybitCredentials("", "", profile)


__all__ = [
    "BybitCredentials",
    "account_credentials",
    "execution_credentials",
    "private_stream_credentials",
]
