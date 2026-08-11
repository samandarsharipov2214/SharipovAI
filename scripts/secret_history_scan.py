"""Scan reachable Git history for high-confidence secret patterns.

This is a defense-in-depth utility. It does not replace provider-side secret
scanning. It intentionally avoids printing the secret value; findings contain
commit, path, line and rule only.
"""
from __future__ import annotations

import argparse
import hashlib
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
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
)

# POSIX ERE prefilter for ``git grep``.  Detailed Python patterns still decide
# findings; this only keeps history scanning proportional to plausible lines.
_COARSE_PATTERN = r"github_pat_|gh[pousr]_|AKIA|PRIVATE KEY|[0-9]{6,12}:|sk-|AIza"

# Scoped historical test fixture: the tuple intentionally pins rule, path and
# non-reversible fingerprint.  Adding an entry is a code-reviewed decision.
ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("github_token", "tests/test_secret_history_scan.py", "4a000a3806c4e01d"),
    }
)


@dataclass(frozen=True)
class Finding:
    commit: str
    path: str
    line: int
    rule: str
    fingerprint: str


def _fingerprint(value: str) -> str:
    """Provide reviewable correlation metadata without emitting a secret."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _allowlisted(*, rule: str, path: str, fingerprint: str) -> bool:
    return (rule, path, fingerprint) in ALLOWLIST


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        stderr=subprocess.DEVNULL,
    )


def scan_history(root: Path, *, max_commits: int | None = None) -> list[Finding]:
    root = root.resolve()
    command = [
        "git", "-C", str(root), "log", "--all", "-G", _COARSE_PATTERN,
        "--format=__SHARIPOVAI_SCAN_COMMIT__%H", "--patch", "--no-ext-diff",
    ]
    if max_commits is not None:
        command.extend(["--max-count", str(max(0, max_commits))])
    result = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("git history diff scan failed")

    findings: list[Finding] = []
    commit = ""
    path = ""
    line_no = 0
    for row in result.stdout.splitlines():
        if row.startswith("__SHARIPOVAI_SCAN_COMMIT__"):
            commit = row.removeprefix("__SHARIPOVAI_SCAN_COMMIT__").strip()
            path = ""
            line_no = 0
        elif row.startswith("+++ b/"):
            path = row[6:]
            line_no = 0
        elif row.startswith("@@"):
            # Added-side hunk position, e.g. ``@@ -1 +5,3 @@``.
            marker = row.split("+", 1)[1].split(" ", 1)[0]
            line_no = int(marker.split(",", 1)[0])
        elif row.startswith("+") and not row.startswith("+++") and commit and path:
            line = row[1:]
            for rule, pattern in RULES:
                for match in pattern.finditer(line):
                    fingerprint = _fingerprint(match.group(0))
                    if not _allowlisted(rule=rule, path=path, fingerprint=fingerprint):
                        findings.append(Finding(commit, path, int(line_no), rule, fingerprint))
            line_no += 1
        elif row.startswith(" ") and line_no:
            line_no += 1
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
