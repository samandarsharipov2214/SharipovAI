from __future__ import annotations

from paper_activity_engine import PaperActivityEngine


def verified_gate() -> dict[str, object]:
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


def allow_all_profitability(monkeypatch) -> None:
    monkeypatch.setenv("VIRTUAL_MIN_CONFIDENCE", "0")
    monkeypatch.setenv("VIRTUAL_MIN_EXPECTED_NET_USDT", "0")
    monkeypatch.setenv("VIRTUAL_MIN_EDGE_TO_FEE_RATIO", "0")


def test_paper_activity_blocks_without_verified_market_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    engine = PaperActivityEngine()

    result = engine.tick(force=True, now=1000)
    state = engine.state()

    assert result["status"] == "blocked"
    assert result["gate"]["market_data_verified"] is False
    assert state["summary"]["trade_count"] == 0
    assert state["summary"]["skipped_count"] == 1
    assert state["real_orders_blocked"] is True


def test_verified_paper_activity_opens_trades(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_TICK_SECONDS", "60")
    allow_all_profitability(monkeypatch)
    engine = PaperActivityEngine()

    first = engine.tick(force=True, now=1000, gate_payload=verified_gate())
    second = engine.tick(force=True, now=1060, gate_payload=verified_gate())

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    state = engine.state()
    assert state["summary"]["trade_count"] == 2
    assert state["summary"]["open_positions"] == 2
    assert all(trade["real_order_placed"] is False for trade in state["trades"])


def test_paper_activity_waits_for_interval_after_verified_tick(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_TICK_SECONDS", "60")
    allow_all_profitability(monkeypatch)
    engine = PaperActivityEngine()

    engine.tick(force=True, now=1000, gate_payload=verified_gate())
    waiting = engine.tick(force=False, now=1010, gate_payload=verified_gate())

    assert waiting["status"] == "waiting"
    assert "waiting_interval" in waiting["reason"]
    assert engine.state()["summary"]["trade_count"] == 1


def test_paper_activity_closes_oldest_when_max_open_reached(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_MAX_OPEN", "2")
    allow_all_profitability(monkeypatch)
    engine = PaperActivityEngine()

    engine.tick(force=True, now=1000, gate_payload=verified_gate())
    engine.tick(force=True, now=1060, gate_payload=verified_gate())
    third = engine.tick(force=True, now=1120, gate_payload=verified_gate())

    assert third["status"] == "closed_position"
    state = engine.state()
    assert state["summary"]["trade_count"] == 2
    assert state["summary"]["closed_positions"] == 1
    assert state["summary"]["open_positions"] == 1


def test_catch_up_never_fabricates_missing_market_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_TICK_SECONDS", "60")
    monkeypatch.setenv("PAPER_ACTIVITY_MAX_OPEN", "20")
    engine = PaperActivityEngine()
    engine.tick(force=True, now=1000)

    result = engine.catch_up(now=1000 + 60 * 10, max_ticks=5)
    state = engine.state()

    assert result["status"] == "ok"
    assert result["catch_up_ticks"] == 5
    assert state["summary"]["trade_count"] == 0
    assert state["summary"]["skipped_count"] == 6
    assert state["summary"]["last_reason"] == "catch_up_completed:5_ticks"


def test_state_bootstrap_is_truthful_without_verified_market(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_BOOTSTRAP_TICKS", "3")
    engine = PaperActivityEngine()

    state = engine.state(catch_up=True)

    assert state["summary"]["trade_count"] == 0
    assert state["summary"]["skipped_count"] == 3
    assert state["config"]["catch_up_on_state"] is True
    assert state["summary"]["last_reason"] == "bootstrap_completed:3_ticks"


def test_paper_activity_reset(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    engine = PaperActivityEngine()
    engine.tick(force=True, now=1000)

    result = engine.reset()

    assert result["status"] == "ok"
    assert result["state"]["summary"]["trade_count"] == 0
