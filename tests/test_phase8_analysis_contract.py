from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "campaigns" / "phase8_analysis.py"


def test_phase8_analysis_is_immutable_and_advisory() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert "Phase8PostCampaignAnalyzer" in text
    assert "phase8_campaign_analysis" in text
    assert "evidence_sha256" in text
    assert '"manual_decision_required": True' in text
    assert '"automatic_promotion": False' in text
    assert '"runtime_flags_changed": False' in text
    assert '"mainnet_enabled": False' in text


def test_phase8_analysis_has_cost_drawdown_and_quality_gates() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    for token in (
        "minimum_actual_private_fills",
        "maximum_execution_cost_drawdown_percent",
        "maximum_actual_fee_bps",
        "maximum_p95_slippage_bps",
        "maximum_p95_latency_ms",
        "maximum_partial_fill_rate_percent",
        "unique_private_execution_ids",
        "drawdown_within_limit",
    ):
        assert token in text
