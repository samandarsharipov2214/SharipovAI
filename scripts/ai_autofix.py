#!/usr/bin/env python3
"""Run pytest, ask OpenAI for a focused patch, apply it, and retest.

This script is intended for GitHub Actions. It is deliberately conservative:
- it only edits repository files through a unified diff returned by the model;
- it refuses to continue when OPENAI_API_KEY is missing;
- it commits nothing itself; the workflow commits only if files changed;
- it keeps real trading/order execution concerns in the prompt.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path.cwd()
PYTEST_LOG = ROOT / "pytest-autofix.log"
PATCH_FILE = ROOT / "ai-autofix.patch"
MAX_LOG_CHARS = int(os.getenv("AI_AUTOFIX_MAX_LOG_CHARS", "60000"))
MAX_ATTEMPTS = int(os.getenv("AI_AUTOFIX_ATTEMPTS", "2"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")


SYSTEM_PROMPT = """You are an autonomous senior software engineer fixing a private repository.
Return ONLY a unified diff patch. Do not use markdown fences. Do not explain.
Patch must be applicable with `git apply` from repository root.
Do not delete meaningful tests. Update tests only when they are stale because product terminology or backwards-compatible endpoints changed.
Preserve safety: real exchange orders must remain blocked; virtual/paper execution must not place live orders.
Keep user-facing UI in Russian where the current product expects Russian.
Preserve backwards compatibility for /api/paper-activity/* when possible.
"""


def run(cmd: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)


def run_pytest() -> tuple[int, str]:
    proc = run([sys.executable, "-m", "pytest"], timeout=900)
    PYTEST_LOG.write_text(proc.stdout, encoding="utf-8")
    return proc.returncode, proc.stdout


def repo_snapshot() -> str:
    files = [
        ".github/workflows/tests.yml",
        "paper_activity_engine.py",
        "profitability_gate.py",
        "persistence_paths.py",
        "dashboard/paper_activity_api.py",
        "dashboard/bot_communication_api.py",
        "dashboard/demo_state.py",
        "dashboard/static/mini-app-live.js",
        "dashboard/static/mini-app-all-trades.js",
        "dashboard/static/mini-app-agent-persistence.js",
        "tests/test_profitability_gate.py",
        "tests/test_persistence_and_virtual_account.py",
        "dashboard/tests/test_paper_activity_dashboard.py",
        "dashboard/tests/test_bot_chat_persistence_api.py",
    ]
    chunks: list[str] = []
    for path in files:
        p = ROOT / path
        if p.exists() and p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            if len(text) > 12000:
                text = text[:12000] + "\n...TRUNCATED...\n"
            chunks.append(f"\n--- FILE: {path} ---\n{text}")
    return "\n".join(chunks)


def openai_patch(task: str, pytest_log: str, attempt: int) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it in GitHub Settings → Secrets and variables → Actions.")

    trimmed_log = pytest_log[-MAX_LOG_CHARS:]
    prompt = f"""
Task from GitHub Actions:
{task}

Attempt: {attempt}/{MAX_ATTEMPTS}

Full pytest is failing. Fix the repository with a minimal safe patch.
Return only unified diff.

Pytest output tail:
{trimmed_log}

Relevant repository snapshot:
{repo_snapshot()}
"""
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from exc
    content = data["choices"][0]["message"]["content"]
    return strip_fences(content).strip() + "\n"


def strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return text


def apply_patch(patch: str) -> bool:
    if "diff --git" not in patch and "--- " not in patch:
        print("Model did not return a unified diff; skipping apply.")
        print(patch[:2000])
        return False
    PATCH_FILE.write_text(patch, encoding="utf-8")
    check = run(["git", "apply", "--check", str(PATCH_FILE)], timeout=120)
    if check.returncode != 0:
        print("Patch did not apply cleanly:")
        print(check.stdout)
        print(patch[:4000])
        return False
    applied = run(["git", "apply", str(PATCH_FILE)], timeout=120)
    print(applied.stdout)
    return applied.returncode == 0


def main() -> int:
    task = os.getenv("AI_AUTOFIX_TASK", "Run full pytest, fix failures, preserve SharipovAI product safety and compatibility.")
    print("AI autofix task:")
    print(textwrap.indent(task, "  "))

    final_code = 1
    last_log = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        code, log = run_pytest()
        last_log = log
        print(log[-12000:])
        if code == 0:
            print("pytest already green.")
            return 0
        patch = openai_patch(task, log, attempt)
        if not apply_patch(patch):
            break
        final_code, last_log = run_pytest()
        print(last_log[-12000:])
        if final_code == 0:
            print("pytest green after AI patch.")
            return 0
    print("AI autofix finished but pytest is still failing.")
    PYTEST_LOG.write_text(last_log, encoding="utf-8")
    return final_code


if __name__ == "__main__":
    raise SystemExit(main())
