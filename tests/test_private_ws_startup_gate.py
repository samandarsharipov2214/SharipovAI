from __future__ import annotations

from autonomous_trading.startup_reconciliation import StartupExecutionReconciler
from exchange_connector.private_ws_gate import PrivateStreamHealthRepository
from storage import ProjectDatabase


def _database(tmp_path) -> ProjectDatabase:
    return ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")


def _healthy_status(now_ms: int) -> dict[str, object]:
    return {
        "enabled": True,
        "worker_running": True,
        "credentials_configured": True,
        "connected": True,
        "authenticated": True,
        "subscribed": True,
        "ready_at_ms": now_ms - 1_000,
        "last_message_at_ms": 0,
        "last_heartbeat_at_ms": now_ms - 500,
        "last_error": "",
    }


def test_private_stream_gate_accepts_fresh_authenticated_subscription(tmp_path) -> None:
    database = _database(tmp_path)
    gate = PrivateStreamHealthRepository(database=database, environment="testnet")
    gate.record(_healthy_status(10_000_000), recorded_at_ms=10_000_000)

    report = gate.evaluate(
        required=True,
        now_ms=10_000_100,
        maximum_heartbeat_age_seconds=60,
    )

    assert report.ready is True
    assert report.failed_gates == ()


def test_private_stream_gate_blocks_stale_or_missing_health(tmp_path) -> None:
    database = _database(tmp_path)
    gate = PrivateStreamHealthRepository(database=database, environment="testnet")

    missing = gate.evaluate(required=True, now_ms=10_000_000)
    assert missing.ready is False
    assert "private_order_stream_disconnected" in missing.failed_gates

    gate.record(_healthy_status(1_000_000), recorded_at_ms=1_000_000)
    stale = gate.evaluate(
        required=True,
        now_ms=2_000_000,
        maximum_heartbeat_age_seconds=60,
    )
    assert stale.ready is False
    assert "private_order_stream_heartbeat_stale" in stale.failed_gates


def test_startup_reconciliation_requires_private_stream_when_explicit(tmp_path) -> None:
    database = _database(tmp_path)
    gate = PrivateStreamHealthRepository(database=database, environment="testnet")
    blocked = StartupExecutionReconciler(
        database=database,
        private_stream_gate=gate,
        require_private_stream=True,
        environment="testnet",
    ).reconcile()
    assert blocked.restart_safe is False
    assert blocked.private_stream_required is True
    assert blocked.private_stream_ready is False

    now_ms = 10_000_000
    gate.record(_healthy_status(now_ms), recorded_at_ms=now_ms)
    ready = gate.evaluate(required=True, now_ms=now_ms + 100)
    assert ready.ready is True
