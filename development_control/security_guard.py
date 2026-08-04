"""Fail-closed validation for AI-generated unified diffs."""
from __future__ import annotations

import re

from .models import PatchVerdict

PROTECTED_EXACT = {"CONSTITUTION.md", "Dockerfile", "requirements.txt"}
PROTECTED_PREFIXES = (".github/", "deploy/", "execution/")
_MAX_CHECKED_FILES = 500
_MAX_REASONS = 200
_DANGEROUS = (
    "os.system(",
    "subprocess.Popen(",
    "subprocess.run(",
    "shell=True",
    "eval(",
    "exec(",
    "pickle.loads(",
    "yaml.load(",
    "chmod 777",
    "curl ",
    "wget ",
    "docker.sock",
    "SHARIPOVAI_DISABLE_AUTH",
    "real_orders_blocked = False",
    "live_execution_enabled = True",
)
_TEST_WEAKENING = (
    "@pytest.mark.skip",
    "pytest.skip(",
    "unittest.skip",
    "xfail",
    "assert True",
    "# noqa",
    "# type: ignore",
)
_PATH_RE = re.compile(r"^(?:---|\+\+\+)\s+(?:[ab]/)?(.+)$", re.MULTILINE)


def validate_patch(patch: str) -> PatchVerdict:
    reasons: list[str] = []
    if not isinstance(patch, str):
        return PatchVerdict(
            allowed=False,
            reasons=("patch must be text",),
            checked_files=(),
            risk_level="critical",
        )
    if not patch.strip().startswith("diff --git "):
        reasons.append("patch is not a unified git diff")
    if "GIT binary patch" in patch or "Binary files " in patch:
        reasons.append("binary patches are forbidden")
    if "rename from " in patch or "rename to " in patch or "similarity index " in patch:
        reasons.append("renames are forbidden")
    if "new file mode 120000" in patch or "old mode 120000" in patch:
        reasons.append("symlinks are forbidden")

    paths = sorted(
        {
            path.strip()
            for path in _PATH_RE.findall(patch)
            if path.strip() != "/dev/null"
        }
    )
    if len(paths) > _MAX_CHECKED_FILES:
        reasons.append(
            f"patch changes too many files: {len(paths)} > {_MAX_CHECKED_FILES}"
        )
    checked_files: list[str] = []
    for path in paths[:_MAX_CHECKED_FILES]:
        normalized = path.removeprefix("a/").removeprefix("b/")
        checked_files.append(normalized)
        if normalized in PROTECTED_EXACT or normalized.startswith(PROTECTED_PREFIXES):
            reasons.append(f"protected path: {normalized}")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            reasons.append(f"unsafe path: {normalized}")

    added = "\n".join(
        line[1:]
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    removed = "\n".join(
        line[1:]
        for line in patch.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    for marker in _DANGEROUS:
        if marker in added:
            reasons.append(f"dangerous construct added: {marker}")
    for marker in _TEST_WEAKENING:
        if marker in added:
            reasons.append(f"test weakening added: {marker}")
    if "assert " in removed and "assert " not in added:
        reasons.append("assertions removed without replacement")
    if "test_" in removed and "test_" not in added:
        reasons.append("tests removed without replacement")

    normalized_reasons = _bounded_unique(reasons, _MAX_REASONS)
    return PatchVerdict(
        allowed=not normalized_reasons,
        reasons=normalized_reasons,
        checked_files=tuple(checked_files),
        risk_level="critical" if normalized_reasons else "low",
    )


def _bounded_unique(values: list[str], limit: int) -> tuple[str, ...]:
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    if len(unique) <= limit:
        return tuple(unique)
    omitted = len(unique) - (limit - 1)
    return tuple([*unique[: limit - 1], f"{omitted} additional blocking reasons omitted"])


class SecurityGuard:
    def check(self, patch: str) -> PatchVerdict:
        return validate_patch(patch)


__all__ = [
    "PROTECTED_EXACT",
    "PROTECTED_PREFIXES",
    "PatchVerdict",
    "SecurityGuard",
    "validate_patch",
]
