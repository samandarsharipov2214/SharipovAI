from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from autonomous_trading.loop import AutonomousPaperLoop
from autonomous_trading.testnet_bridge import AutonomousTestnetBridge
from autonomous_trading.trade_identity import normalize_trade, scope_for_path
from storage import ProjectDatabase, list_json_items


class Stream:
    symbols: tuple[str, ...] = ()

    def snapshot(self):
        return {"verified": False, "quotes": {}, "status": "stale", "connected": False}


class Stage:
    def assess(self):
        return SimpleNamespace(eligible_stage=3, to_dict=lambda: {"eligible_stage": 3})


class Client:
    mode = "sandbox"
    max_notional = 25.0

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls: list[dict] = []

    def status(self):
        return {"mode": self.mode, "kill_switch": True}

    def place_market_order(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise TimeoutError("ambiguous timeout")
        return SimpleNamespace(
            order_id="order-1",
            message="accepted",
            to_dict=lambda: {
                "status": "accepted",
                "mode": "sandbox",
                "environment": "testnet",
                "category": "spot",
                "symbol": kwargs["symbol"],
                "side": kwargs["side"],
                "quantity": kwargs["quantity"],
                "order_id": "order-1",
            },
        )


def db(tmp_path: Path) -> ProjectDatabase:
    value = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    value.initialize()
    return value


def set_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    paper = tmp_path / "paper.json"
    bridge = tmp_path / "bridge.json"
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(paper))
    monkeypatch.setenv("TESTNET_BRIDGE_STATE_FILE", str(bridge))
    monkeypatch.setenv("EXECUTION_JOURNAL_FILE", str(tmp_path / "journal.json"))
    return paper, bridge


def seed_trade(database: ProjectDatabase, paper_file: Path, trade_id: str) -> dict:
    scope = scope_for_path(paper_file)
    trade = normalize_trade({
        "trade_id": trade_id,
        "created_at_ms": 1_000,
        "time": "2026-01-01T00:00:01+00:00",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 0.1,
        "price": 100.0,
        "fee": 0.01,
        "net_pnl": None,
        "reason": "test",
        "source": "bybit_websocket",
        "verified_market_data": True,
    }, scope=scope, index=0)
    database.put_json(f"paper_trades:{scope}", trade_id, trade, expected_version=0)
    return trade


def test_legacy_json_migrates_and_database_survives_missing_backup(tmp_path, monkeypatch) -> None:
    paper, _ = set_paths(monkeypatch, tmp_path)
    paper.write_text(json.dumps({
        "mode": "autonomous_paper",
        "cash": 9000.0,
        "equity": 9100.0,
        "realized_pnl": 10.0,
        "unrealized_pnl": 0.0,
        "total_fees": 1.0,
        "positions": {},
        "trades": [{
            "time": "2026-01-01T00:00:00+00:00", "symbol": "BTCUSDT", "side": "BUY",
            "quantity": 1, "price": 100, "fee": 0.1, "net_pnl": None, "reason": "legacy",
            "source": "bybit_websocket", "verified_market_data": True,
        }],
        "events": [{"time": "2026-01-01T00:00:00+00:00", "action": "BUY", "symbol": "BTCUSDT", "reason": "legacy"}],
    }), encoding="utf-8")
    database = db(tmp_path)
    first = AutonomousPaperLoop(Stream(), database=database)  # type: ignore[arg-type]
    snapshot = first.snapshot()
    assert snapshot["database_backed"] is True
    assert snapshot["trades"][0]["trade_id"].startswith("paper_legacy_")
    assert snapshot["trade_history_count"] == 1
    paper.unlink()
    second = AutonomousPaperLoop(Stream(), database=database)  # type: ignore[arg-type]
    assert second.snapshot()["cash"] == 9000.0
    assert second.snapshot()["trades"][0]["trade_id"] == snapshot["trades"][0]["trade_id"]


def test_database_remains_source_of_truth_when_json_backup_fails(tmp_path, monkeypatch) -> None:
    paper, _ = set_paths(monkeypatch, tmp_path)
    database = db(tmp_path)
    loop = AutonomousPaperLoop(Stream(), database=database)  # type: ignore[arg-type]
    monkeypatch.setattr(loop, "_write_json_backup", lambda: (_ for _ in ()).throw(PermissionError("locked")))
    loop._event("BLOCK", "database survives")
    assert loop.snapshot()["backup_status"] == "error"
    paper.unlink(missing_ok=True)
    recovered = AutonomousPaperLoop(Stream(), database=database)  # type: ignore[arg-type]
    assert recovered.snapshot()["last_reason"] == "database survives"
    assert recovered.snapshot()["event_history_count"] == 1


def test_full_trade_history_is_immutable_while_ui_cache_is_bounded(tmp_path, monkeypatch) -> None:
    set_paths(monkeypatch, tmp_path)
    database = db(tmp_path)
    loop = AutonomousPaperLoop(Stream(), database=database)  # type: ignore[arg-type]
    for index in range(505):
        loop._trade("BTCUSDT", "BUY", 0.01, 100 + index, 0.01, f"trade-{index}", None)
    snapshot = loop.snapshot()
    assert len(snapshot["trades"]) == 500
    assert snapshot["trade_history_count"] == 505
    assert len(loop.trade_history()) == 505


def test_bridge_requires_both_flags_and_never_uses_list_index(tmp_path, monkeypatch) -> None:
    paper, _ = set_paths(monkeypatch, tmp_path)
    database = db(tmp_path)
    seed_trade(database, paper, "paper_first")
    client = Client()
    monkeypatch.setenv("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "1")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    bridge = AutonomousTestnetBridge(client, database=database)
    bridge.stages = Stage()
    bridge.tick()
    assert client.calls == []
    assert bridge.snapshot()["processed_trade_count"] == 1

    seed_trade(database, paper, "paper_second")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "1")
    bridge.tick()
    assert len(client.calls) == 1
    assert bridge.snapshot()["last_trade_id"] == "paper_second"
    records = [item["value"] for item in list_json_items(database, bridge.record_namespace)]
    assert {item["paper_trade_id"] for item in records} == {"paper_first", "paper_second"}


def test_ambiguous_bridge_error_is_unresolved_and_never_retried(tmp_path, monkeypatch) -> None:
    paper, _ = set_paths(monkeypatch, tmp_path)
    database = db(tmp_path)
    seed_trade(database, paper, "paper_timeout")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "1")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "1")
    client = Client(fail=True)
    bridge = AutonomousTestnetBridge(client, database=database)
    bridge.stages = Stage()
    bridge.tick()
    bridge.tick()
    assert len(client.calls) == 1
    snapshot = bridge.snapshot()
    assert snapshot["unresolved_trade_ids"] == ["paper_timeout"]
    journal = bridge.journal.load()["orders"]
    assert len(journal) == 1
    assert journal[0]["status"] == "unresolved"
    assert journal[0]["requires_reconciliation"] is True


def test_corrupt_json_does_not_override_valid_database_state(tmp_path, monkeypatch) -> None:
    paper, _ = set_paths(monkeypatch, tmp_path)
    database = db(tmp_path)
    loop = AutonomousPaperLoop(Stream(), database=database)  # type: ignore[arg-type]
    loop._event("BLOCK", "stored safely")
    paper.write_text("{broken", encoding="utf-8")
    recovered = AutonomousPaperLoop(Stream(), database=database)  # type: ignore[arg-type]
    assert recovered.snapshot()["last_reason"] == "stored safely"
