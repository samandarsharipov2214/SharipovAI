"""Temporary read-only diagnostic for the live SharipovAI Telegram integration.

This file is intentionally branch-only and must not be merged.
It never reads container environment variables or secret files.
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request


BASE = "https://85-137-88-17.sslip.io"
PATHS = (
    "/health",
    "/telegram/webhook",
    "/api/telegram/status",
    "/api/telegram/self-test",
    "/api/release/status",
)
_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+", re.IGNORECASE)
_SECRET_RE = re.compile(r"(?i)(secret(?:_token)?|token|authorization)([=: ]+)([^\s,;\"']+)")


def _sanitize(value: str) -> str:
    value = _TOKEN_RE.sub("bot<REDACTED>", value)
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}<REDACTED>", value)


def _run(args: list[str], *, timeout: int = 20) -> dict[str, object]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as exc:
        return {"argv": args[:2], "returncode": None, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "argv": args[:2],
        "returncode": proc.returncode,
        "stdout": _sanitize(proc.stdout[-12000:]),
        "stderr": _sanitize(proc.stderr[-4000:]),
    }


def _get(path: str) -> dict[str, object]:
    url = f"{BASE}{path}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SharipovAI-Live-Diagnostic/1.0", "Accept": "application/json"},
        method="GET",
    )
    opener = urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())
    try:
        response = opener.open(request, timeout=15)
        with response:
            body = response.read(1_000_000).decode("utf-8", "replace")
            try:
                payload: object = json.loads(body)
            except json.JSONDecodeError:
                payload = body[:4000]
            return {"url": url, "status": int(response.status), "payload": payload, "final_url": response.geturl()}
    except urllib.error.HTTPError as exc:
        body = exc.read(1_000_000).decode("utf-8", "replace")
        return {"url": url, "status": int(exc.code), "error": body[:4000], "final_url": exc.geturl()}
    except Exception as exc:
        return {"url": url, "status": 0, "error": f"{type(exc).__name__}: {exc}"}


def _filtered_docker_logs(container: str, pattern: str) -> dict[str, object]:
    result = _run(["docker", "logs", "--since", "24h", "--tail", "10000", container], timeout=30)
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    lines = (stdout + "\n" + stderr).splitlines()
    selected = [_sanitize(line) for line in lines if pattern.lower() in line.lower()]
    result["matched_line_count"] = len(selected)
    result["matched_lines_tail"] = selected[-40:]
    result.pop("stdout", None)
    result.pop("stderr", None)
    return result


def test_live_telegram_runtime_diagnostic() -> None:
    evidence = {
        "http": [_get(path) for path in PATHS],
        "watcher": _run(["systemctl", "is-active", "sharipovai-deploy-watcher.service"]),
        "app_inspect": _run([
            "docker", "inspect", "--format",
            "status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{end}} image={{.Config.Image}} id={{.Image}}",
            "sharipovai",
        ]),
        "app_telegram_errors": _filtered_docker_logs("sharipovai", "Telegram webhook processing error"),
        "caddy_webhook_access": _filtered_docker_logs("sharipovai-caddy", "/telegram/webhook"),
    }
    payload = "LIVE_TELEGRAM_DIAGNOSTIC=" + json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    raise AssertionError(payload)
