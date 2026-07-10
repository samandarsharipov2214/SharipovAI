"""Shared persistent memory for all SharipovAI surfaces and agents."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_RETENTION_DAYS = 183
IMPACT_NEWS_RETENTION_DAYS = 365


def default_memory_path() -> Path:
    """Resolve canonical storage without breaking Linux CI or cloud deploys."""

    configured = os.getenv("SHARIPOVAI_UNIFIED_MEMORY_FILE")
    if configured:
        return Path(configured)
    if os.name == "nt":
        return Path(r"D:\SharipovAI\data\unified_memory.json")
    return Path("data/unified_memory.json")


@dataclass(frozen=True, slots=True)
class MemoryItem:
    namespace: str
    key: str
    value: dict[str, Any]
    source: str
    updated_at: int
    expires_at: int
    retention_days: int
    category: str = "general"
    version: int = 1


class UnifiedMemory:
    """Atomic JSON memory shared by Telegram, dashboard and internal agents."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_memory_path()
        self._lock = threading.RLock()

    def put(
        self,
        namespace: str,
        key: str,
        value: dict[str, Any],
        *,
        source: str,
        category: str = "general",
        retention_days: int = DEFAULT_RETENTION_DAYS,
        now: int | None = None,
    ) -> MemoryItem:
        namespace = self._clean(namespace)
        key = self._clean(key)
        if not isinstance(value, dict):
            raise TypeError("UnifiedMemory value must be a dictionary.")
        if retention_days <= 0:
            raise ValueError("retention_days must be positive.")
        timestamp = int(time.time()) if now is None else int(now)
        with self._lock:
            items = self._load()
            identity = f"{namespace}:{key}"
            previous = items.get(identity, {})
            item = MemoryItem(
                namespace=namespace,
                key=key,
                value=value,
                source=self._clean(source),
                updated_at=timestamp,
                expires_at=timestamp + retention_days * 86400,
                retention_days=retention_days,
                category=self._clean(category),
                version=int(previous.get("version", 0)) + 1,
            )
            items[identity] = asdict(item)
            self._write(items)
            return item

    def get(self, namespace: str, key: str) -> MemoryItem | None:
        self.cleanup_expired()
        raw = self._load().get(f"{self._clean(namespace)}:{self._clean(key)}")
        return MemoryItem(**raw) if isinstance(raw, dict) else None

    def list_namespace(self, namespace: str) -> list[MemoryItem]:
        self.cleanup_expired()
        normalized = self._clean(namespace)
        return sorted(
            (MemoryItem(**raw) for raw in self._load().values() if raw.get("namespace") == normalized),
            key=lambda item: (item.updated_at, item.key),
            reverse=True,
        )

    def cleanup_expired(self, *, now: int | None = None) -> int:
        timestamp = int(time.time()) if now is None else int(now)
        with self._lock:
            items = self._load()
            kept = {
                identity: raw
                for identity, raw in items.items()
                if int(raw.get("expires_at", timestamp + 1)) > timestamp
            }
            removed = len(items) - len(kept)
            if removed:
                self._write(kept)
            return removed

    def health(self) -> dict[str, Any]:
        try:
            self.cleanup_expired()
            items = self._load()
            return {
                "ok": True,
                "item_count": len(items),
                "path": str(self.path),
                "default_retention_days": DEFAULT_RETENTION_DAYS,
                "impact_news_retention_days": IMPACT_NEWS_RETENTION_DAYS,
            }
        except Exception as exc:
            return {"ok": False, "item_count": 0, "path": str(self.path), "error": f"{type(exc).__name__}: {exc}"}

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}

    def _write(self, payload: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.path.name, dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _clean(value: str) -> str:
        normalized = str(value).strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("Memory namespace, key and source must not be empty.")
        return normalized
