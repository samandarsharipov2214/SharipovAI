#!/usr/bin/env python3
"""Fail-closed validation for production-safe and bounded Testnet VPS modes."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable, Mapping

_TRUE = {"1", "true", "yes", "on"}
_PLACEHOLDER = re.compile(r"(?:replace|change[-_ ]?me|example\.com|your[-_ ]|<.+>)", re.IGNORECASE)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"{path}:{line_number}: invalid key {key!r}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def merge_env(paths: Iterable[Path]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in paths:
        merged.update(read_env(path))
    return merged


def validate(values: Mapping[str, str], mode: str) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []

    def required(name: str) -> str:
        value = str(values.get(name, "")).strip()
        if not value:
            errors.append(f"{name} is required")
        elif _PLACEHOLDER.search(value):
            errors.append(f"{name} still contains a placeholder")
        return value

    def exact(name: str, expected: str) -> None:
        actual = str(values.get(name, "")).strip()
        if actual != expected:
            errors.append(f"{name} must be {expected!r}, got {actual!r}")

    def truthy(name: str) -> bool:
        return str(values.get(name, "0")).strip().lower() in _TRUE

    domain = required("DOMAIN")
    required("AUTH_SECRET")
    required("ADMIN_USERNAME")
    required("ADMIN_PASSWORD")
    if domain and "://" in domain:
        errors.append("DOMAIN must be a hostname without a URL scheme")
    if str(values.get("AUTH_SECRET", "")).strip() and len(str(values["AUTH_SECRET"]).strip()) < 32:
        errors.append("AUTH_SECRET must contain at least 32 characters")
    if str(values.get("ADMIN_PASSWORD", "")).strip() and len(str(values["ADMIN_PASSWORD"]).strip()) < 14:
        errors.append("ADMIN_PASSWORD must contain at least 14 characters")

    exact("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    exact("FEATURE_BYBIT_LIVE_EXECUTION", "0")
    if truthy("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS"):
        errors.append("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS must remain disabled")
    if values.get("BYBIT_MAINNET_API_KEY") or values.get("BYBIT_MAINNET_API_SECRET"):
        errors.append("Mainnet execution credentials are forbidden on this deployment")

    if mode == "production":
        exact("EXECUTION_KILL_SWITCH", "1")
        for name in (
            "TESTNET_EXECUTION_ENABLED",
            "AUTONOMOUS_TESTNET_ENABLED",
            "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
            "FEATURE_BYBIT_TESTNET",
            "FEATURE_BYBIT_PRIVATE_ORDER_WS",
            "RUNTIME_FILL_HARVESTER_ENABLED",
            "SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED",
        ):
            if truthy(name):
                errors.append(f"{name} must be disabled in production-safe mode")
        if str(values.get("PHASE6_TESTNET_RELEASE_GATE", "blocked")).strip().lower() == "green":
            errors.append("PHASE6_TESTNET_RELEASE_GATE cannot be green in production-safe mode")
    elif mode == "testnet-campaign":
        exact("EXCHANGE_MODE", "sandbox")
        exact("EXCHANGE_BASE_URL", "https://api-testnet.bybit.com")
        if str(values.get("PHASE6_TESTNET_RELEASE_GATE", "")).strip().lower() != "green":
            errors.append("PHASE6_TESTNET_RELEASE_GATE must be green for the bounded campaign")
        required("BYBIT_TESTNET_API_KEY")
        required("BYBIT_TESTNET_API_SECRET")
        for name in ("EXECUTION_MAX_NOTIONAL_USDT", "SHADOW_TESTNET_MAX_NOTIONAL_USDT"):
            try:
                value = float(str(values.get(name, "25")).strip())
            except ValueError:
                errors.append(f"{name} must be numeric")
                continue
            if not 10.0 <= value <= 25.0:
                errors.append(f"{name} must be within 10..25 USDT")
        if not truthy("CRITICAL_ALERT_MONITOR_ENABLED"):
            errors.append("CRITICAL_ALERT_MONITOR_ENABLED must be enabled during the campaign")
        if not truthy("ALERT_DELIVERY_ENABLED"):
            warnings.append("ALERT_DELIVERY_ENABLED is off; alerts persist locally but are not delivered externally")
    else:
        errors.append(f"unsupported mode: {mode}")

    return {
        "status": "ok" if not errors else "blocked",
        "mode": mode,
        "errors": errors,
        "warnings": warnings,
        "safe_to_continue": not errors,
        "mainnet_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True, action="append")
    parser.add_argument("--mode", choices=("production", "testnet-campaign"), required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = validate(merge_env(args.env_file), args.mode)
    except (OSError, ValueError) as exc:
        report = {
            "status": "blocked",
            "mode": args.mode,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "warnings": [],
            "safe_to_continue": False,
            "mainnet_enabled": False,
        }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"runtime env validation: {report['status']} ({report['mode']})")
        for error in report["errors"]:
            print(f"ERROR: {error}")
        for warning in report["warnings"]:
            print(f"WARNING: {warning}")
    return 0 if report["safe_to_continue"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
