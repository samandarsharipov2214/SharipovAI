from __future__ import annotations

import threading

import pytest

from autonomous_trading.execution_journal import ExecutionJournal


def test_accepted_evidence_is_never_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv("EXECUTION_JOURNAL_DIAGNOSTIC_LIMIT", "100")
    journal = ExecutionJournal(str(tmp_path / "journal.json"))
    journal.append({"status": "accepted", "order_id": "keep-1"})
    for index in range(250):
        journal.append({"status": "blocked_or_error", "index": index})
    journal.append({"status": "accepted", "order_id": "keep-2"})

    rows = journal.load()["orders"]
    accepted = [row for row in rows if row.get("status") == "accepted"]
    assert [row["order_id"] for row in accepted] == ["keep-1", "keep-2"]
    assert len(rows) == 102


def test_corrupt_journal_fails_closed(tmp_path):
    path = tmp_path / "journal.json"
    path.write_text("broken", encoding="utf-8")
    journal = ExecutionJournal(str(path))
    with pytest.raises(RuntimeError, match="unreadable"):
        journal.load()


def test_multiple_instances_do_not_lose_entries(tmp_path):
    path = str(tmp_path / "journal.json")
    first = ExecutionJournal(path)
    second = ExecutionJournal(path)
    threads = [
        threading.Thread(
            target=(first if index % 2 else second).append,
            args=({"status": "accepted", "order_id": str(index)},),
        )
        for index in range(40)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert len(first.load()["orders"]) == 40
