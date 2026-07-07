"""JSON-backed memory engine for SharipovAI OS.

The memory engine stores decision records in a local JSON file. It does not use
AI behavior, trading logic, or a database.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import DecisionRecord


class MemoryEngine:
    """Stores and retrieves decision records from JSON storage."""

    DEFAULT_STORAGE_PATH: Path = Path("memory") / "decisions.json"

    def __init__(self, storage_path: Path | str | None = None) -> None:
        """Initialize the memory engine.

        Args:
            storage_path: Optional JSON file path used for storage. When
                omitted, ``memory/decisions.json`` is used.
        """

        self._storage_path = Path(storage_path or self.DEFAULT_STORAGE_PATH)

    @property
    def storage_path(self) -> Path:
        """Return the JSON storage path."""

        return self._storage_path

    def save(self, record: DecisionRecord) -> None:
        """Save a decision record.

        Existing records with the same ID are replaced to keep record IDs
        unique.

        Args:
            record: Decision record to persist.
        """

        records = self.load_all()
        records_by_id = {item.id: item for item in records}
        records_by_id[record.id] = record
        self._write_records(list(records_by_id.values()))

    def load(self, symbol: str) -> list[DecisionRecord]:
        """Load all records for an exact symbol match.

        Args:
            symbol: Symbol to load.

        Returns:
            Matching decision records.
        """

        normalized_symbol = symbol.upper()
        return [
            record
            for record in self.load_all()
            if record.symbol.upper() == normalized_symbol
        ]

    def load_all(self) -> list[DecisionRecord]:
        """Load all stored decision records.

        Returns:
            All decision records in storage.
        """

        if not self._storage_path.exists():
            return []

        with self._storage_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        if not isinstance(payload, list):
            return []

        return [
            DecisionRecord.from_dict(item)
            for item in payload
            if isinstance(item, dict)
        ]

    def search(self, symbol: str) -> list[DecisionRecord]:
        """Search records by symbol substring.

        Args:
            symbol: Symbol text to search for.

        Returns:
            Matching decision records.
        """

        normalized_symbol = symbol.upper()
        return [
            record
            for record in self.load_all()
            if normalized_symbol in record.symbol.upper()
        ]

    def _write_records(self, records: list[DecisionRecord]) -> None:
        """Write records to JSON storage.

        Args:
            records: Decision records to persist.
        """

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload: list[dict[str, Any]] = [record.to_dict() for record in records]

        with self._storage_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
