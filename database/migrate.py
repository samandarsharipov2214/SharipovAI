"""Apply SharipovAI database migrations explicitly.

Run with: python -m database.migrate
"""

from __future__ import annotations

from .unified_store import UnifiedStore


def main() -> int:
    store = UnifiedStore()
    store.migrate()
    health = store.health()
    if not health.schema_ready:
        raise RuntimeError("Unified PostgreSQL schema is not ready")
    print("SharipovAI database migration: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
