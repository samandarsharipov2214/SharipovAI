"""Non-persistent memory sink for the legacy offline runner."""

from __future__ import annotations

from typing import Any


class DiagnosticMemorySink:
    """Discard pre-canonical diagnostic decisions instead of persisting them."""

    storage_path = None

    def save(self, record: Any) -> None:
        del record

    def load(self, symbol: str) -> list[Any]:
        del symbol
        return []

    def load_all(self) -> list[Any]:
        return []

    def search(self, symbol: str) -> list[Any]:
        del symbol
        return []


__all__ = ["DiagnosticMemorySink"]
