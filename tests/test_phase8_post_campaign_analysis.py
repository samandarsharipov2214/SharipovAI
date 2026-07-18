from __future__ import annotations

from campaigns.phase8_analysis import PostCampaignAnalysisService
from storage import ProjectDatabase


def test_post_campaign_analysis_computes_net_pnl_divergence_and_recommendation(tmp_path) -> None:
    service = PostCampaignAnalysisService(ProjectDatabase(f"sqlite:///{tmp_path / 'phase8.db'}"))
    campaign = {
        "campaign_id": "campaign_8",
        "experiment_id": "experiment_8",
        "scope": "BTCUSDT",
        "status": "completed",
        "metrics": {
            "matched_fill_count": 20,
            "paper_average_fill_price": 100.0,
            "paper_fee_total": 0.02,
            "unmatched_paper_count": 0,
            "unmatched_testnet_count": 0,
            "orphan_execution_count": 0,
            "duplicate_order_count": 0,
            "unresolved_order_count": 0,
        },
    }
    fills = []
    for index in range(10):
        fills.append({"symbol":"BTCUSDT","side":"Buy","filled_quantity":1,"average_fill_price":100,"executed_value":100,"actual_fee":0.001,"last_exec_time_ms":index})
    for index in range(10):
        fills.append({"symbol":"BTCUSDT","side":"Sell","filled_quantity":1,"average_fill_price":101,"executed_value":101,"actual_fee":0.001,"last_exec_time_ms":100+index})
    result = service.analyze(campaign, fills, generated_at_ms=123456)
    assert result["pnl"]["gross_realized_pnl_usdt"] == 10.0
    assert result["pnl"]["net_realized_pnl_usdt"] == 9.98
    assert result["recommendation"]["action"] == "eligible_for_manual_promotion_review"
    assert result["manual_decision_required"] is True
    assert result["mainnet_enabled"] is False
    assert service.get("campaign_8")["analysis_id"] == result["analysis_id"]


def test_post_campaign_analysis_fails_closed_on_identity_and_fill_gates(tmp_path) -> None:
    service = PostCampaignAnalysisService(ProjectDatabase(f"sqlite:///{tmp_path / 'phase8.db'}"))
    campaign = {"campaign_id":"blocked","status":"completed","metrics":{"matched_fill_count":5,"orphan_execution_count":1}}
    result = service.analyze(campaign, [], generated_at_ms=1)
    assert result["recommendation"]["action"] == "reject_or_rerun"
    assert "minimum_matched_fills" in result["failed_gates"]
    assert "identity_integrity" in result["failed_gates"]
    assert result["recommendation"]["automatic_promotion"] is False
