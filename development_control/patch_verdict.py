"""Compatibility facade for the canonical typed patch verdict."""
from __future__ import annotations

from typing import Any

from .models import PatchVerdict as _TypedPatchVerdict


class PatchVerdict(_TypedPatchVerdict):
    """Typed verdict with the original allowed/reasons comparison contract."""

    def to_dict(self) -> dict[str, object]:
        return {"allowed": self.allowed, "reasons": list(self.reasons)}

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, _TypedPatchVerdict):
            return self.allowed == other.allowed and self.reasons == other.reasons
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.allowed, tuple(self.reasons)))


__all__ = ["PatchVerdict"]
