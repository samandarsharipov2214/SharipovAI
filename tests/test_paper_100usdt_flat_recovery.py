from __future__ import annotations

from pathlib import Path

from autonomous_trading.council_provider import _risk_blocks
from autonomous_trading.loop import AutonomousPaperLoop
from autonomous_trading.market_stream import StreamQuote
from autonomous_trading.paper_campaign import (
    DEFAULT_PAPER_INITIAL_CASH,
    PAPER_FLAT_RECOVERY_POSITION_FACTOR,
    maybe_rebase_paper_book,
)
from autonomous_trading.stage_controller import StageController
from exchange_connector.execution_contract import MAINNET_EXECUTION_COMPILED
from storage import ProjectDatabase

from test_paper_anti_churn_fee_driven import (
    MID,
    SYMBOL,
    _build_loop,
    _close_long,
    _open_long,
    _plan_buy,
    _quote as _anti_churn_quote,
)


class FakeStream:
    symbols = ["BTCUSDT"]

    def __init__(self, quote: StreamQuote) -> None:
        self.current = quote

    def snapshot(self):
        return {
            "verified": True,
            "status": "live",
            "connected": True,
            "age_seconds": 0,
            "last_error": "",
            "quotes": {self.current.symbol: self.current.to_dict()},
        }

    def quote(self, symbol: str) -> StreamQuote:
        assert symbol == self.current.symbol
        return self.current


def _quote(price: float = 100.0, change: float = 1.0) -> StreamQuote:
    return StreamQuote(
        "BTCUSDT",
        price,
        change,
        1_000_000.0,
        "bybit_websocket",
        "2026-09-02T00:00:00+00:00",
        9_999_999_999_999,
    )


def _loop(tmp_path, monkeypatch, **env: str) -> AutonomousPaperLoop:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.delenv("AUTONOMOUS_PAPER_REBASE_TO_INITIAL", raising=False)
    monkeypatch.delenv("AUTONOMOUS_PAPER_CAMPAIGN_ID", raising=False)
    if "AUTONOMOUS_PAPER_INITIAL_CASH" in env:
        monkeypatch.setenv("AUTONOMOUS_PAPER_INITIAL_CASH", env["AUTONOMOUS_PAPER_INITIAL_CASH"])
    else:
        monkeypatch.delenv("AUTONOMOUS_PAPER_INITIAL_CASH", raising=False)
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    return AutonomousPaperLoop(FakeStream(_quote()), database=database)


def test_default_initial_cash_is_100_when_env_unset(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path, monkeypatch)
    assert DEFAULT_PAPER_INITIAL_CASH == 100.0
    assert loop.initial_cash == 100.0
    assert loop._state["cash"] == 100.0
    assert loop._state["equity"] == 100.0
    stage = StageController(state_file=str(tmp_path / "missing-paper.json"))
    assert stage.assess().metrics["evidence_equity"] == 100.0


def test_env_autonomous_paper_initial_cash_200_is_honored(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path, monkeypatch, AUTONOMOUS_PAPER_INITIAL_CASH="200")
    assert loop.initial_cash == 200.0
    assert loop._state["cash"] == 200.0


def test_flat_drawdown_over_8_does_not_hard_block_recovery_buy() -> None:
    blocks = _risk_blocks(
        change=1.0,
        turnover=10_000_000.0,
        drawdown_percent=12.0,
        max_abs_change=12.0,
        min_turnover=5_000_000.0,
        max_drawdown=8.0,
        deviation=0.1,
        open_position_count=0,
    )
    assert "paper_portfolio_drawdown_limit" not in blocks


def test_open_position_drawdown_over_8_still_hard_blocks() -> None:
    blocks = _risk_blocks(
        change=1.0,
        turnover=10_000_000.0,
        drawdown_percent=12.0,
        max_abs_change=12.0,
        min_turnover=5_000_000.0,
        max_drawdown=8.0,
        deviation=0.1,
        open_position_count=1,
    )
    assert "paper_portfolio_drawdown_limit" in blocks


