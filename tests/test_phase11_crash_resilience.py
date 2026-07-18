from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.admin_guard import install_sensitive_api_guard
from dashboard.phase11_production_api import _AuditCache
from observability.phase10_performance_alerts import (
    project_activation_alerts,
    project_performance_alerts,
)

ROOT = Path(__file__).resolve().parents[1]


def test_sensitive_phase10_payload_is_rejected_before_handler_or_json_parsing(monkeypatch):
    for name in ("AUTH_SECRET", "ADMIN_USERNAME", "ADMIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    app = FastAPI()
    install_sensitive_api_guard(app)
    called = {"handler": 0}

    @app.post("/api/campaigns/phase10/probe")
    async def probe(body: dict):
        called["handler"] += 1
        return body

    response = TestClient(app).post(
        "/api/campaigns/phase10/probe",
        content=b"{this-is-invalid-json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "auth_not_configured"
    assert called["handler"] == 0


def test_audit_cache_avoids_repeated_expensive_audits():
    class FakeAudit:
        def __init__(self):
            self.calls = 0

        def run(self):
            self.calls += 1
            return {
                "status": "ready_for_bounded_testnet_preflight",
                "blockers": [],
                "warnings": [],
                "audit_sha256": "a" * 64,
            }

    audit = FakeAudit()
    cache = _AuditCache(audit, ttl_seconds=60)
    first = cache.get()
    second = cache.get()
    assert audit.calls == 1
    assert first["audit_sha256"] == second["audit_sha256"]
    assert second["cache_age_ms"] >= 0


def test_audit_cache_converts_internal_exception_to_blocked_state():
    class BrokenAudit:
        def run(self):
            raise RuntimeError("secret internal detail must not escape")

    report = _AuditCache(BrokenAudit(), ttl_seconds=60).get()
    assert report["status"] == "blocked"
    assert report["blockers"] == ["audit_internal_error"]
    assert report["error_type"] == "RuntimeError"
    assert "secret internal detail" not in str(report)


def test_invalid_performance_evidence_generates_critical_alert():
    alerts = project_performance_alerts(
        {
            "month": "2026-07",
            "maximum_drawdown_bps": float("nan"),
            "net_pnl_usdt": 1,
            "matched_fill_count": 20,
        }
    )
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "critical"
    assert "invalid-performance-evidence" in alerts[0]["key"]


def test_expired_or_malformed_authority_alerts_fail_closed():
    expired = project_activation_alerts(
        {"activation_id": "p10a_test", "status": "active", "expires_at_ms": 1000},
        now_ms=1000,
    )
    assert expired[0]["severity"] == "critical"
    malformed = project_activation_alerts(
        {"activation_id": "p10a_bad", "status": "active", "expires_at_ms": "bad"},
        now_ms=1000,
    )
    assert malformed[0]["severity"] == "critical"
    assert "invalid-scaling-evidence" in malformed[0]["key"]


def test_post_deploy_verifier_uses_public_liveness_unique_temp_and_atomic_replace():
    script = (ROOT / "deploy/vps/phase11_post_deploy_verify.sh").read_text(encoding="utf-8")
    assert "/api/health" in script
    assert "/api/system/health" not in script
    assert "mktemp" in script
    assert "os.replace" in script
    assert "/tmp/phase11-health.json" not in script
    assert "ProjectDatabase().health()" in script
    assert "SHARIPOVAI_EXPECTED_SHA" in script


def test_dashboard_renderers_are_abortable_and_injection_safe():
    for relative in (
        "dashboard/static/web2/phase10_scaling_performance_v42.js",
        "dashboard/static/web2/phase11_production_v43.js",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "AbortController" in source
        assert "replaceChildren" in source
        assert "visibilitychange" in source
        assert "innerHTML" not in source
        assert "eval(" not in source
