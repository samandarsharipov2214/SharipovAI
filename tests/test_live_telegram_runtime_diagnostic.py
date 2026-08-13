"""Temporary read-only diagnostic for the live SharipovAI Telegram integration.

This file is intentionally branch-only and must not be merged.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request


BASE = "https://85-137-88-17.sslip.io"
PATHS = (
    "/health",
    "/api/telegram/status",
    "/api/telegram/self-test",
    "/api/release/status",
)


def _get(path: str) -> dict[str, object]:
    url = f"{BASE}{path}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SharipovAI-Live-Diagnostic/1.0", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read(1_000_000).decode("utf-8", "replace")
            try:
                payload: object = json.loads(body)
            except json.JSONDecodeError:
                payload = body[:4000]
            return {"url": url, "status": int(response.status), "payload": payload}
    except urllib.error.HTTPError as exc:
        body = exc.read(1_000_000).decode("utf-8", "replace")
        return {"url": url, "status": int(exc.code), "error": body[:4000]}
    except Exception as exc:
        return {"url": url, "status": 0, "error": f"{type(exc).__name__}: {exc}"}


def test_live_telegram_runtime_diagnostic() -> None:
    results = [_get(path) for path in PATHS]
    payload = "LIVE_TELEGRAM_DIAGNOSTIC=" + json.dumps(results, ensure_ascii=False, sort_keys=True)
    raise AssertionError(payload)
