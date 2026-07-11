"""Collection helpers for immutable records stored in the canonical project_kv table."""
from __future__ import annotations

import json
from typing import Any

from .project_database import ProjectDatabase


def list_json_items(
    database: ProjectDatabase,
    namespace: str,
    *,
    limit: int | None = None,
    newest_first: bool = False,
) -> list[dict[str, Any]]:
    clean_namespace = str(namespace).strip()
    if not clean_namespace or len(clean_namespace) > 200:
        raise ValueError("invalid namespace")
    order = "DESC" if newest_first else "ASC"
    query = (
        "SELECT item_key, value_json, version, updated_at_ms FROM project_kv "
        f"WHERE namespace = ? ORDER BY updated_at_ms {order}, item_key {order}"
    )
    params: tuple[Any, ...] = (clean_namespace,)
    if limit is not None:
        bounded = min(max(int(limit), 1), 1_000_000)
        query += " LIMIT ?"
        params = (clean_namespace, bounded)
    with database.connect() as connection:
        rows = database._fetchall(connection, query, params)  # package-level repository helper
    return [
        {
            "key": row["item_key"],
            "value": json.loads(row["value_json"]),
            "version": int(row["version"]),
            "updated_at_ms": int(row["updated_at_ms"]),
        }
        for row in rows
    ]


__all__ = ["list_json_items"]
