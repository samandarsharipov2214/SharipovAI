from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from operations_ai import SAFE_RECOVERY_ACTIONS, _recommended_action, cto_report, diagnose_system, heal_system


@pytest.fixture(autouse=True)
def _public_dashboard_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")


def test_doctor_returns_evidence_based_incidents():
    report = diagnose_system()
    assert report["status"] in {"healthy", "degraded"}
    assert report["real_orders_blocked"] is True
    assert report["legacy_paper_autorun_recovery_allowed"] is False
    assert "incident_count" in report["summary"]
    assert "agent_health" in report


def test_heal_does_not_execute_without_explicit_flag():
    report = heal_system(execute_safe_actions=False)
    assert report["executed"] == []
    assert report["real_orders_blocked"] is True


def test_legacy_paper_autorun_is_never_a_safe_recovery_action():
    assert "restart_virtual_account_autorun" not in SAFE_RECOVERY_ACTIONS
    recommendation = _recommended_action(
        {
            "name": "Paper Trading Bot",
            "last_error": "autorun stopped",
        }
    )
    assert recommendation["action_id"] is None
    assert recommendation["automatic_allowed"] is False
    assert "Legacy PaperActivity" in recommendation["title"]


def test_cto_release_gate_never_allows_real_orders():
    report = cto_report()
    assert report["release_gate"]["real_orders_allowed"] is False
    assert report["legacy_paper_autorun_recovery_allowed"] is False
    assert isinstance(report["top_priorities"], list)


def test_operations_endpoints_are_installed():
    client = TestClient(create_app())

    doctor = client.get("/api/operations/doctor")
    cto = client.get("/api/operations/cto")
    heal = client.post("/api/operations/doctor/heal", json={"execute_safe_actions": False})

    assert doctor.status_code == 200
    assert cto.status_code == 200
    assert heal.status_code == 200
    assert doctor.json()["real_orders_blocked"] is True
    assert cto.json()["release_gate"]["real_orders_allowed"] is False
    assert heal.json()["executed"] == []
