from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _patch(path: str, added: str = "value = 2") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        f"+{added}\n"
    )


def _verify(tmp_path: Path, patch: str) -> subprocess.CompletedProcess[str]:
    candidate = tmp_path / "candidate.patch"
    candidate.write_text(patch, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "development_control.patch_policy", "--verify", str(candidate)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_accepts_safe_unified_diff(tmp_path: Path) -> None:
    result = _verify(tmp_path, _patch("app/service.py"))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"allowed": True, "reasons": []}


def test_cli_rejects_protected_and_dangerous_diff(tmp_path: Path) -> None:
    protected = _verify(tmp_path, _patch("deploy/vps/run.sh"))
    assert protected.returncode == 2
    assert json.loads(protected.stdout)["allowed"] is False

    dangerous = _verify(tmp_path, _patch("app/service.py", "os.system(user_input)"))
    assert dangerous.returncode == 2
    assert any("dangerous construct" in reason for reason in json.loads(dangerous.stdout)["reasons"])


def test_cli_fails_closed_for_missing_or_non_utf8_patch(tmp_path: Path) -> None:
    missing = subprocess.run(
        [sys.executable, "-m", "development_control.patch_policy", "--verify", str(tmp_path / "missing.patch")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["allowed"] is False

    binary = tmp_path / "candidate.patch"
    binary.write_bytes(b"\xff\xfe")
    result = subprocess.run(
        [sys.executable, "-m", "development_control.patch_policy", "--verify", str(binary)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
