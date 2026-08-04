"""Fail-closed validation for AI-generated unified diff patches."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import PatchVerdict
from .patch_policy import (
    BINARY_MARKERS,
    DANGEROUS_ADDITION_PATTERNS,
    PROTECTED_EXACT,
    PROTECTED_PREFIXES,
    RENAME_OR_COPY_MARKERS,
    SYMLINK_MODE,
    TEST_WEAKENING_ADDITION_PATTERNS,
    TEST_WEAKENING_REMOVAL_PATTERNS,
    is_protected_path,
    is_test_path,
    normalize_patch_path,
)


@dataclass(slots=True)
class _FilePatch:
    old_path: str
    new_path: str
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(path for path in (self.old_path, self.new_path) if path != "/dev/null")

    @property
    def is_test_change(self) -> bool:
        return any(is_test_path(path) for path in self.paths)


class SecurityGuard:
    def validate(self, patch: str) -> PatchVerdict:
        reasons: list[str] = []
        protected_paths: list[str] = []
        if not isinstance(patch, str):
            return self._verdict(["patch must be text"], protected_paths)
        if not patch.strip():
            return self._verdict(["patch is empty"], protected_paths)
        if "\x00" in patch:
            return self._verdict(["binary or NUL-containing patch is forbidden"], protected_paths)
        self._check_global_metadata(patch, reasons)
        files = self._parse_files(patch, reasons)
        if not files:
            reasons.append("patch contains no valid file changes")
        for file_patch in files:
            self._check_file(file_patch, reasons, protected_paths)
        return self._verdict(reasons, protected_paths)

    def check(self, patch: str) -> PatchVerdict:
        return self.validate(patch)

    def __call__(self, patch: str) -> PatchVerdict:
        return self.validate(patch)

    @staticmethod
    def _verdict(reasons: list[str], protected_paths: list[str]) -> PatchVerdict:
        unique_reasons = list(dict.fromkeys(reasons))
        unique_protected = list(dict.fromkeys(protected_paths))
        return PatchVerdict(
            allowed=not unique_reasons,
            reasons=unique_reasons,
            policy_version="development-v2",
            protected_paths=unique_protected,
            required_checks=["security-guard", "targeted-tests", "full-regression"],
            requires_human_approval=False,
        )

    @staticmethod
    def _check_global_metadata(patch: str, reasons: list[str]) -> None:
        if any(marker in patch for marker in BINARY_MARKERS):
            reasons.append("binary patches are forbidden")
        for line in patch.splitlines():
            if line.startswith(RENAME_OR_COPY_MARKERS) or line.startswith("similarity index "):
                reasons.append("renames and copies are forbidden")
            if line.startswith(("old mode ", "new mode ", "new file mode ", "deleted file mode ")) and SYMLINK_MODE in line:
                reasons.append("symlink patches are forbidden")
            if line.startswith(("literal ", "delta ")):
                reasons.append("binary patch payloads are forbidden")

    @staticmethod
    def _parse_files(patch: str, reasons: list[str]) -> list[_FilePatch]:
        files: list[_FilePatch] = []
        current: _FilePatch | None = None
        pending_old: str | None = None
        in_hunk = False
        for line in patch.splitlines():
            if line.startswith("diff --git "):
                in_hunk = False
                pending_old = None
                parts = line.split(" ")
                if len(parts) != 4:
                    reasons.append("malformed diff --git header")
                    current = None
                    continue
                try:
                    current = _FilePatch(normalize_patch_path(parts[2]), normalize_patch_path(parts[3]))
                except ValueError as exc:
                    reasons.append(f"unsafe diff path: {exc}")
                    current = None
                    continue
                files.append(current)
                continue
            if line.startswith("--- "):
                in_hunk = False
                try:
                    pending_old = normalize_patch_path(line[4:].split("\t", 1)[0])
                except ValueError as exc:
                    reasons.append(f"unsafe old path: {exc}")
                    pending_old = None
                continue
            if line.startswith("+++ "):
                in_hunk = False
                try:
                    new_path = normalize_patch_path(line[4:].split("\t", 1)[0])
                except ValueError as exc:
                    reasons.append(f"unsafe new path: {exc}")
                    continue
                if current is None:
                    if pending_old is None:
                        reasons.append("file header is missing an old path")
                        continue
                    current = _FilePatch(pending_old, new_path)
                    files.append(current)
                else:
                    if pending_old is not None and pending_old != current.old_path:
                        reasons.append("diff header old path does not match file header")
                    if new_path != current.new_path:
                        reasons.append("diff header new path does not match file header")
                continue
            if line.startswith("@@"):
                if current is None:
                    reasons.append("hunk appears before a valid file header")
                in_hunk = current is not None
                continue
            if not in_hunk or current is None:
                continue
            if line.startswith("+") and not line.startswith("+++"):
                current.added_lines.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                current.removed_lines.append(line[1:])
        return files

    @staticmethod
    def _check_file(
        file_patch: _FilePatch,
        reasons: list[str],
        protected_paths: list[str],
    ) -> None:
        for path in file_patch.paths:
            if is_protected_path(path):
                reasons.append(f"protected path cannot be modified: {path}")
                protected_paths.append(path)
        if file_patch.is_test_change:
            if file_patch.new_path == "/dev/null":
                reasons.append(f"test file deletion is forbidden: {file_patch.old_path}")
            for line in file_patch.removed_lines:
                for description, pattern in TEST_WEAKENING_REMOVAL_PATTERNS:
                    if pattern.search(line):
                        reasons.append(f"test weakening detected: {description}")
            for line in file_patch.added_lines:
                for description, pattern in TEST_WEAKENING_ADDITION_PATTERNS:
                    if pattern.search(line):
                        reasons.append(f"test weakening detected: {description}")
        for line in file_patch.added_lines:
            for description, pattern in DANGEROUS_ADDITION_PATTERNS:
                if pattern.search(line):
                    reasons.append(f"dangerous construct detected: {description}")


def validate_patch(patch: str) -> PatchVerdict:
    return SecurityGuard().validate(patch)


__all__ = [
    "PROTECTED_EXACT",
    "PROTECTED_PREFIXES",
    "PatchVerdict",
    "SecurityGuard",
    "validate_patch",
]
