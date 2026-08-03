"""Declarative policy used by :mod:`development_control.security_guard`.

The policy is intentionally conservative. Automated patch application must fail
closed when a diff uses an unsupported representation or touches sensitive
project infrastructure.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

PROTECTED_EXACT = frozenset(
    {
        "constitution.md",
        "dockerfile",
        "requirements.txt",
    }
)

PROTECTED_PREFIXES = (
    ".github/",
    "deploy/",
    "execution/",
)

TEST_PATH_PARTS = frozenset({"test", "tests"})
TEST_FILE_PREFIXES = ("test_",)
TEST_FILE_SUFFIXES = ("_test.py",)

BINARY_MARKERS = (
    "GIT binary patch",
    "Binary files ",
)

RENAME_OR_COPY_MARKERS = (
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
)

SYMLINK_MODE = "120000"

DANGEROUS_ADDITION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("dynamic code execution via eval", re.compile(r"\beval\s*\(")),
    ("dynamic code execution via exec", re.compile(r"\bexec\s*\(")),
    ("shell execution via os.system", re.compile(r"\bos\.system\s*\(")),
    (
        "shell execution via subprocess with shell=True",
        re.compile(
            r"\bsubprocess\.(?:run|call|check_call|check_output|Popen)\s*\([^\n]*\bshell\s*=\s*True\b"
        ),
    ),
    ("unsafe deserialization via pickle", re.compile(r"\bpickle\.(?:load|loads)\s*\(")),
    (
        "unsafe YAML loading",
        re.compile(r"\byaml\.load\s*\((?![^\n]*(?:SafeLoader|safe_load))"),
    ),
    ("TLS verification disabled", re.compile(r"\bverify\s*=\s*False\b")),
    ("TLS hostname verification disabled", re.compile(r"\bcheck_hostname\s*=\s*False\b")),
    ("world-writable permissions", re.compile(r"\bchmod\s+(?:-R\s+)?777\b")),
    ("destructive recursive deletion", re.compile(r"\brm\s+-rf\s+(?:/|\$\{?HOME\}?|~)")),
    (
        "downloaded script piped to a shell",
        re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:ba|z|k)?sh\b"),
    ),
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
    """Return a safe repository-relative POSIX path.

    Git's ``a/`` and ``b/`` prefixes are removed. Unsupported quoting,
    backslashes, absolute paths, NUL bytes and traversal are rejected so a
    caller cannot bypass protected-path matching through alternate syntax.
    """

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
    """Return whether *path* is protected, using case-insensitive matching."""

    if path == "/dev/null":
        return False
    folded = path.casefold()
    return folded in PROTECTED_EXACT or any(
        folded.startswith(prefix.casefold()) for prefix in PROTECTED_PREFIXES
    )


def is_test_path(path: str) -> bool:
    """Return whether *path* conventionally contains tests."""

    if path == "/dev/null":
        return False
    candidate = PurePosixPath(path)
    folded_parts = {part.casefold() for part in candidate.parts[:-1]}
    name = candidate.name.casefold()
    return bool(folded_parts & TEST_PATH_PARTS) or name.startswith(
        TEST_FILE_PREFIXES
    ) or name.endswith(TEST_FILE_SUFFIXES)
