from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.global_auth_guard import install_global_auth_guard
from dashboard.release_status_api import install_release_status_api, release_status


def test_release_status_reports_exact_sha_and_fail_closed_flags(monkeypatch) -> None:
    sha = "a" * 40
    monkeypatch.setenv("SHARIPOVAI_BUILD_SHA", sha)
    monkeypatch.setenv("SHARIPOVAI_BUILD_DATE", "2026-07-24T12:00:00Z")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")
    monkeypatch.setenv("SHARIPOVAI_DATABASE_REQUIRED", "1")
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "0")
    monkeypatch.setenv("FEATURE_BYBIT_PRIVATE_ORDER_WS", "0")
    monkeypatch.setenv("RUNTIME_FILL_HARVESTER_ENABLED", "0")
    monkeypatch.setenv("SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED", "0")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("FEATURE_BYBIT_LIVE_EXECUTION", "0")

    report = release_status()

    assert report == {
        "status": "ok",
        "release_sha": sha,
        "build_date": "2026-07-24T12:00:00Z",
        "environment": "production",
        "auth_enabled": True,
        "database_required": True,
        "exchange_mode": "sandbox",
        "mainnet_execution_compiled": False,
        "execution_kill_switch": True,
        "testnet_execution_enabled": False,
        "autonomous_testnet_enabled": False,
        "autonomous_testnet_bridge_enabled": False,
        "private_order_stream_enabled": False,
        "runtime_fill_harvester_enabled": False,
        "scheduled_campaign_orchestrator_enabled": False,
        "live_execution_enabled": False,
    }


def test_release_status_rejects_invalid_sha(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_BUILD_SHA", "not-a-release-sha")
    assert release_status()["release_sha"] == "unknown"


def test_release_status_is_public_but_other_api_remains_protected(monkeypatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")
    monkeypatch.setenv("SHARIPOVAI_BUILD_SHA", "b" * 40)

    app = FastAPI()
    install_release_status_api(app)

    @app.get("/api/protected-probe")
    async def protected_probe() -> dict[str, str]:
        return {"status": "unsafe"}

    install_global_auth_guard(app)
    client = TestClient(app)

    release = client.get("/api/release/status")
    protected = client.get("/api/protected-probe")

    assert release.status_code == 200
    assert release.json()["release_sha"] == "b" * 40
    assert release.headers["cache-control"] == "no-store"
    assert protected.status_code == 401
