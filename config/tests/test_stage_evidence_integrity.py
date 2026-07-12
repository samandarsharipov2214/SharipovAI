from __future__ import annotations

import json

from autonomous_trading.evidence_integrity import assess_trade_evidence
from autonomous_trading.stage_controller import StageController
from profitability_gate import evaluate_profitability_candidate


class _Journal:
    def summary(self) -> dict[str, int]:
        return {"verified_testnet_orders": 0, "verified_live_orders": 0}


def _verified_trade(index: int, pnl: float = 1.0) -> dict[str, object]:
    return {
        "trade_id": f"trade-{index}",
        "created_at_ms": 1_700_000_000_000 + index,
        "side": "SELL",
        "quantity": 0.01,
        "price": 50_000.0,
        "net_pnl": pnl,
        "source": "bybit_websocket",
        "verified_market_data": True,
    }


def _synthetic_trade(index: int, pnl: float = 100.0) -> dict[str, object]:
    return {
        "id": f"VA-{index}",
        "created_at_ms": 1_700_000_100_000 + index,
        "side": "SELL",
        "quantity": 1.0,
        "price": 1.0,
        "net_pnl": pnl,
        "source": "virtual_account_execution_engine",
        "verified_market_data": False,
    }


def test_synthetic_trade_is_not_promotion_evidence() -> None:
    result = assess_trade_evidence(_synthetic_trade(1))
    assert result.eligible is False
    assert any("synthetic source" in reason for reason in result.reasons)


def test_verified_market_trade_is_eligible() -> None:
    result = assess_trade_evidence(_verified_trade(1))
    assert result.eligible is True
    assert result.reasons == ()


def test_deterministic_profitability_is_explicitly_non_evidence(monkeypatch) -> None:
    monkeypatch.setenv("VIRTUAL_MIN_EXPECTED_NET_USDT", "0")
    monkeypatch.setenv("VIRTUAL_MIN_EDGE_TO_FEE_RATIO", "0")
    monkeypatch.setenv("VIRTUAL_MIN_CONFIDENCE", "0")
    result = evaluate_profitability_candidate(
        symbol="BTC/USDT",
        side="BUY",
        tick_count=1,
        notional=100.0,
        estimated_fee=0.1,
        state={"trades": []},
        gate={"ai_consensus_score": 75},
    )

    assert result["evidence_class"] == "synthetic_simulation"
    assert result["uses_live_market_prediction"] is False
    assert result["promotion_eligible"] is False
    assert result["learning_eligible"] is False
    assert result["reputation_eligible"] is False


def test_synthetic_profit_cannot_unlock_testnet(tmp_path, monkeypatch) -> None:
    state_file = tmp_path / "paper.json"
    state_file.write_text(
        json.dumps({"equity": 1_000_000.0, "trades": [_synthetic_trade(index) for index in range(100)]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTONOMOUS_TRADING_STAGE", "2")
    assessment = StageController(str(state_file), journal=_Journal()).assess()

    assert assessment.eligible_stage == 2
    assert assessment.metrics["closed_trades"] == 0.0
    assert assessment.metrics["rejected_evidence_trades"] == 100.0
    assert assessment.metrics["net_profit"] == 0.0
    assert assessment.recommended_max_notional_usdt == 0.0


def test_only_verified_trades_count_toward_stage_three(tmp_path, monkeypatch) -> None:
    trades = [_verified_trade(index) for index in range(30)]
    trades.extend(_synthetic_trade(index) for index in range(20))
    state_file = tmp_path / "paper.json"
    state_file.write_text(json.dumps({"equity": 999_999.0, "trades": trades}), encoding="utf-8")
    monkeypatch.setenv("AUTONOMOUS_TRADING_STAGE", "2")

    assessment = StageController(str(state_file), journal=_Journal()).assess()

    assert assessment.eligible_stage == 3
    assert assessment.metrics["closed_trades"] == 30.0
    assert assessment.metrics["rejected_evidence_trades"] == 20.0
    assert assessment.metrics["net_profit"] == 30.0
    assert assessment.metrics["evidence_equity"] == 10_030.0
    assert assessment.metrics["reported_equity"] == 999_999.0


def test_recovered_deep_drawdown_still_blocks_stage_three(tmp_path, monkeypatch) -> None:
    trades = [_verified_trade(0, -2_000.0)]
    trades.extend(_verified_trade(index, 100.0) for index in range(1, 30))
    state_file = tmp_path / "paper.json"
    state_file.write_text(json.dumps({"equity": 10_900.0, "trades": trades}), encoding="utf-8")
    monkeypatch.setenv("AUTONOMOUS_TRADING_STAGE", "2")
    monkeypatch.setenv("STAGE3_MAX_DRAWDOWN_PERCENT", "10")

    assessment = StageController(str(state_file), journal=_Journal()).assess()

    assert assessment.metrics["net_profit"] == 900.0
    assert assessment.metrics["evidence_equity"] == 10_900.0
    assert assessment.metrics["drawdown_percent"] == 20.0
    assert assessment.eligible_stage == 2
    assert any("Просадка" in blocker for blocker in assessment.blockers)
