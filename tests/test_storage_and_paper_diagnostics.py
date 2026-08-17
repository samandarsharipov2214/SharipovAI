from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.paper_trade_analysis import analyze_trades


ROOT = Path(__file__).resolve().parents[1]


def test_paper_trade_analysis_reports_net_after_fees_and_agent_associations() -> None:
    trades = [
        {
            "trade_id": "b1",
            "created_at_ms": 1,
            "time": "2026-08-01T00:00:00+00:00",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 1,
            "price": 100,
            "fee": 1,
            "reason": "canonical_council_allow:d1",
            "decision_id": "d1",
            "decision_quality_confidence": 0.8,
            "decision_quality_agreement": 0.7,
            "general_controller_decision": "ALLOW",
        },
        {
            "trade_id": "s1",
            "created_at_ms": 2,
            "time": "2026-08-01T01:00:00+00:00",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "quantity": 1,
            "price": 90,
            "fee": 1,
            "net_pnl": -12,
            "reason": "protective_stop_loss",
            "decision_id": "d1",
            "decision_settlement": {
                "selected_action": "BUY",
                "realized_action": "SELL",
                "losing_agents": ["crypto_ai", "world_ai"],
                "winning_agents": [],
                "abstaining_agents": ["risk_engine"],
                "reputation_recorded": True,
            },
        },
        {
            "trade_id": "b2",
            "created_at_ms": 3,
            "time": "2026-08-02T00:00:00+00:00",
            "symbol": "ETHUSDT",
            "side": "BUY",
            "quantity": 2,
            "price": 50,
            "fee": 1,
            "reason": "canonical_council_allow:d2",
            "decision_id": "d2",
        },
        {
            "trade_id": "s2",
            "created_at_ms": 4,
            "time": "2026-08-02T02:00:00+00:00",
            "symbol": "ETHUSDT",
            "side": "SELL",
            "quantity": 2,
            "price": 60,
            "fee": 1,
            "net_pnl": 18,
            "reason": "protective_take_profit",
            "decision_id": "d2",
            "decision_settlement": {
                "selected_action": "BUY",
                "realized_action": "BUY",
                "winning_agents": ["crypto_ai"],
                "losing_agents": [],
                "abstaining_agents": [],
                "reputation_recorded": True,
            },
        },
    ]
    state = {
        "v2_shadow_records": {
            "d1": {"champion_action": "BUY", "challenger_action": "WAIT"},
            "d2": {
                "champion_action": "BUY",
                "challenger_action": "BUY",
                "paper_settlement": {"net_pnl": 18},
            },
        }
    }

    report = analyze_trades(trades, state)

    assert report["summary"]["immutable_trade_records"] == 4
    assert report["summary"]["closed_trades"] == 2
    assert report["summary"]["wins"] == 1
    assert report["summary"]["losses"] == 1
    assert report["summary"]["net_pnl"] == pytest.approx(6.0)
    assert report["summary"]["fees"] == pytest.approx(4.0)
    assert report["summary"]["estimated_pnl_before_fees"] == pytest.approx(10.0)
    assert report["by_symbol"]["BTCUSDT"]["net_pnl"] == pytest.approx(-12.0)
    assert report["by_exit_reason"]["protective_take_profit"]["net_pnl"] == pytest.approx(18.0)
    assert report["agent_settlement_associations"]["world_ai"]["losing_settlement_count"] == 1
    assert report["agent_settlement_associations"]["crypto_ai"]["winning_settlement_count"] == 1
    assert report["agent_settlement_associations"]["crypto_ai"]["losing_settlement_count"] == 1
    assert report["v2_shadow"]["records"] == 2
    assert report["v2_shadow"]["disagreements"] == 1
    assert report["v2_shadow"]["settled_records"] == 1
    assert report["v2_shadow"]["execution_authority"] is False


def test_paper_trade_analysis_falls_back_to_symbol_pairing_for_legacy_rows() -> None:
    report = analyze_trades(
        [
            {
                "trade_id": "legacy-buy",
                "created_at_ms": 1,
                "time": "2026-08-01T00:00:00+00:00",
                "symbol": "SOLUSDT",
                "side": "BUY",
                "quantity": 2,
                "price": 10,
                "fee": 0.1,
                "reason": "legacy",
            },
            {
                "trade_id": "legacy-sell",
                "created_at_ms": 2,
                "time": "2026-08-01T00:10:00+00:00",
                "symbol": "SOLUSDT",
                "side": "SELL",
                "quantity": 2,
                "price": 9,
                "fee": 0.1,
                "net_pnl": -2.2,
                "reason": "legacy_exit",
            },
        ]
    )
    assert report["summary"]["closed_trades"] == 1
    assert report["summary"]["orphan_sell_records"] == 0
    assert report["worst_losses"][0]["holding_seconds"] == pytest.approx(600.0)


def test_storage_reclaim_helper_is_bounded_and_syntax_valid() -> None:
    path = ROOT / "scripts" / "storage_reclaim_safe.sh"
    subprocess.run(["bash", "-n", str(path)], check=True)
    text = path.read_text(encoding="utf-8")

    forbidden = (
        "docker system prune",
        "docker volume prune",
        "docker image prune",
        "docker container prune",
        "docker buildx prune",
        "rm -rf /var/lib/docker",
        "rm -rf /var/lib/containerd",
    )
    for command in forbidden:
        assert command not in text

    assert "current_image_id" in text
    assert "rollback_image_id" in text
    assert "ai.sharipov.service=data-permissions" in text
    assert "STORAGE_RECLAIM_OK" in text


def test_docker_context_excludes_host_recovery_material() -> None:
    text = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for pattern in (
        "deploy/vps/backups/",
        "deploy/vps/emergency-recovery/",
        "deploy/vps/docker-compose.yml.bak-*",
        "deploy/vps/*.bak-*",
    ):
        assert pattern in text
