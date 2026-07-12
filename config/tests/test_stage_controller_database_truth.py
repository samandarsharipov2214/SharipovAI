from __future__ import annotations

import json
from pathlib import Path

from autonomous_trading.execution_journal import ExecutionJournal
from autonomous_trading.stage_controller import StageController
from autonomous_trading.trade_identity import scope_for_path
from storage import ProjectDatabase


def _trade(trade_id: str, *, pnl: float = 10.0) -> dict[str, object]:
    return {
        "trade_id": trade_id,
        "created_at_ms": 1_700_000_000_000,
        "side": "SELL",
        "quantity": 1.0,
        "price": 100.0,
        "net_pnl": pnl,
        "source": "bybit_websocket",
        "verified_market_data": True,
    }


def _controller(tmp_path: Path, monkeypatch) -> tuple[StageController, ProjectDatabase, Path, str]:
    monkeypatch.setenv("AUTONOMOUS_TRADING_STAGE", "2")
    monkeypatch.setenv("STAGE3_MIN_CLOSED_TRADES", "1")
    monkeypatch.setenv("STAGE3_MIN_PROFIT_FACTOR", "1")
    monkeypatch.setenv("STAGE3_MAX_DRAWDOWN_PERCENT", "50")
    state_file = tmp_path / "paper.json"
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    journal = ExecutionJournal(str(tmp_path / "journal.json"), database=database)
    controller = StageController(str(state_file), journal=journal, database=database)
    return controller, database, state_file, scope_for_path(state_file)


def test_stage_controller_uses_immutable_database_history(tmp_path: Path, monkeypatch) -> None:
    controller, database, _state_file, scope = _controller(tmp_path, monkeypatch)
    trade = _trade("verified-1")
    database.put_json(
        "autonomous_paper_state",
        scope,
        {"trades": [trade], "equity": 10_010.0},
        expected_version=0,
    )
    database.put_json(f"paper_trades:{scope}", "verified-1", trade, expected_version=0)

    assessment = controller.assess()

    assert assessment.eligible_stage == 3
    assert assessment.metrics["paper_state_database_backed"] == 1.0
    assert assessment.metrics["immutable_trade_history_count"] == 1.0
    assert assessment.metrics["net_profit"] == 10.0


def test_missing_immutable_history_blocks_promotion(tmp_path: Path, monkeypatch) -> None:
    controller, database, _state_file, scope = _controller(tmp_path, monkeypatch)
    trade = _trade("missing-history")
    database.put_json(
        "autonomous_paper_state",
        scope,
        {"trades": [trade], "equity": 10_010.0},
        expected_version=0,
    )

    assessment = controller.assess()

    assert assessment.eligible_stage == 2
    assert any("не согласованы" in blocker for blocker in assessment.blockers)


def test_legacy_json_is_migrated_before_assessment(tmp_path: Path, monkeypatch) -> None:
    controller, database, state_file, scope = _controller(tmp_path, monkeypatch)
    trade = _trade("legacy-1")
    state_file.write_text(
        json.dumps({"trades": [trade], "equity": 10_010.0}),
        encoding="utf-8",
    )

    assessment = controller.assess()

    assert assessment.eligible_stage == 3
    assert database.get_json("autonomous_paper_state", scope) is not None
    assert database.get_json(f"paper_trades:{scope}", "legacy-1") is not None
    assert assessment.metrics["paper_state_database_backed"] == 1.0
