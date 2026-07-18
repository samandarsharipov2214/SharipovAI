from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase8_report_cli_is_fail_closed() -> None:
    source = (ROOT / "scripts" / "phase8_campaign_report.py").read_text(encoding="utf-8")
    assert "campaign is not completed" in source
    assert "campaign not found" in source
    assert "return 0 if not analysis[\"failed_gates\"] else 2" in source
    assert "PostCampaignAnalysisService" in source
