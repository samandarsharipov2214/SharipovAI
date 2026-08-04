"""Declarative fail-closed policy and CLI for unified diff verification."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

PROTECTED_EXACT = frozenset({"constitution.md", "dockerfile", "requirements.txt"})
PROTECTED_PREFIXES = (".github/", "deploy/", "execution/")
TEST_PATH_PARTS = frozenset({"test", "tests"})
TEST_FILE_PREFIXES = ("test_",)
TEST_FILE_SUFFIXES = ("_test.py",)
BINARY_MARKERS = ("GIT binary patch", "Binary files ")
RENAME_OR_COPY_MARKERS = ("rename from ", "rename to ", "copy from ", "copy to ")
SYMLINK_MODE = "120000"

DANGEROUS_ADDITION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("dynamic code execution via eval", re.compile(r"\beval\s*\(")),
    ("dynamic code execution via exec", re.compile(r"\bexec\s*\(")),
    ("shell execution via os.system", re.compile(r"\bos\.system\s*\(")),
    (
        "shell execution via subprocess with shell=True",
        re.compile(r"\bsubprocess\.(?:run|call|check_call|check_output|Popen)\s*\([^\n]*\bshell\s*=\s*True\b"),
    ),
    ("unsafe deserialization via pickle", re.compile(r"\bpickle\.(?:load|loads)\s*\(")),
    ("unsafe YAML loading", re.compile(r"\byaml\.load\s*\((?![^\n]*(?:SafeLoader|safe_load))")),
    ("TLS verification disabled", re.compile(r"\bverify\s*=\s*False\b")),
    ("TLS hostname verification disabled", re.compile(r"\bcheck_hostname\s*=\s*False\b")),
    ("world-writable permissions", re.compile(r"\bchmod\s+(?:-R\s+)?777\b")),
    ("destructive recursive deletion", re.compile(r"\brm\s+-rf\s+(?:/|\$\{?HOME\}?|~)")),
    ("downloaded script piped to a shell", re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:ba|z|k)?sh\b")),
    ("Docker socket access", re.compile(r"(?:/var/run/)?docker\.sock")),
    ("authentication bypass", re.compile(r"SHARIPOVAI_DISABLE_AUTH\s*=\s*['\"]?1")),
    ("real order enablement", re.compile(r"(?:live_execution_enabled|real_orders_blocked)\s*=\s*(?:True|False)")),
)

TEST_WEAKENING_REMOVAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("removed a test function", re.compile(r"^\s*(?:async\s+)?def\s+test_[A-Za-z0-9_]*\s*\(")),
    ("removed an assertion", re.compile(r"\bassert\b|\.assert[A-Z][A-Za-z0-9_]*\s*\(")),
    ("removed an expected-exception check", re.compile(r"\bpytest\.raises\s*\(")),
    ("removed test parametrization", re.compile(r"@pytest\.mark\.parametrize\b")),
)

TEST_WEAKENING_ADDITION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("added pytest.skip", re.compile(r"\bpytest\.skip\s*\(")),
    ("added unittest skip", re.compile(r"@unittest\.skip\b")),
    ("added pytest skip marker", re.compile(r"@pytest\.mark\.skip(?:if)?\b")),
    ("added pytest xfail marker", re.compile(r"@pytest\.mark\.xfail\b")),
    ("added a vacuous assertion", re.compile(r"^\s*assert\s+(?:True|1)\s*(?:#.*)?$")),
)


def normalize_patch_path(raw_path: str) -> str:
    path = raw_path.strip()
    if path == "/dev/null":
        return path
    if not path or "\x00" in path:
        raise ValueError("empty or NUL-containing path")
    if path.startswith('"') or path.endswith('"'):
        raise ValueError("quoted diff paths are not supported")
    if "\\" in path:
        raise ValueError("backslash path separators are not supported")
    if path.startswith(("a/", "b/")):
        path = path[2:]
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("path must be normalized and repository-relative")
    return candidate.as_posix()


def is_protected_path(path: str) -> bool:
    if path == "/dev/null":
        return False
    folded = path.casefold()
    return folded in PROTECTED_EXACT or any(folded.startswith(prefix.casefold()) for prefix in PROTECTED_PREFIXES)


def is_test_path(path: str) -> bool:
    if path == "/dev/null":
        return False
    candidate = PurePosixPath(path)
    folded_parts = {part.casefold() for part in candidate.parts[:-1]}
    name = candidate.name.casefold()
    return bool(folded_parts & TEST_PATH_PARTS) or name.startswith(TEST_FILE_PREFIXES) or name.endswith(TEST_FILE_SUFFIXES)


def _verify_file(path: Path, max_bytes: int) -> tuple[int, dict[str, object]]:
    try:
        stat = path.stat()
        if not path.is_file() or path.is_symlink():
            raise ValueError("patch path must be a regular non-symlink file")
        if stat.st_size <= 0 or stat.st_size > max_bytes:
            raise ValueError(f"patch size must be 1..{max_bytes} bytes")
        patch = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        return 1, {"allowed": False, "reasons": [f"patch read failed: {exc}"]}

    from .security_guard import validate_patch

    verdict = validate_patch(patch)
    return (0 if verdict.allowed else 2), {"allowed": verdict.allowed, "reasons": verdict.reasons}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an approved SharipovAI unified diff")
    parser.add_argument("--verify", metavar="PATCH", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=2 * 1024 * 1024)
    args = parser.parse_args(argv)
    if args.max_bytes < 1:
        parser.error("--max-bytes must be positive")
    code, payload = _verify_file(args.verify, args.max_bytes)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
