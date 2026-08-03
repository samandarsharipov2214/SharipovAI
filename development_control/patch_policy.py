"""Fail-closed policy primitives for proposed source-code patches.

The parser intentionally uses only the Python standard library so the policy can
run inside the production Docker image without Git, a compiler, network access or
additional packages. It parses enough Git/unified diff syntax to identify paths,
content hunks, binary data, copies/renames and file modes. Ambiguous input is
rejected instead of guessed.
"""
from __future__ import annotations

import re
import shlex
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Final, Iterable


PROTECTED_EXACT: Final[frozenset[str]] = frozenset(
    {"CONSTITUTION.md", "Dockerfile", "requirements.txt"}
)
PROTECTED_PREFIXES: Final[tuple[str, ...]] = (
    ".github/",
    "deploy/",
    "execution/",
)
MAX_PATCH_BYTES: Final[int] = 2_000_000

_PROTECTED_EXACT_FOLDED: Final[frozenset[str]] = frozenset(
    item.casefold() for item in PROTECTED_EXACT
)
_PROTECTED_PREFIXES_FOLDED: Final[tuple[str, ...]] = tuple(
    item.casefold() for item in PROTECTED_PREFIXES
)
_BINARY_MARKERS: Final[tuple[str, ...]] = ("GIT binary patch", "Binary files ")
_RENAME_MARKERS: Final[tuple[str, ...]] = (
    "rename from ",
    "rename to ",
    "similarity index ",
    "dissimilarity index ",
)
_COPY_MARKERS: Final[tuple[str, ...]] = ("copy from ", "copy to ")
_MODE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:(?:old|new|new file|deleted file) mode)\s+(?P<mode>[0-7]{6})$"
)
_INDEX_MODE_RE: Final[re.Pattern[str]] = re.compile(
    r"^index\s+[0-9a-fA-F.]+(?:\s+(?P<mode>[0-7]{6}))?$"
)
_HUNK_RE: Final[re.Pattern[str]] = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+"
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@(?:\s.*)?$"
)
_DRIVE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]:")
_NO_NEWLINE_MARKER: Final[str] = r"\ No newline at end of file"


class PatchParseError(ValueError):
    """Raised when a patch cannot be interpreted without ambiguity."""


