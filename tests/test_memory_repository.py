from __future__ import annotations

import pytest

from memory_engine import FactCreate, MemoryRepository, MemoryStatus, RawLogCreate
from storage import ProjectDatabase


def _repo(tmp_path):
    repository = MemoryRepository(ProjectDatabase(dsn=f"sqlite:///{tmp_path / 'memory.db'}"))
    repository.initialize()
    return repository


def test_raw_logs_are_idempotent(tmp_path):
    repository = _repo(tmp_path)
    payload = RawLogCreate(
        team_id="sharipovai",
        user_id="owner",
        agent_id="learning_engine",
        session_id="fix-1",
        content="Regression fixed",
        source_ref="event:1",
    )

    first = repository.save_raw_log(payload)
    second = repository.save_raw_log(payload)

    assert first.log_id == second.log_id
    assert repository.stats()["raw_logs"] == 1


def test_fact_activation_is_manual_only(tmp_path):
    repository = _repo(tmp_path)
    fact = repository.save_fact(
        FactCreate(
            team_id="sharipovai",
            user_id="owner",
            agent_id="learning_engine",
            session_id="fix-1",
            content="Backup must complete before deployment",
            source_ref="event:1",
        )
    )

    verified = repository.update_fact_status(
        fact.fact_id,
        MemoryStatus.VERIFIED,
        actor="verifier",
        rationale="deterministic checks passed",
    )
    assert verified.status is MemoryStatus.VERIFIED

    with pytest.raises(PermissionError, match="manual approval"):
        repository.update_fact_status(
            fact.fact_id,
            MemoryStatus.ACTIVE,
            actor="automatic",
            rationale="not allowed",
        )

    active = repository.update_fact_status(
        fact.fact_id,
        MemoryStatus.ACTIVE,
        actor="owner",
        rationale="approved through canonical decision ledger",
        manual_approval=True,
    )
    assert active.status is MemoryStatus.ACTIVE


def test_search_returns_only_verified_or_active_facts(tmp_path):
    repository = _repo(tmp_path)
    extracted = repository.save_fact(
        FactCreate(
            team_id="sharipovai",
            user_id="owner",
            agent_id="reviewer",
            session_id="s1",
            content="Always verify the backup before deployment",
            source_ref="event:1",
            embedding=[1.0, 0.0],
        )
    )
    verified = repository.update_fact_status(
        extracted.fact_id,
        MemoryStatus.VERIFIED,
        actor="verifier",
        rationale="verified",
    )

    hits = repository.search_facts(
        "backup deployment",
        agent_id="reviewer",
        user_id="owner",
        team_id="sharipovai",
        query_embedding=[1.0, 0.0],
    )

    assert [item.fact.fact_id for item in hits] == [verified.fact_id]
    assert hits[0].score > 0
