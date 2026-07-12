import time

from storage import ProjectDatabase, ProjectDomainStore, VersionConflict


def _store(tmp_path):
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    database.initialize()
    return ProjectDomainStore(database)


def test_shared_memory_is_versioned_and_cross_chat_ready(tmp_path):
    store = _store(tmp_path)
    record = store.put_memory(namespace="project", key="architecture", value={"organs": 9})
    assert record.version == 1
    loaded = store.get_memory(namespace="project", key="architecture")
    assert loaded["value"]["value"] == {"organs": 9}
    assert loaded["value"]["confidence"] == 100.0

    updated = store.put_memory(
        namespace="project",
        key="architecture",
        value={"organs": 9, "status": "canonical"},
        expected_version=1,
    )
    assert updated.version == 2

    try:
        store.put_memory(
            namespace="project",
            key="architecture",
            value={"organs": 10},
            expected_version=1,
        )
    except VersionConflict:
        pass
    else:
        raise AssertionError("stale cross-chat write must be blocked")


def test_market_news_portfolio_candidate_execution_and_audit_share_one_db(tmp_path):
    store = _store(tmp_path)

    store.save_market_quote(
        {
            "provider": "bybit",
            "symbol": "BTCUSDT",
            "category": "spot",
            "last_price": 60000,
            "exchange_timestamp_ms": 1_800_000_000_000,
        }
    )
    store.save_news_event(
        {
            "source": "source-a",
            "source_event_id": "event-1",
            "headline": "Verified market event",
        }
    )
    store.save_portfolio_snapshot(
        environment="paper",
        account_key="primary",
        snapshot={"equity": 10000, "positions": []},
        captured_at_ms=1_800_000_000_001,
    )
    store.save_trading_candidate(
        {
            "candidate_id": "candidate-1",
            "environment": "testnet",
            "decision": "BLOCK",
            "symbol": "BTCUSDT",
        }
    )
    store.append_execution_evidence(
        {
            "candidate_id": "candidate-1",
            "order_link_id": "sai_candidate_1",
            "environment": "paper",
            "revision": 1,
            "status": "VirtualFilled",
        }
    )
    store.append_audit(
        event_type="safety-check",
        severity="warning",
        correlation_id="candidate-1",
        payload={"decision": "BLOCK"},
    )

    database = store.database
    assert len(database.list_events("market")) == 1
    assert len(database.list_events("news")) == 1
    assert len(database.list_events("portfolio")) == 1
    assert len(database.list_events("trading_candidates")) == 1
    assert len(database.list_events("execution")) == 1
    assert len(database.list_events("audit")) == 1


def test_existing_market_quote_shape_and_redelivery_are_supported(tmp_path):
    store = _store(tmp_path)
    quote = {
        "source": "bybit",
        "symbol": "ETHUSDT",
        "price": 3000.5,
        "received_at_unix_ms": 1_800_000_000_100,
        "verified": True,
    }
    first = store.save_market_quote(quote)
    second = store.save_market_quote(quote)
    assert first == second
    assert len(store.database.list_events("market")) == 1

    conflicting = dict(quote, price=3001.5)
    try:
        store.save_market_quote(conflicting)
    except ValueError:
        pass
    else:
        raise AssertionError("same event id with changed evidence must be blocked")


def test_portfolio_latest_never_moves_backwards(tmp_path):
    store = _store(tmp_path)
    latest = store.save_portfolio_snapshot(
        environment="testnet",
        account_key="primary",
        snapshot={"equity": 12000},
        captured_at_ms=2000,
    )
    stale = store.save_portfolio_snapshot(
        environment="testnet",
        account_key="primary",
        snapshot={"equity": 9000},
        captured_at_ms=1000,
    )
    assert stale.version == latest.version
    row = store.database.get_json("portfolio", "testnet:primary:latest")
    assert row["value"]["equity"] == 12000
    assert len(store.database.list_events("portfolio")) == 2


def test_wait_is_preserved_and_candidate_events_are_versioned(tmp_path):
    store = _store(tmp_path)
    first = store.save_trading_candidate(
        {"candidate_id": "candidate-wait", "environment": "paper", "decision": "WAIT"}
    )
    second = store.save_trading_candidate(
        {"candidate_id": "candidate-wait", "environment": "paper", "decision": "BLOCK"}
    )
    assert first.version == 1
    assert second.version == 2
    events = store.database.list_events("trading_candidates")
    assert {event["event_id"] for event in events} == {
        "candidate:candidate-wait:v1",
        "candidate:candidate-wait:v2",
    }


def test_incomplete_allow_is_blocked_but_valid_allow_is_stored(tmp_path):
    store = _store(tmp_path)
    try:
        store.save_trading_candidate(
            {"candidate_id": "candidate-bad", "environment": "testnet", "decision": "ALLOW"}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("incomplete ALLOW must be blocked")

    now = int(time.time() * 1000)
    record = store.save_trading_candidate(
        {
            "candidate_id": "candidate-good",
            "symbol": "BTCUSDT",
            "category": "spot",
            "side": "Buy",
            "environment": "testnet",
            "market_timestamp_ms": now - 100,
            "received_timestamp_ms": now - 50,
            "reference_price": 60000.0,
            "data_sources": ["bybit", "binance", "okx"],
            "market_regime": "trend",
            "signal_evidence": ["signal-1"],
            "news_evidence": [],
            "news_assessment_id": "news-1",
            "portfolio_snapshot_id": "portfolio-1",
            "cost_snapshot_id": "cost-1",
            "estimated_fees": 1.0,
            "estimated_slippage": 1.0,
            "risk_score": 20.0,
            "risk_blocks": [],
            "confidence": 80.0,
            "consensus": 80.0,
            "decision": "ALLOW",
            "expires_at_ms": now + 5000,
        }
    )
    assert record.version == 1


def test_non_finite_and_unsafe_values_are_blocked(tmp_path):
    store = _store(tmp_path)

    for bad_price in (float("nan"), float("inf"), 0, -1, True):
        try:
            store.save_market_quote(
                {
                    "provider": "bybit",
                    "symbol": "BTCUSDT",
                    "last_price": bad_price,
                    "exchange_timestamp_ms": 1,
                }
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe price accepted: {bad_price!r}")

    for environment in ("", "production", "live-money"):
        try:
            store.save_trading_candidate(
                {
                    "candidate_id": "candidate-x",
                    "environment": environment,
                    "decision": "BLOCK",
                }
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe environment accepted: {environment!r}")