@dataclass(slots=True)
class PatchVerdict:
    """Security decision returned to patch-producing development agents."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {"allowed": self.allowed, "reasons": list(self.reasons)}


@dataclass(frozen=True, slots=True)
class FilePatch:
    """Normalized evidence extracted from one file section of a patch."""

    old_path: str | None
    new_path: str | None
    added_lines: tuple[str, ...]
    removed_lines: tuple[str, ...]
    metadata: tuple[str, ...]
    modes: tuple[str, ...]
    hunk_count: int
    binary: bool
    rename_or_copy: bool

    @property
    def display_path(self) -> str:
        return self.new_path or self.old_path or "<unknown>"

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(path for path in (self.old_path, self.new_path) if path is not None)

    @property
    def deleted(self) -> bool:
        return self.old_path is not None and self.new_path is None

    @property
    def created(self) -> bool:
        return self.old_path is None and self.new_path is not None

    @property
    def symlink(self) -> bool:
        return "120000" in self.modes


@dataclass(slots=True)
class _SectionBuilder:
    diff_old_path: str | None = None
    diff_new_path: str | None = None
    header_old_path: str | None = None
    header_new_path: str | None = None
    saw_old_header: bool = False
    saw_new_header: bool = False
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)
    metadata: list[str] = field(default_factory=list)
    modes: list[str] = field(default_factory=list)
    hunk_count: int = 0
    binary: bool = False
    rename_or_copy: bool = False
    in_hunk: bool = False
    old_remaining: int = 0
    new_remaining: int = 0

    def start_hunk(self, header: str) -> None:
        match = _HUNK_RE.match(header)
        if match is None:
            raise PatchParseError(f"invalid hunk header: {header!r}")
        if not self.saw_old_header or not self.saw_new_header:
            raise PatchParseError("hunk appeared before ---/+++ file headers")
        if self.in_hunk:
            raise PatchParseError("new hunk started before the previous hunk completed")
        self.old_remaining = int(match.group("old_count") or "1")
        self.new_remaining = int(match.group("new_count") or "1")
        self.hunk_count += 1
        self.in_hunk = True
        self._complete_hunk_if_ready()

    def consume_hunk_line(self, line: str) -> None:
        if not self.in_hunk:
            raise PatchParseError("hunk content appeared outside a hunk")
        if line.startswith("+"):
            self.added_lines.append(line[1:])
            self.new_remaining -= 1
        elif line.startswith("-"):
            self.removed_lines.append(line[1:])
            self.old_remaining -= 1
        elif line.startswith(" "):
            self.old_remaining -= 1
            self.new_remaining -= 1
        elif line == _NO_NEWLINE_MARKER:
            return
        else:
            raise PatchParseError(f"invalid hunk line prefix: {line[:40]!r}")
        if self.old_remaining < 0 or self.new_remaining < 0:
            raise PatchParseError("hunk contains more lines than declared")
        self._complete_hunk_if_ready()

    def _complete_hunk_if_ready(self) -> None:
        if self.old_remaining == 0 and self.new_remaining == 0:
            self.in_hunk = False

    def build(self) -> FilePatch:
        if self.in_hunk or self.old_remaining or self.new_remaining:
            raise PatchParseError("file section ended before the hunk completed")

        old_path = self.header_old_path if self.saw_old_header else self.diff_old_path
        new_path = self.header_new_path if self.saw_new_header else self.diff_new_path
        if old_path is None and new_path is None:
            raise PatchParseError("file section has no usable old or new path")

        if self.saw_old_header and self.header_old_path is not None and self.diff_old_path is not None:
            if self.header_old_path != self.diff_old_path:
                raise PatchParseError(
                    f"old path mismatch: {self.diff_old_path!r} != {self.header_old_path!r}"
                )
        if self.saw_new_header and self.header_new_path is not None and self.diff_new_path is not None:
            if self.header_new_path != self.diff_new_path:
                raise PatchParseError(
                    f"new path mismatch: {self.diff_new_path!r} != {self.header_new_path!r}"
                )

        if old_path is not None and new_path is not None and old_path != new_path:
            self.rename_or_copy = True
        if (
            not self.binary
            and not self.rename_or_copy
            and self.hunk_count == 0
            and not self.modes
        ):
            raise PatchParseError(f"file section has no hunks or mode change: {new_path or old_path}")

        return FilePatch(
            old_path=old_path,
            new_path=new_path,
            added_lines=tuple(self.added_lines),
            removed_lines=tuple(self.removed_lines),
            metadata=tuple(self.metadata),
            modes=tuple(dict.fromkeys(self.modes)),
            hunk_count=self.hunk_count,
            binary=self.binary,
            rename_or_copy=self.rename_or_copy,
        )


def parse_unified_diff(patch: str) -> tuple[FilePatch, ...]:
    """Parse a Git or plain unified diff into normalized file sections.

    The function never applies the patch. Invalid or ambiguous syntax raises
    :class:`PatchParseError` so the caller can deny the proposal.
    """

    if not isinstance(patch, str):
        raise PatchParseError("patch must be text")
    if "\x00" in patch:
        raise PatchParseError("NUL byte is forbidden")
    encoded_size = len(patch.encode("utf-8"))
    if encoded_size == 0:
        raise PatchParseError("patch is empty")
    if encoded_size > MAX_PATCH_BYTES:
        raise PatchParseError(f"patch exceeds {MAX_PATCH_BYTES} bytes")

    lines = patch.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections: list[FilePatch] = []
    current: _SectionBuilder | None = None
    index = 0

    def finish_current() -> None:
        nonlocal current
        if current is not None:
            sections.append(current.build())
            current = None

    while index < len(lines):
        line = lines[index]

        if line.startswith("diff --git "):
            finish_current()
            old_path, new_path = _parse_git_diff_header(line)
            current = _SectionBuilder(diff_old_path=old_path, diff_new_path=new_path)
            index += 1
            continue

        if line.startswith("--- ") and (
            current is None
            or (
                not current.in_hunk
                and current.saw_old_header
                and current.saw_new_header
                and current.hunk_count > 0
            )
        ):
            if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
                raise PatchParseError("plain unified diff is missing +++ header")
            if current is not None:
                finish_current()
            current = _SectionBuilder(
                header_old_path=_parse_file_header_path(line[4:]),
                header_new_path=_parse_file_header_path(lines[index + 1][4:]),
                saw_old_header=True,
                saw_new_header=True,
            )
            index += 2
            continue

        if current is None:
            if line.strip():
                raise PatchParseError(f"unexpected content outside a file section: {line[:80]!r}")
            index += 1
            continue

        if not current.in_hunk and line.startswith("--- "):
            current.header_old_path = _parse_file_header_path(line[4:])
            current.saw_old_header = True
            index += 1
            continue
        if not current.in_hunk and line.startswith("+++ "):
            current.header_new_path = _parse_file_header_path(line[4:])
            current.saw_new_header = True
            index += 1
            continue
        if line.startswith("@@"):
            current.start_hunk(line)
            index += 1
            continue
        if current.in_hunk:
            current.consume_hunk_line(line)
            index += 1
            continue
        if line == _NO_NEWLINE_MARKER:
            index += 1
            continue

        current.metadata.append(line)
        if any(line.startswith(marker) for marker in _BINARY_MARKERS):
            current.binary = True
        if any(line.startswith(marker) for marker in _RENAME_MARKERS + _COPY_MARKERS):
            current.rename_or_copy = True
        mode_match = _MODE_RE.match(line) or _INDEX_MODE_RE.match(line)
        if mode_match and mode_match.groupdict().get("mode"):
            current.modes.append(str(mode_match.group("mode")))
        index += 1

    finish_current()
    if not sections:
        raise PatchParseError("patch contains no file sections")
    return tuple(sections)


def canonicalize_path(raw_path: str) -> str | None:
    """Return a repository-relative POSIX path or ``None`` for ``/dev/null``."""

    value = _decode_path(raw_path.strip())
    if value == "/dev/null":
        return None
    value = unicodedata.normalize("NFKC", value)
    if "\x00" in value:
        raise PatchParseError("path contains NUL")
    if "\\" in value:
        raise PatchParseError(f"backslash path separator is forbidden: {value!r}")
    if value.startswith("/") or value.startswith("//") or _DRIVE_RE.match(value):
        raise PatchParseError(f"absolute path is forbidden: {value!r}")
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]

    normalized_parts: list[str] = []
    for part in PurePosixPath(value).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not normalized_parts:
                raise PatchParseError(f"path escapes repository root: {raw_path!r}")
            normalized_parts.pop()
            continue
        normalized_parts.append(part)
    if not normalized_parts:
        raise PatchParseError(f"empty repository path: {raw_path!r}")
    return "/".join(normalized_parts)


def is_protected_path(path: str) -> bool:
    """Check exact and prefix protections after canonical normalization."""

    folded = path.casefold()
    return folded in _PROTECTED_EXACT_FOLDED or folded.startswith(
        _PROTECTED_PREFIXES_FOLDED
    )


def is_test_path(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1].casefold()
    directory_parts = {part.casefold() for part in parts[:-1]}
    return "tests" in directory_parts or name.startswith("test_") or name.endswith("_test.py")


def is_test_policy_path(path: str) -> bool:
    return path.casefold() in {
        "pyproject.toml",
        "pytest.ini",
        "tox.ini",
        "setup.cfg",
        ".coveragerc",
    }


def unique_reasons(reasons: Iterable[str]) -> list[str]:
    """Preserve policy evaluation order while removing duplicate messages."""

    return list(dict.fromkeys(str(reason) for reason in reasons if str(reason).strip()))


def _parse_git_diff_header(line: str) -> tuple[str, str]:
    raw = line[len("diff --git ") :]
    if "\\" in raw:
        raise PatchParseError("backslash escape/separator is forbidden in diff --git path")
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError as exc:
        raise PatchParseError(f"invalid diff --git header: {exc}") from exc
    if len(tokens) != 2:
        raise PatchParseError("diff --git header must contain exactly two paths")
    return _require_path(tokens[0]), _require_path(tokens[1])


def _parse_file_header_path(raw: str) -> str | None:
    value = raw
    if value.startswith('"'):
        try:
            tokens = shlex.split(value, posix=True)
        except ValueError as exc:
            raise PatchParseError(f"invalid quoted file header: {exc}") from exc
        if len(tokens) != 1:
            raise PatchParseError("quoted file header must contain one path")
        value = tokens[0]
    else:
        value = value.split("\t", 1)[0]
    return canonicalize_path(value)


def _require_path(raw: str) -> str:
    path = canonicalize_path(raw)
    if path is None:
        raise PatchParseError("/dev/null is invalid in diff --git header")
    return path


def _decode_path(value: str) -> str:
    if not value:
        raise PatchParseError("path is empty")
    if value.startswith('"'):
        try:
            tokens = shlex.split(value, posix=True)
        except ValueError as exc:
            raise PatchParseError(f"invalid quoted path: {exc}") from exc
        if len(tokens) != 1:
            raise PatchParseError("quoted path must decode to one value")
        return tokens[0]
    return value


__all__ = [
    "FilePatch",
    "MAX_PATCH_BYTES",
    "PROTECTED_EXACT",
    "PROTECTED_PREFIXES",
    "PatchParseError",
    "PatchVerdict",
    "canonicalize_path",
    "is_protected_path",
    "is_test_path",
    "is_test_policy_path",
    "parse_unified_diff",
    "unique_reasons",
]
