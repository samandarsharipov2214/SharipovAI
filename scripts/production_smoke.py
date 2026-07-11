"""Read-only production smoke check for the deployed SharipovAI service."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SmokeResult:
    status: str
    base_url: str
    attempts: int
    health: dict[str, Any]
    homepage_status: int
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_smoke(
    base_url: str,
    *,
    attempts: int = 5,
    timeout_seconds: float = 20.0,
    sleep_seconds: float = 5.0,
    opener: Any = urllib.request.urlopen,
) -> SmokeResult:
    base = str(base_url).strip().rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("production base URL must use https")
    attempts = min(max(int(attempts), 1), 10)
    timeout_seconds = min(max(float(timeout_seconds), 1.0), 60.0)
    sleep_seconds = min(max(float(sleep_seconds), 0.0), 60.0)
    last_errors: list[str] = []
    last_health: dict[str, Any] = {}
    homepage_status = 0

    for attempt in range(1, attempts + 1):
        errors: list[str] = []
        try:
            status, payload = _get_json(f"{base}/health", timeout_seconds, opener)
            if status != 200:
                errors.append(f"health HTTP status is {status}")
            last_health = payload
            errors.extend(_validate_health(payload))
        except Exception as exc:
            errors.append(f"health request failed: {type(exc).__name__}: {exc}")

        try:
            homepage_status, body = _get_text(f"{base}/", timeout_seconds, opener)
            if homepage_status != 200:
                errors.append(f"homepage HTTP status is {homepage_status}")
            if "sharipov" not in body.lower():
                errors.append("homepage does not contain SharipovAI identity")
        except Exception as exc:
            errors.append(f"homepage request failed: {type(exc).__name__}: {exc}")

        if not errors:
            return SmokeResult("ok", base, attempt, last_health, homepage_status, ())
        last_errors = errors
        if attempt < attempts and sleep_seconds:
            time.sleep(sleep_seconds)

    return SmokeResult("blocked", base, attempts, last_health, homepage_status, tuple(last_errors))


def _validate_health(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("status") != "ok":
        errors.append("health status is not ok")
    database = payload.get("database")
    if not isinstance(database, dict) or database.get("status") != "ok":
        errors.append("database health is not ok")
    configuration = payload.get("configuration")
    if not isinstance(configuration, dict):
        errors.append("configuration health is missing")
        return errors
    if configuration.get("status") != "ok":
        errors.append("configuration status is not ok")
    if configuration.get("kill_switch") is not True:
        errors.append("execution kill switch is not active")
    if configuration.get("testnet_execution_enabled") is not False:
        errors.append("Testnet execution is unexpectedly enabled")
    if configuration.get("live_execution_enabled") is not False:
        errors.append("Live execution is unexpectedly enabled")
    return errors


def _get_json(url: str, timeout: float, opener: Any) -> tuple[int, dict[str, Any]]:
    status, body = _request(url, timeout, opener)
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("JSON response must be an object")
    return status, payload


def _get_text(url: str, timeout: float, opener: Any) -> tuple[int, str]:
    return _request(url, timeout, opener)


def _request(url: str, timeout: float, opener: Any) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SharipovAI-Production-Smoke/1.0", "Accept": "application/json,text/html"},
        method="GET",
    )
    try:
        response = opener(request, timeout=timeout)
        with response:
            status = int(getattr(response, "status", response.getcode()))
            body = response.read(2_000_000).decode("utf-8", "replace")
            return status, body
    except urllib.error.HTTPError as exc:
        body = exc.read(2_000_000).decode("utf-8", "replace")
        return int(exc.code), body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the deployed SharipovAI service")
    parser.add_argument("--base-url", default="https://sharipovai-bot.onrender.com")
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--sleep", type=float, default=5.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run_smoke(
        args.base_url,
        attempts=args.attempts,
        timeout_seconds=args.timeout,
        sleep_seconds=args.sleep,
    )
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"RESULT: {result.status}; attempts={result.attempts}; errors={len(result.errors)}")
        for error in result.errors:
            print(f"- {error}")
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
