from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import telegram_system_adapter as adapter
from telegram_runtime_state import unavailable_state


ADAPTER_PATH = Path(__file__).resolve().parents[1] / "telegram_system_adapter.py"


class FakeLoop:
    def __init__(self, payload):
        self.payload = payload

    def snapshot(self):
        return self.payload


def _canonical_payload(**overrides):
    payload = {
        "source_of_truth": "autonomous_paper",
        "mode": "autonomous_paper",
        "equity": 9876.5,
        "cash": 8765.4,
        "realized_pnl": -12.5,
        "unrealized_pnl": 3.25,
        "total_fees": 8.75,
        "positions": {"BTCUSDT": {"quantity": 0.01}},
        "trades": [
            {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "fee": 1.0,
                "net_pnl": None,
            }
        ],
        "trade_history_count": 17,
        "last_action": "WAIT",
        "last_reason": "drawdown",
        "worker_running": True,
        "database_backed": True,
        "database_scope": "canonical",
        "mutation_on_read": False,
        "market_stream": {"verified": True, "age_seconds": 2},
    }
    payload.update(overrides)
    return payload


def _app_with(payload):
    return SimpleNamespace(state=SimpleNamespace(autonomous_paper_loop=FakeLoop(payload)))


def _bind(app):
    adapter.bind_runtime_app(app)


def test_adapter_source_does_not_import_demo_api() -> None:
    source = ADAPTER_PATH.read_text(encoding="utf-8")
    assert "dashboard.demo_api" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("dashboard.demo_api"):
            raise AssertionError("telegram_system_adapter still imports dashboard.demo_api")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("dashboard.demo_api"):
                    raise AssertionError("telegram_system_adapter still imports dashboard.demo_api")


def test_overview_uses_canonical_equity_and_wait_reason() -> None:
    _bind(_app_with(_canonical_payload()))
    try:
        text = adapter._overview()
    finally:
        _bind(None)

    assert "Режим: <b>AUTONOMOUS_PAPER</b>" in text
    assert "9876.50 USDT" in text
    assert "Last action: <b>WAIT</b>" in text
    assert "Last reason: <b>drawdown</b>" in text
    assert "Realized PnL: <b>-12.50 USDT</b>" in text
    assert "LIVE" in text
    assert "заблокирован" in text
    assert "10000.00" not in text
    assert "Режим: <b>PAPER</b>" not in text


def test_trades_and_status_keep_wait_reason() -> None:
    _bind(_app_with(_canonical_payload()))
    try:
        trades = adapter._trades()
        status = adapter._status()
    finally:
        _bind(None)

    for text in (trades, status):
        assert "AUTONOMOUS_PAPER" in text
        assert "9876.50 USDT" in text
        assert "WAIT" in text
        assert "drawdown" in text
        assert "заблокирован" in text
        assert "sandbox" not in text.lower()


def test_missing_loop_renders_unavailable_not_zeros() -> None:
    _bind(SimpleNamespace(state=SimpleNamespace()))
    try:
        overview = adapter._overview()
        trades = adapter._trades()
        status = adapter._status()
    finally:
        _bind(None)

    for text in (overview, trades, status):
        assert "UNAVAILABLE" in text
        assert "0.00 USDT" not in text
        assert "10000" not in text
        assert "autonomous_paper_loop_missing" in text
        assert "заблокирован" in text


def test_unbound_adapter_fails_closed_without_demo_defaults() -> None:
    _bind(None)
    text = adapter._overview()
    assert "UNAVAILABLE" in text
    assert "telegram_runtime_app_unbound" in text
    assert "0.00 USDT" not in text
    state = adapter._current_state()
    assert state["equity"] is None
    assert state["mode"] == "UNAVAILABLE"
    assert unavailable_state("x")["equity"] is None


def test_reply_passes_canonical_state_not_demo(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_answer_chat(question, state=None):
        captured["question"] = question
        captured["state"] = state
        return {"source_ai": "Portfolio Engine", "reply": "canonical"}

    monkeypatch.setattr(adapter, "answer_chat", fake_answer_chat)
    _bind(_app_with(_canonical_payload()))
    try:
        reply = adapter._reply("покажи портфель")
    finally:
        _bind(None)

    state = captured["state"]
    assert isinstance(state, dict)
    assert state["data_available"] is True
    assert state["equity"] == 9876.5
    assert state["source_of_truth"] == "autonomous_paper"
    assert state["mode"] == "AUTONOMOUS_PAPER"
    assert state["last_action"] == "WAIT"
    assert "canonical" in reply
    assert state.get("integration", {}).get("source") != "dashboard.demo_api"


def test_webhook_status_contract_is_canonical_not_demo(monkeypatch) -> None:
    import dashboard.telegram_webhook_api as telegram_api

    monkeypatch.setattr(telegram_api, "_auto_configure_webhook", lambda: {"status": "disabled"})
    app = FastAPI()
    app.state.autonomous_paper_loop = FakeLoop(_canonical_payload())
    telegram_api.install_telegram_webhook_api(app)

    with TestClient(app) as client:
        payload = client.get("/api/telegram/status").json()

    integration = payload["integration"]
    assert integration["shared_demo_state"] is False
    assert integration["canonical_paper_state"] is True
    assert integration["state_source"] == "telegram_runtime_state"
    assert integration["source_of_truth"] == "autonomous_paper"
    assert integration["adapter"] == "telegram_system_adapter"
    assert payload.get("deprecated_demo_state_used") is not True

    overview = adapter._overview()
    assert "9876.50 USDT" in overview
    assert "WAIT" in overview
    _bind(None)


def test_overview_does_not_crash_on_none_money_fields() -> None:
    _bind(None)
    text = adapter._overview()
    assert "UNAVAILABLE" in text
    assert "float" not in text.lower()
