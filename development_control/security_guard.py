"""Fail-closed validation for unified diff patches."""

from __future__ import annotations

from dataclasses import dataclass, field

from .patch_policy import (
    BINARY_MARKERS,
    DANGEROUS_ADDITION_PATTERNS,
    RENAME_OR_COPY_MARKERS,
    SYMLINK_MODE,
    TEST_WEAKENING_ADDITION_PATTERNS,
    TEST_WEAKENING_REMOVAL_PATTERNS,
    is_protected_path,
    is_test_path,
    normalize_patch_path,
)


@dataclass(slots=True)
class PatchVerdict:
    """Result of a patch validation operation."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)


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
    """Validate unified diffs before an automated system applies them.

    The validator deliberately rejects unsupported or ambiguous patch forms.
    This is safer than attempting to recover from malformed metadata in a
    security boundary.
    """

    def validate(self, patch: str) -> PatchVerdict:
        reasons: list[str] = []

        if not isinstance(patch, str):
            return PatchVerdict(False, ["patch must be text"])
        if not patch.strip():
            return PatchVerdict(False, ["patch is empty"])
        if "\x00" in patch:
            return PatchVerdict(False, ["binary or NUL-containing patch is forbidden"])

        self._check_global_metadata(patch, reasons)
        files = self._parse_files(patch, reasons)

        if not files:
            reasons.append("patch contains no valid file changes")

        for file_patch in files:
            self._check_file(file_patch, reasons)

        return PatchVerdict(allowed=not reasons, reasons=_deduplicate(reasons))

    def __call__(self, patch: str) -> PatchVerdict:
        return self.validate(patch)

    @staticmethod
    def _check_global_metadata(patch: str, reasons: list[str]) -> None:
        for marker in BINARY_MARKERS:
            if marker in patch:
                reasons.append("binary patches are forbidden")
                break

        for line in patch.splitlines():
            if line.startswith(RENAME_OR_COPY_MARKERS):
                reasons.append("renames and copies are forbidden")
            if line.startswith(("old mode ", "new mode ", "new file mode ", "deleted file mode ")):
                if SYMLINK_MODE in line:
                    reasons.append("symlink patches are forbidden")
            if line.startswith(("literal ", "delta ")):
                reasons.append("binary patch payloads are forbidden")

    @staticmethod
    def _parse_files(patch: str, reasons: list[str]) -> list[_FilePatch]:
        lines = patch.splitlines()
        files: list[_FilePatch] = []
        current: _FilePatch | None = None
        in_hunk = False
        pending_old: str | None = None

        for line in lines:
            if line.startswith("diff --git "):
                in_hunk = False
                pending_old = None
                parts = line.split(" ")
                if len(parts) != 4:
                    reasons.append("malformed diff --git header")
                    current = None
                    continue
                try:
                    old_path = normalize_patch_path(parts[2])
                    new_path = normalize_patch_path(parts[3])
                except ValueError as exc:
                    reasons.append(f"unsafe diff path: {exc}")
                    current = None
                    continue
                current = _FilePatch(old_path=old_path, new_path=new_path)
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
                    current = _FilePatch(old_path=pending_old, new_path=new_path)
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
    def _check_file(file_patch: _FilePatch, reasons: list[str]) -> None:
        for path in file_patch.paths:
            if is_protected_path(path):
                reasons.append(f"protected path cannot be modified: {path}")

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
    """Convenience function for one-shot validation."""

    return SecurityGuard().validate(patch)


def _deduplicate(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
