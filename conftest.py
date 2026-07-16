"""Repository-wide pytest bootstrap for deterministic self-hosted CI.

Every pytest process in GitHub Actions receives a fresh explicitly configured
runtime state. Local developer runs remain untouched. Unsafe execution flags or
unsafe deletion targets stop collection before application modules are imported.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.ci_runtime_state import reset_runtime_state

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_RESET_MARKER = "SHARIPOVAI_CI_STATE_RESET_COMPLETED"
_LOG_MARKER = "SHARIPOVAI_CI_CLEANROOM_REPORT="


def pytest_sessionstart(session: pytest.Session) -> None:
    del session
    if os.getenv("GITHUB_ACTIONS", "").strip().lower() not in _TRUE:
        return
    if os.getenv(_RESET_MARKER, "").strip().lower() in _TRUE:
        return

    cleanroom = os.getenv("SHARIPOVAI_CI_CLEANROOM", "1").strip().lower()
    apply = cleanroom not in _FALSE
    report = reset_runtime_state(apply=apply)
    payload = report.to_dict()
    artifact_directory = Path("artifacts")
    artifact_directory.mkdir(parents=True, exist_ok=True)
    report_path = artifact_directory / f"runtime-state-{os.getpid()}.json"
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    # Targeted and full-suite workflows already retain pytest stdout logs. Emitting
    # compact JSON here preserves the reset evidence even when standalone wildcard
    # artifact collection is unavailable.
    print(_LOG_MARKER + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if report.status != "ok":
        pytest.exit(
            "CI runtime cleanroom blocked pytest collection: "
            + "; ".join(report.violations),
            returncode=2,
        )
    os.environ[_RESET_MARKER] = "1"
