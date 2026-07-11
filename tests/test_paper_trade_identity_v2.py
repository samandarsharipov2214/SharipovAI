from autonomous_trading.loop import AutonomousPaperLoop


class Stream:
    symbols = []


def test_new_paper_trade_gets_persistent_trade_id(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    loop = AutonomousPaperLoop(Stream())
    loop._trade("BTCUSDT", "BUY", 0.01, 100, 0.001, "momentum", None)
    trade = loop._state["trades"][0]
    assert trade["trade_id"].startswith("paper_")
