"""Scan reachable Git history for high-confidence secret patterns.

This is a defense-in-depth utility. It does not replace provider-side secret
scanning. It intentionally avoids printing the secret value; findings contain
commit, path, line and rule only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("telegram_bot_token", re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")),
)


@dataclass(frozen=True)
class Finding:
    commit: str
    path: str
    line: int
    rule: str


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL)


def scan_history(root: Path, *, max_commits: int | None = None) -> list[Finding]:
    root = root.resolve()
    commits = [line.strip() for line in _git(root, "rev-list", "--all").splitlines() if line.strip()]
    if max_commits is not None:
        commits = commits[: max(0, max_commits)]
    findings: list[Finding] = []
    for commit in commits:
        names = [line for line in _git(root, "ls-tree", "-r", "--name-only", commit).splitlines() if line]
        for path in names:
            if path.endswith((".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".sqlite", ".db")):
                continue
            try:
                content = _git(root, "show", f"{commit}:{path}")
            except subprocess.CalledProcessError:
                continue
            for line_no, line in enumerate(content.splitlines(), 1):
                for rule, pattern in RULES:
                    if pattern.search(line):
                        findings.append(Finding(commit, path, line_no, rule))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".", type=Path)
    parser.add_argument("--max-commits", type=int)
    args = parser.parse_args()
    findings = scan_history(args.root, max_commits=args.max_commits)
    print(json.dumps({"status": "blocked" if findings else "ok", "findings": [asdict(item) for item in findings]}, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
