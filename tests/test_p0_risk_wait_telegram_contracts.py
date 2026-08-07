from __future__ import annotations

from fastapi import FastAPI

import telegram_health as telegram_module
import trading_intelligence
from autonomous_trading.council_loop import CouncilAuthorizedPaperLoop
from autonomous_trading.council_provider import _DEFAULT_RISK_SERVICE
from dashboard.ai_organ_state_api import AIOrganRuntimeMonitor
from risk_engine import CanonicalRiskService
from storage import ProjectDatabase


def test_council_trade_gate_and_health_share_one_canonical_risk_service(tmp_path) -> None:
    service = CanonicalRiskService()
    assert CanonicalRiskService() is service
    assert _DEFAULT_RISK_SERVICE is service
    assert trading_intelligence._RISK is service

    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    monitor = AIOrganRuntimeMonitor(FastAPI(), database)
    assert monitor.risk_service is service
    assert service.service_id == "risk_engine.canonical_service"


def test_canonical_wait_dedup_emits_immediately_when_reason_changes() -> None:
    loop = object.__new__(CouncilAuthorizedPaperLoop)
    loop._state = {}
    loop.wait_event_min_interval_seconds = 300.0

    assert loop._suppress_wait_event("reason-a", "BTCUSDT", created_at_ms=1_000_000) is False
    assert loop._suppress_wait_event("reason-a", "BTCUSDT", created_at_ms=1_001_000) is True
    assert loop._suppress_wait_event("reason-b", "BTCUSDT", created_at_ms=1_002_000) is False
    # Returning to A is still a reason transition, so it must be visible even
    # though the original A was emitted less than five minutes ago.
    assert loop._suppress_wait_event("reason-a", "BTCUSDT", created_at_ms=1_003_000) is False
    assert loop._state["suppressed_wait_events"] == 1


def test_telegram_health_marks_fresh_error_as_current(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "not-printed")
    monkeypatch.setenv("WEBAPP_URL", "https://example.test")
    monkeypatch.setattr(telegram_module, "_LAST_SUCCESSFUL_WEBHOOK_PROBE_AT", 0)
    monkeypatch.setattr(telegram_module.time, "time", lambda: 10_000)

    def fake_call(token, method, payload=None):
        assert token == "not-printed"
        if method == "getMe":
            return {"ok": True}
        return {
            "ok": True,
            "result": {
                "url": "https://example.test/telegram/webhook",
                "last_error_date": 9_990,
                "last_error_message": "recent failure",
            },
        }

    monkeypatch.setattr(telegram_module, "_telegram", fake_call)
    result = telegram_module.telegram_health()

    assert result["verdict"] == "webhook_error"
    assert result["last_error_date"] == 9_990
    assert result["last_error_is_current"] is True
    assert result["stale_webhook_error_ignored"] is False


def test_telegram_health_marks_old_error_as_historical(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "not-printed")
    monkeypatch.setenv("WEBAPP_URL", "https://example.test")
    monkeypatch.setattr(telegram_module, "_LAST_SUCCESSFUL_WEBHOOK_PROBE_AT", 0)
    monkeypatch.setattr(telegram_module.time, "time", lambda: 10_000)

    def fake_call(token, method, payload=None):
        if method == "getMe":
            return {"ok": True}
        return {
            "ok": True,
            "result": {
                "url": "https://example.test/telegram/webhook",
                "last_error_date": 9_000,
                "last_error_message": "historical failure",
            },
        }

    monkeypatch.setattr(telegram_module, "_telegram", fake_call)
    result = telegram_module.telegram_health()

    assert result["verdict"] == "working"
    assert result["last_error_is_current"] is False
    assert result["stale_webhook_error_ignored"] is True
    assert result["historical_last_error_message"] == "historical failure"
