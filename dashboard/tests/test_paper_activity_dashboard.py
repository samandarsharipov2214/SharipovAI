from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app


class DummyRunner:
    def run(self):
        raise RuntimeError("not used")


def isolate_state(tmp_path, monkeypatch) -> None:
    path = str(tmp_path / "virtual-activity.json")
    monkeypatch.setenv("VIRTUAL_ACCOUNT_STATE_FILE", path)
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", path)
    monkeypatch.setenv("PAPER_ACTIVITY_AUTORUN_ENABLED", "0")
    monkeypatch.setenv("PAPER_ACTIVITY_BOOTSTRAP_TICKS", "0")
    monkeypatch.setenv("VIRTUAL_ACCOUNT_BOOTSTRAP_TICKS", "1")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")


def _assert_virtual_trade_evidence(state: dict) -> None:
    trades = state.get("trades", [])
    assert state["summary"]["trade_count"] == len(trades)
    for trade in trades:
        assert trade.get("real_order_placed") is False
        assert float(trade.get("entry_price", 0) or 0) > 0
        assert str(trade.get("quote_source") or trade.get("source") or "").strip()
        factors = trade.get("decision_factors", {})
        assert factors.get("market_data_verified") is True


def test_paper_activity_api_is_installed_and_blocks_unverified_market_evidence(tmp_path, monkeypatch) -> None:
    isolate_state(tmp_path, monkeypatch)
    client = TestClient(create_app(runner_factory=DummyRunner))

    state_response = client.get("/api/paper-activity/state")
    assert state_response.status_code == 200
    state = state_response.json()["state"]
    _assert_virtual_trade_evidence(state)
    assert state["real_orders_blocked"] is True
    assert state_response.json()["autorun"]["enabled"] is False
    baseline_trades = int(state["summary"]["trade_count"])
    baseline_skips = int(state["summary"].get("skipped_count", 0))

    tick = client.post(
        "/api/paper-activity/tick",
        json={
            "force": True,
            "gate_payload": {
                "symbol": "BTCUSDT",
                "market_data_verified": False,
                "exchange_ok": False,
                "strategy_approved": True,
                "live_requested": False,
            },
        },
    )
    assert tick.status_code == 200
    result = tick.json()
    assert result["status"] == "blocked"
    assert result["state"]["summary"]["trade_count"] == baseline_trades
    assert result["state"]["summary"]["skipped_count"] >= baseline_skips + 1

    trades = client.get("/api/paper-activity/trades")
    assert trades.status_code == 200
    assert trades.json()["summary"]["trade_count"] == len(trades.json()["trades"])

    page = client.get("/paper-activity")
    assert page.status_code == 200
    assert "Paper Activity Engine" in page.text
    assert "Все сделки" in page.text
    assert "JSON all trades" in page.text
    assert "Autorun" in page.text


def test_paper_activity_catch_up_never_fabricates_historical_market_evidence(tmp_path, monkeypatch) -> None:
    isolate_state(tmp_path, monkeypatch)
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.post("/api/paper-activity/catch-up", json={"max_ticks": 3})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["catch_up_ticks"] >= 1
    assert payload.get("historical_prices_fabricated") is False
    _assert_virtual_trade_evidence(payload["state"])
    assert payload["state"]["real_orders_blocked"] is True


def test_launch_check_contains_paper_activity(tmp_path, monkeypatch) -> None:
    isolate_state(tmp_path, monkeypatch)
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.get("/api/launch-check")

    assert response.status_code == 200
    check_names = {item["name"] for item in response.json()["checks"]}
    assert "Paper Activity" in check_names
    assert response.json()["important_urls"]["paper_activity"] == "/paper-activity"