def test_anti_churn_still_blocks_fee_driven_reentry(tmp_path, monkeypatch) -> None:
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _open_long(loop, stream, plan, clock, "eth-buy-1")
    _close_long(loop, stream, plan, clock, "eth-sell-1")
    clock.advance(15_000)
    stream.current = _anti_churn_quote(MID, now_ms=clock.now_ms())
    _plan_buy(plan, "eth-buy-2", now_ms=clock.now_ms())
    loop.tick()
    assert SYMBOL not in loop._state["positions"]
    assert "eth-buy-2" not in runtime.consumed
    assert "anti_churn" in loop._state["last_reason"]


def test_rebase_helper_does_nothing_unless_env_set(monkeypatch) -> None:
    monkeypatch.delenv("AUTONOMOUS_PAPER_REBASE_TO_INITIAL", raising=False)
    ledger = [{"trade_id": "paper_keep_old_10k", "created_at_ms": 1, "side": "SELL"}]
    state = {
        "cash": 9_200.0,
        "equity": 9_200.0,
        "peak_equity": 10_000.0,
        "positions": {},
        "trades": list(ledger),
        "events": [{"event_id": "paper_event_keep"}],
    }
    unchanged, reason = maybe_rebase_paper_book(state, initial_cash=100.0)
    assert unchanged["cash"] == 9_200.0
    assert unchanged["trades"] == ledger
    assert reason == ""

    monkeypatch.setenv("AUTONOMOUS_PAPER_REBASE_TO_INITIAL", "1")
    rebased, reason = maybe_rebase_paper_book(state, initial_cash=100.0)
    assert rebased["cash"] == 100.0
    assert rebased["equity"] == 100.0
    assert rebased["peak_equity"] == 100.0
    assert rebased["trades"] == ledger
    assert rebased["events"][0]["event_id"] == "paper_event_keep"
    assert "paper_campaign_rebase_to_initial" in reason

    held = dict(state)
    held["positions"] = {"BTCUSDT": {"quantity": 0.01, "entry_price": 100.0, "entry_fee": 0.0}}
    skipped, skipped_reason = maybe_rebase_paper_book(held, initial_cash=100.0)
    assert skipped["cash"] == 9_200.0
    assert skipped_reason == ""


def test_mainnet_still_compiled_out_and_kill_switch_untouched() -> None:
    assert MAINNET_EXECUTION_COMPILED is False
    compose = (Path(__file__).resolve().parents[1] / "deploy/vps/docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert 'AUTONOMOUS_PAPER_INITIAL_CASH: "100"' in compose
    assert 'EXECUTION_KILL_SWITCH: "1"' in compose
    assert 'EXCHANGE_LIVE_TRADING_ENABLED: "0"' in compose
    assert 'FEATURE_BYBIT_LIVE_EXECUTION: "0"' in compose


def test_position_sizing_at_100_usdt_uses_ten_percent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_MAX_POSITION_PERCENT", "10")
    monkeypatch.setenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001")
    loop = _loop(tmp_path, monkeypatch)
    assert loop.max_position_percent == 10.0
    percent, reason = loop._entry_position_percent()
    assert percent == 10.0
    assert reason == ""
    loop.tick()
    position = loop._state["positions"]["BTCUSDT"]
    assert abs(position["quantity"] * 100.0 - 10.0) < 1e-9


def test_flat_underwater_book_uses_documented_recovery_size(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path, monkeypatch)
    loop._state["cash"] = 90.0
    loop._state["equity"] = 90.0
    loop._state["positions"] = {}
    percent, reason = loop._entry_position_percent()
    assert PAPER_FLAT_RECOVERY_POSITION_FACTOR == 0.5
    assert percent == 5.0
    assert "paper_flat_recovery_size" in reason
    loop._state["positions"] = {
        "BTCUSDT": {"quantity": 0.01, "entry_price": 100.0, "entry_fee": 0.0}
    }
    open_percent, open_reason = loop._entry_position_percent()
    assert open_percent == 10.0
    assert open_reason == ""
