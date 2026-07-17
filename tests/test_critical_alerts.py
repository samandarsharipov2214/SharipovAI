from __future__ import annotations

from observability.critical_alerts import CampaignCriticalAlertMonitor, CampaignCriticalAlertService
from storage import ProjectDatabase


def _database(tmp_path):
    return ProjectDatabase(f"sqlite:///{tmp_path / 'alerts.db'}")


def _snapshot(*, active=None, latest=None, active_count=0, errors=None):
    return {
        "active_campaign": active or {},
        "latest_campaign": latest or active or {},
        "active_campaign_count": active_count,
        "plan": {
            "execution": {
                "kill_switch": False,
                "restart_safe": True,
                "status": "ok",
            },
            "private_stream": {"ready": True, "status": "ready"},
        },
        "orchestrator": {"errors": list(errors or [])},
    }


def test_alerts_are_deduplicated_and_resolved(tmp_path) -> None:
    deliveries: list[dict] = []
    service = CampaignCriticalAlertService(
        _database(tmp_path),
        delivery=lambda record: deliveries.append(dict(record)) or {"status": "captured"},
    )
    snapshot = _snapshot(
        active={
            "campaign_id": "campaign_1",
            "status": "running",
            "failed_gates": ["execution_reconciliation_blocked"],
        },
        active_count=1,
    )
    snapshot["plan"]["execution"] = {
        "kill_switch": True,
        "restart_safe": False,
        "status": "blocked",
    }
    snapshot["plan"]["private_stream"] = {"ready": False, "status": "stale"}

    first = service.evaluate(snapshot, now_ms=1_000_000)
    codes = {item["code"] for item in first["open_alerts"]}
    assert codes == {
        "kill_switch_engaged_during_campaign",
        "execution_reconciliation_failure",
        "private_stream_failure",
        "campaign_evidence_integrity_failure",
    }
    assert first["created_count"] == 4
    assert first["delivered_count"] == 4
    assert len(deliveries) == 4

    repeated = service.evaluate(snapshot, now_ms=1_001_000)
    assert repeated["created_count"] == 0
    assert repeated["delivered_count"] == 0
    assert repeated["open_count"] == 4

    healthy = service.evaluate(_snapshot(), now_ms=1_002_000)
    assert healthy["resolved_count"] == 4
    assert healthy["open_count"] == 0


def test_latest_blocked_campaign_and_orchestrator_failure_alert(tmp_path) -> None:
    service = CampaignCriticalAlertService(
        _database(tmp_path),
        delivery=lambda record: {"status": "captured", "code": record["code"]},
    )
    snapshot = _snapshot(
        latest={
            "campaign_id": "campaign_blocked",
            "status": "blocked",
            "failed_gates": ["orphan_execution", "campaign_notional_outside_10_25_usdt"],
        },
        errors=["schedule_1: RuntimeError: reconciliation failed"],
    )

    result = service.evaluate(snapshot, now_ms=2_000_000)
    codes = {item["code"] for item in result["open_alerts"]}
    assert codes == {
        "campaign_blocked",
        "campaign_evidence_integrity_failure",
        "campaign_orchestrator_failure",
    }
    assert result["critical_open_count"] == 2


def test_monitor_is_read_only_and_reports_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CRITICAL_ALERT_MONITOR_ENABLED", "1")
    calls = 0

    def provider():
        nonlocal calls
        calls += 1
        return _snapshot(errors=["orchestrator unavailable"])

    monitor = CampaignCriticalAlertMonitor(
        provider,
        CampaignCriticalAlertService(
            _database(tmp_path),
            delivery=lambda record: {"status": "captured"},
        ),
    )
    result = monitor.tick()
    assert calls == 1
    assert result["open_count"] == 1
    assert monitor.status()["monitor_enabled"] is True
