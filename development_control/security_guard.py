"""Typed adapter over the parser-based development patch Security Guard."""
from __future__ import annotations

from .models import PatchVerdict
from .patch_policy import (
    PROTECTED_EXACT,
    PROTECTED_PREFIXES,
    PatchParseError,
    is_protected_path,
    parse_unified_diff,
)
from .security_guard_engine import SecurityGuard as _ParserSecurityGuard


class SecurityGuard:
    """Return the canonical typed verdict while using the strict parser engine."""

    def __init__(self) -> None:
        self._engine = _ParserSecurityGuard()

    def evaluate(self, patch: str | bytes) -> PatchVerdict:
        raw = self._engine.evaluate(patch)
        protected_paths = _protected_paths(patch)
        return PatchVerdict(
            allowed=bool(raw.allowed),
            reasons=list(raw.reasons),
            policy_version="development-v2",
            protected_paths=protected_paths,
            required_checks=["security-guard", "targeted-tests", "full-regression"],
            requires_human_approval=bool(protected_paths and not raw.allowed),
        )

    def check(self, patch: str | bytes) -> PatchVerdict:
        return self.evaluate(patch)

    def validate(self, patch: str | bytes) -> PatchVerdict:
        return self.evaluate(patch)

    def __call__(self, patch: str | bytes) -> PatchVerdict:
        return self.evaluate(patch)


_DEFAULT_GUARD = SecurityGuard()


def evaluate_patch(patch: str | bytes) -> PatchVerdict:
    return _DEFAULT_GUARD.evaluate(patch)


def validate_patch(patch: str | bytes) -> PatchVerdict:
    return evaluate_patch(patch)


def _protected_paths(patch: str | bytes) -> list[str]:
    if isinstance(patch, bytes):
        try:
            text = patch.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return []
    elif isinstance(patch, str):
        text = patch
    else:
        return []
    try:
        sections = parse_unified_diff(text)
    except PatchParseError:
        return []
    return list(
        dict.fromkeys(
            candidate
            for section in sections
            for candidate in section.paths
            if is_protected_path(candidate)
        )
    )


__all__ = [
    "PROTECTED_EXACT",
    "PROTECTED_PREFIXES",
    "PatchVerdict",
    "SecurityGuard",
    "evaluate_patch",
    "validate_patch",
]
