from __future__ import annotations

from paper_activity_engine import PaperActivityEngine
from persistence_paths import durable_data_path


def _verified_gate() -> dict[str, object]:
    return {
        "market_data_verified": True,
        "exchange_ok": True,
        "strategy_approved": True,
        "live_requested": False,
        "ai_consensus_score": 90,
        "news_credibility_percent": 90,
        "news_shock_score": 0,
        "risk_per_trade_percent": 0.5,
        "volatility_percent": 3.0,
        "trend_score": 0.8,
        "spread_percent": 0.03,
        "liquidity_score": 90,
    }


def test_durable_data_path_uses_render_disk(monkeypatch, tmp_path):
    monkeypatch.delenv("VIRTUAL_ACCOUNT_STATE_FILE", raising=False)
    monkeypatch.setenv("RENDER_DISK_PATH", str(tmp_path))
    assert durable_data_path("VIRTUAL_ACCOUNT_STATE_FILE", "data/virtual_account_activity_state.json") == tmp_path / "virtual_account_activity_state.json"


def test_virtual_account_equity_uses_expected_open_edge_not_fee_only_loss(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRTUAL_ACCOUNT_MAX_OPEN", "10")
    monkeypatch.setenv("VIRTUAL_MIN_CONFIDENCE", "0")
    monkeypatch.setenv("VIRTUAL_MIN_EXPECTED_NET_USDT", "0")
    monkeypatch.setenv("VIRTUAL_MIN_EDGE_TO_FEE_RATIO", "0")
    engine = PaperActivityEngine(tmp_path / "state.json")
    opened = []
    now = 1_700_000_000
    for index in range(12):
        result = engine.tick(force=True, now=now + index * 60, gate_payload=_verified_gate())
        if result["status"] == "ok":
            opened.append(result["trade"])
    state = engine.state()
    summary = state["summary"]
    assert opened
    assert all(item["real_order_placed"] is False for item in opened)
    assert summary["expected_open_net_pnl"] > 0
    assert summary["equity"] >= summary["cash"]
    assert summary["equity"] > 10_000 - summary["total_fees"]
