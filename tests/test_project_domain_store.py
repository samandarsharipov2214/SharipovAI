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
            "environment": "testnet",
            "revision": 1,
            "status": "Reserved",
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
