from __future__ import annotations

from pathlib import Path

from risk_engine import CanonicalRiskService


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_risk_service_is_single_fail_closed_contract() -> None:
    service = CanonicalRiskService()

    assessment = service.evaluate(
        {
            "market_data_verified": False,
            "exchange_ok": False,
            "live_requested": True,
        },
        profile="trade_gate",
    )

    assert service.service_id == "risk_engine.canonical_service"
    assert assessment.allowed_virtual is False
    assert assessment.allowed_live is False
    assert assessment.decision == "BLOCK"
    assert "market_data_unverified" in assessment.hard_blocks
    assert "exchange_unavailable" in assessment.hard_blocks
    assert "live_execution_requested" in assessment.hard_blocks


def test_wait_events_remain_bounded_in_canonical_loop() -> None:
    source = (ROOT / "autonomous_trading" / "loop.py").read_text(encoding="utf-8")

    assert "wait_event_min_interval_seconds" in source
    assert "def _suppress_wait_event" in source
    assert "suppressed_wait_events" in source
    assert 'clean_action == "WAIT"' in source


def test_telegram_health_uses_error_timestamp_not_historical_message_alone() -> None:
    source = (ROOT / "telegram_health.py").read_text(encoding="utf-8")

    assert "last_error_date" in source
    assert "stale_webhook_error_ignored" in source
    assert "_LAST_SUCCESSFUL_WEBHOOK_PROBE_AT" in source
    assert "last_error_message" in source


def test_council_and_monitor_import_the_same_risk_service() -> None:
    council = (ROOT / "autonomous_trading" / "council_provider.py").read_text(encoding="utf-8")
    monitor = (ROOT / "dashboard" / "ai_organ_state_api.py").read_text(encoding="utf-8")

    assert "from risk_engine import CanonicalRiskService" in council
    assert "from risk_engine import CanonicalRiskService" in monitor
    assert "self.risk_service = CanonicalRiskService()" in monitor
