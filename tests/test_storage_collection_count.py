from __future__ import annotations

import pytest

from storage import ProjectDatabase, count_json_items, list_json_items


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    return database


def test_count_json_items_matches_persisted_namespace_without_materializing_payloads(tmp_path) -> None:
    database = _database(tmp_path)
    database.put_json("sample", "a", {"value": 1})
    database.put_json("sample", "b", {"value": 2})
    database.put_json("other", "c", {"value": 3})

    assert count_json_items(database, "sample") == 2
    assert len(list_json_items(database, "sample")) == 2
    assert count_json_items(database, "other") == 1
    assert count_json_items(database, "missing") == 0


def test_count_json_items_rejects_invalid_namespace(tmp_path) -> None:
    database = _database(tmp_path)

    with pytest.raises(ValueError, match="invalid namespace"):
        count_json_items(database, "")
