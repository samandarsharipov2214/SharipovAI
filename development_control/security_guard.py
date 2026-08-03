"""Security Guard for bounded automated development patches.

The guard evaluates a proposed unified diff without applying it. It is
fail-closed, deterministic and standard-library-only so the same decision is
produced in the SharipovAI Docker container and in CI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

from .patch_policy import (
    PROTECTED_EXACT,
    PROTECTED_PREFIXES,
    FilePatch,
    PatchParseError,
    PatchVerdict,
    is_protected_path,
    is_test_path,
    is_test_policy_path,
    parse_unified_diff,
    unique_reasons,
)


@dataclass(frozen=True, slots=True)
class _PatternRule:
    expression: re.Pattern[str]
    reason: str


def _rule(pattern: str, reason: str) -> _PatternRule:
    return _PatternRule(re.compile(pattern, re.IGNORECASE | re.MULTILINE), reason)


_DANGEROUS_RULES: Final[tuple[_PatternRule, ...]] = (
    _rule(r"(?<![.\w])eval\s*\(", "dynamic code execution via eval()"),
    _rule(r"(?<![.\w])exec\s*\(", "dynamic code execution via exec()"),
    _rule(r"(?<![.\w])compile\s*\(", "dynamic code generation via compile()"),
    _rule(r"\bos\.system\s*\(", "shell execution via os.system()"),
    _rule(r"\bos\.popen\s*\(", "shell execution via os.popen()"),
    _rule(
        r"\bsubprocess\.(?:run|Popen|call|check_call|check_output)\s*\([\s\S]{0,600}?\bshell\s*=\s*True\b",
        "subprocess shell=True",
    ),
    _rule(r"\b(?:bash|sh)\s+-c\s+", "shell command interpreter invocation"),
    _rule(r"\b(?:Invoke-Expression|iex)\b", "PowerShell dynamic expression execution"),
    _rule(r"\bpickle\.loads?\s*\(", "unsafe pickle deserialization"),
    _rule(r"\bmarshal\.loads?\s*\(", "unsafe marshal deserialization"),
    _rule(r"\bssl\._create_unverified_context\b", "TLS verification disabled"),
    _rule(r"\bssl\.CERT_NONE\b", "TLS certificate verification disabled"),
    _rule(r"\bcheck_hostname\s*=\s*False\b", "TLS hostname verification disabled"),
    _rule(r"\bverify\s*=\s*False\b", "HTTP TLS verification disabled"),
    _rule(r"\bchmod\s+(?:-R\s+)?0?777\b", "world-writable filesystem permission"),
    _rule(
        r"\bos\.chmod\s*\([\s\S]{0,200}?,\s*0o?777\s*\)",
        "world-writable filesystem permission",
    ),
    _rule(
        r"\brm\s+-rf\s+(?:/|/\*|\$\{?HOME\}?|~)(?:\s|$)",
        "destructive recursive deletion",
    ),
    _rule(
        r"\b(?:curl|wget)\b[^\n|]{0,500}\|\s*(?:sudo\s+)?(?:sh|bash)\b",
        "remote script piped to a shell",
    ),
    _rule(r"\bgit\s+reset\s+--hard\b", "destructive Git reset"),
    _rule(r"\bgit\s+clean\s+-[A-Za-z]*f[A-Za-z]*\b", "destructive Git clean"),
    _rule(r"/var/run/docker\.sock", "Docker socket access"),
    _rule(r"\bMAINNET_EXECUTION_COMPILED\s*=\s*True\b", "Mainnet compile lock enabled"),
    _rule(
        r"\bEXCHANGE_LIVE_TRADING_ENABLED\s*[:=]\s*[\"']?(?:1|true|yes|on)\b",
        "live trading enabled",
    ),
    _rule(
        r"\bLIVE_EXECUTION_MANUAL_UNLOCK\s*[:=]\s*[\"']?(?:1|true|yes|on)\b",
        "live execution unlock enabled",
    ),
    _rule(
        r"\bEXECUTION_KILL_SWITCH\s*[:=]\s*[\"']?(?:0|false|no|off)\b",
        "execution kill switch disabled",
    ),
    _rule(
        r"\bSHARIPOVAI_DISABLE_AUTH\s*[:=]\s*[\"']?(?:1|true|yes|on)\b",
        "authentication bypass enabled",
    ),
    _rule(r"\breal_orders_blocked\s*=\s*False\b", "real-order block disabled"),
    _rule(r"\blive_execution_enabled\s*=\s*True\b", "live execution enabled"),
    _rule(
        r"\bgetattr\s*\([\s\S]{0,200}?,\s*[\"'](?:eval|exec|system|popen)[\"']\s*\)",
        "dangerous callable resolved dynamically",
    ),
    _rule(
        r"\b__import__\s*\(\s*[\"'](?:os|subprocess|pickle|marshal)[\"']\s*\)",
        "dangerous module imported dynamically",
    ),
)

_TEST_DISABLE_RULES: Final[tuple[_PatternRule, ...]] = (
    _rule(r"@pytest\.mark\.(?:skip|skipif|xfail)\b", "pytest skip/xfail marker added"),
    _rule(r"\bpytest\.(?:skip|xfail)\s*\(", "pytest skip/xfail call added"),
    _rule(r"@(?:unittest\.)?(?:skip|skipIf|skipUnless)\b", "unittest skip marker added"),
    _rule(r"\bpytest\.raises\s*\(\s*(?:Exception|BaseException)\b", "over-broad exception expectation added"),
    _rule(r"\bassert\s+(?:True|1)\s*(?:#.*)?$", "vacuous assertion added"),
    _rule(r"#\s*noqa\b", "lint suppression added to a test"),
    _rule(r"#\s*type:\s*ignore\b", "type-check suppression added to a test"),
    _rule(r"#\s*pragma:\s*no\s*cover\b", "coverage suppression added to a test"),
    _rule(
        r"except\s+(?:Exception|BaseException)(?:\s+as\s+\w+)?\s*:\s*(?:#.*\n\s*)?(?:pass|return\b)",
        "broad exception is silently swallowed in a test",
    ),
)

_TEST_POLICY_WEAKENING_RULES: Final[tuple[_PatternRule, ...]] = (
    _rule(
        r"--(?:ignore|ignore-glob|deselect|continue-on-collection-errors)\b",
        "tests excluded from collection",
    ),
    _rule(r"(?:^|\s)-p\s+no:", "pytest plugin disabled"),
    _rule(r"--cov-fail-under(?:=|\s+)0\b", "coverage threshold reduced to zero"),
    _rule(r"\bfail_under\s*=\s*0\b", "coverage threshold reduced to zero"),
    _rule(r"\bcontinue-on-error\s*:\s*true\b", "test failure made non-blocking"),
    _rule(r"\ballow_failures\s*[:=]\s*true\b", "test failures explicitly allowed"),
    _rule(r"\|\|\s*true\b", "test command failure suppressed"),
)

_CRITICAL_REMOVAL_RULES: Final[tuple[_PatternRule, ...]] = (
    _rule(r"\bMAINNET_EXECUTION_COMPILED\s*=\s*False\b", "Mainnet compile lock removed"),
    _rule(r"\bmainnet_hard_blocked\b", "Mainnet hard-block evidence removed"),
    _rule(r"\brequire_admin\s*\(", "administrator authorization check removed"),
    _rule(r"\bhmac\.compare_digest\s*\(", "constant-time credential comparison removed"),
)

_ASSERTION_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\s)(?:assert\b|with\s+pytest\.raises\b|pytest\.raises\s*\(|self\.assert[A-Z]\w*\s*\()"
)
_TEST_DEFINITION_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:async\s+)?def\s+test_[A-Za-z0-9_]*\s*\("
)
_PARAMETRIZE_RE: Final[re.Pattern[str]] = re.compile(r"@pytest\.mark\.parametrize\b")
_EXECUTABLE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".py",
        ".pyi",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".cmd",
        ".bat",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
    }
)
_EXECUTABLE_NAMES: Final[frozenset[str]] = frozenset(
    {"makefile", "procfile", "entrypoint", "entrypoint.sh"}
)
_TEST_CONTRACT_NAMES: Final[frozenset[str]] = frozenset(
    {"conftest.py", "pytest_plugins.py"}
)
_TEST_POLICY_NAMES: Final[frozenset[str]] = frozenset(
    {"noxfile.py"}
)


class SecurityGuard:
    """Evaluate proposed unified diff patches against SharipovAI policy."""

    def evaluate(self, patch: str | bytes) -> PatchVerdict:
        text, input_reasons = _decode_patch(patch)
        if input_reasons:
            return PatchVerdict(allowed=False, reasons=input_reasons)
        try:
            files = parse_unified_diff(text)
        except PatchParseError as exc:
            return PatchVerdict(allowed=False, reasons=[f"malformed patch: {exc}"])

        reasons: list[str] = []
        for file_patch in files:
            reasons.extend(self._evaluate_file(file_patch))
        reasons = unique_reasons(reasons)
        return PatchVerdict(allowed=not reasons, reasons=reasons)

    def check(self, patch: str | bytes) -> PatchVerdict:
        """Backward-compatible alias retained for existing callers."""

        return self.evaluate(patch)

    def _evaluate_file(self, file_patch: FilePatch) -> list[str]:
        reasons: list[str] = []
        path = file_patch.display_path

        for candidate in file_patch.paths:
            if is_protected_path(candidate):
                reasons.append(f"protected path modified: {candidate}")
        if file_patch.binary:
            reasons.append(f"binary patch is forbidden: {path}")
        if file_patch.rename_or_copy:
            source = file_patch.old_path or "/dev/null"
            target = file_patch.new_path or "/dev/null"
            reasons.append(f"rename/copy patch is forbidden: {source} -> {target}")
        if file_patch.symlink:
            reasons.append(f"symlink patch is forbidden: {path}")

        if _should_scan_dangerous_content(path):
            added_text = _policy_text(file_patch.added_lines)
            for rule in _DANGEROUS_RULES:
                if rule.expression.search(added_text):
                    reasons.append(f"dangerous construct in {path}: {rule.reason}")
            if _unsafe_yaml_load(added_text):
                reasons.append(
                    f"dangerous construct in {path}: yaml.load() without SafeLoader"
                )

            removed_text = _policy_text(file_patch.removed_lines)
            for rule in _CRITICAL_REMOVAL_RULES:
                if rule.expression.search(removed_text) and not rule.expression.search(added_text):
                    reasons.append(f"critical safety weakening in {path}: {rule.reason}")

        if any(_is_test_contract_path(candidate) for candidate in file_patch.paths):
            reasons.extend(_test_weakening_reasons(file_patch))
        if any(_is_test_policy_contract_path(candidate) for candidate in file_patch.paths):
            reasons.extend(_test_policy_reasons(file_patch))
        return reasons


_DEFAULT_GUARD: Final[SecurityGuard] = SecurityGuard()


def evaluate_patch(patch: str | bytes) -> PatchVerdict:
    """Evaluate a patch with the default immutable policy."""

    return _DEFAULT_GUARD.evaluate(patch)


def validate_patch(patch: str | bytes) -> PatchVerdict:
    """Backward-compatible function retained for the existing package API."""

    return evaluate_patch(patch)


def _decode_patch(patch: str | bytes) -> tuple[str, list[str]]:
    if isinstance(patch, str):
        if "\x00" in patch:
            return "", ["binary patch is forbidden: NUL byte detected"]
        return patch, []
    if isinstance(patch, bytes):
        if b"\x00" in patch:
            return "", ["binary patch is forbidden: NUL byte detected"]
        try:
            return patch.decode("utf-8", errors="strict"), []
        except UnicodeDecodeError:
            return "", ["binary patch is forbidden: input is not UTF-8 text"]
    return "", [f"patch must be str or bytes, got {type(patch).__name__}"]


def _should_scan_dangerous_content(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.suffix.casefold() in _EXECUTABLE_SUFFIXES or pure.name.casefold() in _EXECUTABLE_NAMES


def _is_test_contract_path(path: str) -> bool:
    return is_test_path(path) or PurePosixPath(path).name.casefold() in _TEST_CONTRACT_NAMES


def _is_test_policy_contract_path(path: str) -> bool:
    return is_test_policy_path(path) or PurePosixPath(path).name.casefold() in _TEST_POLICY_NAMES


def _policy_text(lines: tuple[str, ...]) -> str:
    retained: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        retained.append(line)
    return "\n".join(retained)


def _unsafe_yaml_load(text: str) -> bool:
    for match in re.finditer(
        r"\byaml\.load\s*\((?P<args>[\s\S]{0,500}?)\)",
        text,
        re.IGNORECASE,
    ):
        arguments = match.group("args")
        if not re.search(
            r"(?:SafeLoader|safe_load|Loader\s*=\s*yaml\.SafeLoader)",
            arguments,
        ):
            return True
    return False


def _test_weakening_reasons(file_patch: FilePatch) -> list[str]:
    path = file_patch.display_path
    reasons: list[str] = []
    if file_patch.deleted:
        reasons.append(f"test weakening detected in {path}: test contract deleted")
        return reasons

    added_text = "\n".join(file_patch.added_lines)
    for rule in _TEST_DISABLE_RULES:
        if rule.expression.search(added_text):
            reasons.append(f"test weakening detected in {path}: {rule.reason}")

    removed_assertions = _count_matches(file_patch.removed_lines, _ASSERTION_RE)
    added_assertions = _count_matches(file_patch.added_lines, _ASSERTION_RE)
    if removed_assertions > added_assertions:
        reasons.append(
            f"test weakening detected in {path}: assertions reduced "
            f"from {removed_assertions} removed to {added_assertions} added"
        )

    removed_tests = _count_matches(file_patch.removed_lines, _TEST_DEFINITION_RE)
    added_tests = _count_matches(file_patch.added_lines, _TEST_DEFINITION_RE)
    if removed_tests > added_tests:
        reasons.append(
            f"test weakening detected in {path}: test cases reduced "
            f"from {removed_tests} removed to {added_tests} added"
        )

    removed_parameters = _count_matches(file_patch.removed_lines, _PARAMETRIZE_RE)
    added_parameters = _count_matches(file_patch.added_lines, _PARAMETRIZE_RE)
    if removed_parameters > added_parameters:
        reasons.append(f"test weakening detected in {path}: parametrized coverage reduced")
    return reasons


def _test_policy_reasons(file_patch: FilePatch) -> list[str]:
    path = file_patch.display_path
    if file_patch.deleted:
        return [f"test weakening detected in {path}: test policy file deleted"]

    added_text = "\n".join(file_patch.added_lines)
    reasons = [
        f"test weakening detected in {path}: {rule.reason}"
        for rule in _TEST_POLICY_WEAKENING_RULES
        if rule.expression.search(added_text)
    ]

    protected_keys = ("testpaths", "addopts", "--cov-fail-under", "fail_under")
    for key in protected_keys:
        removed = sum(key.casefold() in line.casefold() for line in file_patch.removed_lines)
        added = sum(key.casefold() in line.casefold() for line in file_patch.added_lines)
        if removed > added:
            reasons.append(f"test weakening detected in {path}: test policy removed: {key}")
    return reasons


def _count_matches(lines: tuple[str, ...], pattern: re.Pattern[str]) -> int:
    count = 0
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        count += bool(pattern.search(line))
    return count


__all__ = [
    "PROTECTED_EXACT",
    "PROTECTED_PREFIXES",
    "PatchVerdict",
    "SecurityGuard",
    "evaluate_patch",
    "validate_patch",
]
