"""Temporary read-only diagnostic for the live SharipovAI Telegram integration.

This file is intentionally branch-only and must not be merged.
It never reads container environment variables or secret files.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


BASE = "https://85-137-88-17.sslip.io"
PATHS = ("/health", "/telegram/webhook", "/api/release/status")
UNITS = (
    "sharipovai-agent.timer",
    "sharipovai-agent.service",
    "sharipovai-deploy-watcher.service",
    "sharipovai-self-healing.timer",
    "sharipovai-self-healing.service",
)
_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+", re.IGNORECASE)
_SECRET_RE = re.compile(r"(?i)(secret(?:_token)?|bot_token|authorization)([=: ]+)([^\s,;\"']+)")


def _sanitize(value: str) -> str:
    value = _TOKEN_RE.sub("bot<REDACTED>", value)
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}<REDACTED>", value)


def _run(args: list[str], *, timeout: int = 20) -> dict[str, object]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as exc:
        return {"argv": args[:3], "returncode": None, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "argv": args[:3],
        "returncode": proc.returncode,
        "stdout": _sanitize(proc.stdout[-16000:]),
        "stderr": _sanitize(proc.stderr[-4000:]),
    }


def _get(path: str) -> dict[str, object]:
    url = f"{BASE}{path}"
    request = urllib.request.Request(url, headers={"User-Agent": "SharipovAI-Live-Diagnostic/1.0", "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read(200_000).decode("utf-8", "replace")
            try:
                payload: object = json.loads(body)
            except json.JSONDecodeError:
                payload = body[:2000]
            return {"url": url, "status": int(response.status), "payload": payload, "final_url": response.geturl()}
    except urllib.error.HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", "replace")
        return {"url": url, "status": int(exc.code), "error": body[:2000], "final_url": exc.geturl()}
    except Exception as exc:
        return {"url": url, "status": 0, "error": f"{type(exc).__name__}: {exc}"}


def _unit(unit: str) -> dict[str, object]:
    return {
        "active": _run(["systemctl", "is-active", unit]),
        "enabled": _run(["systemctl", "is-enabled", unit]),
        "show": _run([
            "systemctl", "show", unit,
            "--property=ActiveState,SubState,UnitFileState,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp,LastTriggerUSec,NextElapseUSecRealtime",
            "--no-pager",
        ]),
    }


def _journal(unit: str, since: str) -> dict[str, object]:
    return _run([
        "journalctl", "-u", unit, "--since", since,
        "--no-pager", "--output=short-iso", "-n", "200",
    ], timeout=20)


def _status_file() -> dict[str, object]:
    path = Path("/var/lib/sharipovai-agent/status.json")
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        payload = {"read_error": f"{type(exc).__name__}: {exc}"}
    return {"exists": True, "mtime": stat.st_mtime, "size": stat.st_size, "payload": payload}


def test_live_telegram_runtime_diagnostic() -> None:
    evidence = {
        "http": [_get(path) for path in PATHS],
        "units": {unit: _unit(unit) for unit in UNITS},
        "journals": {
            "deploy_watcher": _journal("sharipovai-deploy-watcher.service", "2026-08-11 00:00:00"),
            "self_healing": _journal("sharipovai-self-healing.service", "2026-08-12 00:00:00"),
            "legacy_agent": _journal("sharipovai-agent.service", "2026-07-25 00:00:00"),
        },
        "agent_status_file": _status_file(),
        "uid": os.getuid(),
    }
    raise AssertionError("LIVE_TELEGRAM_DIAGNOSTIC=" + json.dumps(evidence, ensure_ascii=False, sort_keys=True))
