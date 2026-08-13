#!/usr/bin/env python3
"""Fail closed for the retired direct GitHub AI-autofix route.

The canonical repair path is ``tools.ai_fixer.AIFixer`` through the authenticated
internal Gemini endpoint, Security Guard, isolated validation, and the
DevelopmentChangeController owner approval flow.  This legacy workflow helper
may record pytest evidence but must never request a patch from an alternate
provider or apply one directly in a GitHub checkout.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from development_control.security_guard import validate_patch

ROOT = Path.cwd()
PYTEST_LOG = ROOT / "pytest-autofix.log"


def run(
    cmd: list[str], *, timeout: int = 300, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def run_pytest() -> tuple[int, str]:
    proc = run([sys.executable, "-m", "pytest"], timeout=900)
    PYTEST_LOG.write_text(proc.stdout, encoding="utf-8")
    return proc.returncode, proc.stdout


def apply_patch(patch: str) -> bool:
    """Validate a supplied patch but never apply it from this legacy route."""

    if "diff --git" not in patch and "--- " not in patch:
        print("Patch is not a unified diff; refusing legacy autofix.")
        return False
    verdict = validate_patch(patch)
    if not verdict.allowed:
        print("Security Guard rejected legacy autofix patch:")
        for reason in verdict.reasons:
            print(f"  - {reason}")
        return False
    print(
        "Legacy GitHub autofix never applies patches. Use the internal Gemini "
        "AIFixer → Security Guard → owner approval flow."
    )
    return False


def main() -> int:
    task = os.getenv("AI_AUTOFIX_TASK", "Run full pytest, fix failures, preserve SharipovAI product safety and compatibility.")
    print("AI autofix task:")
    print(textwrap.indent(task, "  "))

    code, log = run_pytest()
    print(log[-12000:])
    if code == 0:
        print("pytest already green.")
        return 0
    print(
        "Pytest failed; no patch was requested or applied. Route a bounded "
        "proposal through the internal Gemini and owner-approval pipeline."
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
