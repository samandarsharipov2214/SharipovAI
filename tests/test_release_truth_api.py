from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.release_truth_api import (
    build_release_truth,
    evaluate_release_gate,
    install_release_truth_api,
)


def _safe_release() -> dict[str, object]:
    return {
        "execution_kill_switch": True,
        "mainnet_execution_compiled": False,
        "live_execution_enabled": False,
        "testnet_execution_enabled": False,
        "autonomous_testnet_enabled": False,
        "autonomous_testnet_bridge_enabled": False,
    }


def _healthy_health() -> dict[str, object]:
    return {
        "status": "healthy",
        "checked_at_ms": 1,
        "components": [
            {"component": "storage", "status": "healthy", "evidence": ["free_bytes=99999999999"], "blockers": [], "recovery": []},
            {"component": "backup", "status": "healthy", "evidence": ["age_seconds=10"], "blockers": [], "recovery": []},
        ],
    }


def _green_ci() -> dict[str, object]:
    return {
        "main_sha": "a" * 40,
        "status": "SUCCESS",
        "fresh": True,
        "source": "test",
    }


def test_release_gate_waits_when_required_evidence_is_unknown() -> None:
    gate = evaluate_release_gate(
        release=_safe_release(),
        health={"status": "UNKNOWN", "components": []},
        ci={"main_sha": "UNKNOWN", "status": "UNKNOWN", "fresh": False},
        migration={"known": False, "blockers": []},
    )

    assert gate["verdict"] == "WAIT"
    assert gate["deployment_authority"] is False
    assert gate["owner_action"] is None
    assert "exact main SHA evidence is unavailable" in gate["waiting_reasons"]
    assert "required migration blocker state is unknown" in gate["waiting_reasons"]


def test_release_gate_blocks_on_execution_safety_violation() -> None:
    release = _safe_release()
    release["live_execution_enabled"] = True

    gate = evaluate_release_gate(
        release=release,
        health=_healthy_health(),
        ci=_green_ci(),
        migration={"known": True, "blockers": []},
    )

    assert gate["verdict"] == "BLOCK"
    assert gate["deployment_authority"] is False
    assert any("live execution" in reason for reason in gate["blocking_reasons"])


def test_release_gate_passes_only_with_complete_green_evidence() -> None:
    gate = evaluate_release_gate(
        release=_safe_release(),
        health=_healthy_health(),
        ci=_green_ci(),
        migration={"known": True, "blockers": []},
    )

    assert gate == {
        "verdict": "PASS",
        "reasons": [],
        "blocking_reasons": [],
        "waiting_reasons": [],
        "deployment_authority": False,
        "owner_action": "confirm_production_deploy",
    }


def test_truth_snapshot_preserves_unknowns_instead_of_inventing_v2_proof(monkeypatch) -> None:
    app = FastAPI()

    class HealthCenter:
        def snapshot(self):
            return _healthy_health()

    app.state.system_health_center = HealthCenter()
    app.state.release_gate_ci_evidence = _green_ci()
    app.state.release_gate_migration_evidence = {"known": True, "blockers": [], "source": "test"}

    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("FEATURE_BYBIT_LIVE_EXECUTION", "0")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "0")
    monkeypatch.delenv("SHARIPOVAI_ARCHITECTURE_VERSION", raising=False)
    monkeypatch.delenv("SHARIPOVAI_BUILD_SHA", raising=False)

    truth = build_release_truth(app, now=10.0)

    assert truth["checked_at_ms"] == 10_000
    assert truth["architecture_version"] == "UNKNOWN"
    assert truth["identity"]["production_release_sha"] == "UNKNOWN"
    assert truth["paper_runtime"]["decision_owner"] == "UNKNOWN"
    assert truth["risk_security_veto"]["status"] == "UNKNOWN"
    assert truth["v2_cohort_metrics"]["status"] == "UNKNOWN"
    assert truth["release_gate"]["verdict"] == "PASS"
    assert truth["release_gate"]["deployment_authority"] is False


def test_release_truth_endpoint_is_read_only_and_no_store(monkeypatch) -> None:
    app = FastAPI()
    app.state.release_gate_ci_evidence = {"main_sha": "UNKNOWN", "status": "UNKNOWN", "fresh": False}
    app.state.release_gate_migration_evidence = {"known": False, "blockers": []}
    install_release_truth_api(app)

    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("FEATURE_BYBIT_LIVE_EXECUTION", "0")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "0")

    response = TestClient(app).get("/api/system/release-truth")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["release_gate"]["verdict"] == "WAIT"
    assert payload["release_gate"]["deployment_authority"] is False
