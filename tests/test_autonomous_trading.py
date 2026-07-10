from __future__ import annotations

from dataclasses import replace

from autonomous_trading.loop import AutonomousPaperLoop
from autonomous_trading.market_stream import StreamQuote


class FakeStream:
    symbols = ["BTCUSDT"]

    def __init__(self, quote: StreamQuote) -> None:
        self.current = quote

    def snapshot(self):
        return {"verified": True, "status": "live", "connected": True, "age_seconds": 0,
                "last_error": "", "quotes": {self.current.symbol: self.current.to_dict()}}

    def quote(self, symbol: str) -> StreamQuote:
        assert symbol == self.current.symbol
        return self.current


def _quote(price: float, change: float) -> StreamQuote:
    return StreamQuote("BTCUSDT", price, change, 1_000_000.0, "bybit_websocket",
                       "2026-07-10T00:00:00+00:00", 9_999_999_999_999)


def test_loop_opens_and_closes_with_fees(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("AUTONOMOUS_PAPER_MAX_POSITION_PERCENT", "10")
    monkeypatch.setenv("AUTONOMOUS_PAPER_ENTRY_CHANGE_PERCENT", "0.8")
    monkeypatch.setenv("AUTONOMOUS_PAPER_TAKE_PROFIT_PERCENT", "3")
    monkeypatch.setenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001")
    stream = FakeStream(_quote(100.0, 1.0))
    loop = AutonomousPaperLoop(stream)  # type: ignore[arg-type]

    loop.tick()
    opened = loop.snapshot()
    assert "BTCUSDT" in opened["positions"]
    assert opened["total_fees"] > 0

    stream.current = replace(stream.current, price=104.0, change_24h_percent=2.0)
    loop.tick()
    closed = loop.snapshot()
    assert "BTCUSDT" not in closed["positions"]
    assert closed["realized_pnl"] > 0
    assert closed["trades"][-1]["reason"] == "take_profit"
    assert closed["trades"][-1]["verified_market_data"] is True


def test_unverified_stream_blocks_orders(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    stream = FakeStream(_quote(100.0, 5.0))
    stream.snapshot = lambda: {"verified": False, "quotes": {}, "status": "stale"}  # type: ignore[method-assign]
    loop = AutonomousPaperLoop(stream)  # type: ignore[arg-type]
    loop.tick()
    state = loop.snapshot()
    assert state["positions"] == {}
    assert state["last_action"] == "BLOCK"


def test_state_survives_restart(tmp_path, monkeypatch) -> None:
    state_file = tmp_path / "paper.json"
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(state_file))
    stream = FakeStream(_quote(100.0, 1.0))
    first = AutonomousPaperLoop(stream)  # type: ignore[arg-type]
    first.tick()
    assert state_file.exists()
    second = AutonomousPaperLoop(stream)  # type: ignore[arg-type]
    assert "BTCUSDT" in second.snapshot()["positions"]
