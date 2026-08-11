from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.secret_history_scan import scan_history


def _git(root: Path, *args: str) -> None:
    subprocess.check_call(["git", "-C", str(root), *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "ci@example.invalid")
    _git(root, "config", "user.name", "CI")
    return root


def test_secret_history_scan_finds_old_secret_after_file_is_cleaned(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    target = root / "config.txt"
    target.write_text("TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890\n", encoding="utf-8")
    _git(root, "add", "config.txt")
    _git(root, "commit", "-m", "bad history")
    target.write_text("TOKEN=redacted\n", encoding="utf-8")
    _git(root, "add", "config.txt")
    _git(root, "commit", "-m", "clean current tree")

    findings = scan_history(root)
    assert len(findings) == 1
    assert findings[0].path == "config.txt"
    assert findings[0].rule == "github_token"
    assert len(findings[0].fingerprint) == 16
    assert not hasattr(findings[0], "secret")


def test_secret_history_scan_accepts_clean_history(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "README.md").write_text("no credentials here\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "clean")
    assert scan_history(root) == []


def test_secret_history_scan_skips_or_safely_decodes_binary_history(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "logo.bin").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    _git(root, "add", "logo.bin")
    _git(root, "commit", "-m", "binary")

    assert scan_history(root) == []
