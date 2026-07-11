from pathlib import Path

import pytest

from database import DatabaseConfigurationError, UnifiedStore, validate_database_url


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "database" / "migrations" / "0001_unified_core.sql"


def test_database_url_is_fail_closed():
    with pytest.raises(DatabaseConfigurationError):
        validate_database_url(None)
    with pytest.raises(DatabaseConfigurationError):
        validate_database_url("")
    with pytest.raises(DatabaseConfigurationError):
        validate_database_url("sqlite:///tmp/test.db")
    with pytest.raises(DatabaseConfigurationError):
        validate_database_url("postgresql://localhost")
    with pytest.raises(DatabaseConfigurationError):
        validate_database_url("postgresql://user:pass@localhost/db#fragment")


def test_database_url_accepts_postgresql_without_exposing_it():
    url = "postgresql://user:secret@localhost:5432/sharipovai?sslmode=require"
    assert validate_database_url(url) == url
    store = UnifiedStore(url)
    assert "secret" not in repr(store)


def test_unified_schema_contains_every_canonical_domain():
    sql = SCHEMA.read_text(encoding="utf-8")
    required_tables = {
        "project_users",
        "conversations",
        "conversation_messages",
        "project_memory",
        "ai_organ_state",
        "market_quotes",
        "news_events",
        "portfolio_snapshots",
        "trading_candidates",
        "execution_journal",
        "private_order_state",
        "audit_events",
    }
    for table in required_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql


def test_schema_preserves_execution_identity_and_fail_closed_constraints():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "order_link_id TEXT NOT NULL UNIQUE" in sql
    assert "candidate_id TEXT NOT NULL REFERENCES trading_candidates" in sql
    assert "CHECK (environment IN ('paper','testnet','mainnet'))" in sql
    assert "CHECK (decision IN ('ALLOW','BLOCK'))" in sql
    assert "CHECK (expires_at > created_at)" in sql
