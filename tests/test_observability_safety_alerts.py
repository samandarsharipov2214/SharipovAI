from __future__ import annotations

from observability.critical_alerts import CampaignCriticalAlertService
from observability.phase10_performance_alerts import (
    project_activation_alerts,
    project_performance_alerts,
)
from observability.phase9_alerts import phase9_alerts
from storage import ProjectDatabase


def test_phase9_projects_drawdown_profit_factor_source_and_scaling_gates() -> None:
    alerts = phase9_alerts(
        {
            "risk_metrics": {"maximum_drawdown_bps": 251, "profit_factor": 0.8},
            "source_failed_gates": ["source_integrity"],
        },
        [{"status": "blocked"}],
    )
    assert {item["code"] for item in alerts} == {
        "campaign_drawdown_breach",
        "campaign_profit_factor_below_one",
        "campaign_source_gates_failed",
        "scaling_plan_blocked",
    }
    assert sum(item["telegram_eligible"] for item in alerts) == 2


def test_phase9_allows_infinite_profit_factor_without_false_warning() -> None:
    alerts = phase9_alerts(
        {"risk_metrics": {"maximum_drawdown_bps": 0, "profit_factor": "infinity"}},
        [],
    )
    assert alerts == []


def test_phase10_invalid_performance_evidence_fails_closed() -> None:
    alerts = project_performance_alerts(
        {
            "month": "2026-08",
            "maximum_drawdown_bps": float("nan"),
            "net_pnl_usdt": 1,
            "matched_fill_count": 10,
        }
    )
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "critical"
    assert alerts[0]["key"] == "phase10:invalid-performance-evidence:2026-08"


def test_phase10_projects_drawdown_negative_month_and_missing_fills() -> None:
    alerts = project_performance_alerts(
        {
            "month": "2026-08",
            "maximum_drawdown_bps": 300,
            "net_pnl_usdt": -12.5,
            "matched_fill_count": 0,
        },
        drawdown_limit_bps=250,
    )
    assert [item["severity"] for item in alerts] == ["critical", "warning", "warning"]
    assert {item["key"] for item in alerts} == {
        "phase10:monthly-drawdown:2026-08",
        "phase10:negative-month:2026-08",
        "phase10:no-evidence:2026-08",
    }


def test_phase10_rejects_impossible_negative_risk_metrics() -> None:
    alerts = project_performance_alerts(
        {
            "month": "2026-08",
            "maximum_drawdown_bps": -1,
            "net_pnl_usdt": 5,
            "matched_fill_count": 10,
        }
    )
    assert len(alerts) == 1
    assert alerts[0]["key"] == "phase10:negative-risk-evidence:2026-08"
    assert alerts[0]["severity"] == "critical"


def test_phase10_active_expired_authority_is_critical() -> None:
    alerts = project_activation_alerts(
        {"activation_id": "a1", "status": "active", "expires_at_ms": 100},
        now_ms=100,
    )
    assert len(alerts) == 1
    assert alerts[0]["key"] == "phase10:expired-scaling:a1"
    assert alerts[0]["severity"] == "critical"
    assert project_activation_alerts(
        {"activation_id": "a1", "status": "active", "expires_at_ms": 101},
        now_ms=100,
    ) == []


def test_critical_alert_service_deduplicates_resolves_and_reopens(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CRITICAL_ALERT_REPEAT_SECONDS", "900")
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'alerts.db'}")
    deliveries: list[str] = []

    def deliver(record):
        deliveries.append(str(record["code"]))
        return {"status": "test"}

    service = CampaignCriticalAlertService(database, delivery=deliver)
    bad = {"active_campaign_count": 2}

    first = service.evaluate(bad, now_ms=1_000_000)
    assert first["created_count"] == 1
    assert first["delivered_count"] == 1
    assert first["open_count"] == 1

    repeated = service.evaluate(bad, now_ms=1_001_000)
    assert repeated["created_count"] == 0
    assert repeated["delivered_count"] == 0
    assert len(deliveries) == 1

    cleared = service.evaluate({}, now_ms=1_002_000)
    assert cleared["resolved_count"] == 1
    assert cleared["open_count"] == 0

    reopened = service.evaluate(bad, now_ms=1_003_000)
    assert reopened["reopened_count"] == 1
    assert reopened["delivered_count"] == 1
    assert reopened["open_count"] == 1
    assert len(deliveries) == 2

    events = database.list_events("critical_campaign_alert_events", limit=20)
    assert {item["payload"]["action"] for item in events} == {"opened", "resolved", "reopened"}
