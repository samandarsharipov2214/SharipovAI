from __future__ import annotations

from paper_activity_engine import PaperActivityEngine


def test_paper_activity_tick_opens_trades(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_TICK_SECONDS", "60")
    engine = PaperActivityEngine()

    first = engine.tick(force=True, now=1000)
    second = engine.tick(force=True, now=1060)

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    state = engine.state()
    assert state["summary"]["trade_count"] == 2
    assert state["summary"]["open_positions"] == 2
    assert state["real_orders_blocked"] is True


def test_paper_activity_waits_for_interval(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_TICK_SECONDS", "60")
    engine = PaperActivityEngine()

    engine.tick(force=True, now=1000)
    waiting = engine.tick(force=False, now=1010)

    assert waiting["status"] == "waiting"
    assert "waiting_interval" in waiting["reason"]
    assert engine.state()["summary"]["trade_count"] == 1


def test_paper_activity_closes_oldest_when_max_open_reached(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_MAX_OPEN", "2")
    engine = PaperActivityEngine()

    engine.tick(force=True, now=1000)
    engine.tick(force=True, now=1060)
    third = engine.tick(force=True, now=1120)

    assert third["status"] == "closed_position"
    state = engine.state()
    assert state["summary"]["trade_count"] == 2
    assert state["summary"]["closed_positions"] == 1
    assert state["summary"]["open_positions"] == 1


def test_paper_activity_catches_up_after_idle_time(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_TICK_SECONDS", "60")
    monkeypatch.setenv("PAPER_ACTIVITY_MAX_OPEN", "20")
    engine = PaperActivityEngine()
    engine.tick(force=True, now=1000)

    result = engine.catch_up(now=1000 + 60 * 10, max_ticks=5)
    state = engine.state()

    assert result["status"] == "ok"
    assert result["catch_up_ticks"] == 5
    assert state["summary"]["trade_count"] == 6
    assert state["summary"]["last_reason"] == "catch_up_completed:5_ticks"


def test_paper_activity_state_can_catch_up_when_first_opened(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    engine = PaperActivityEngine()

    state = engine.state(catch_up=True)

    assert state["summary"]["trade_count"] == 1
    assert state["config"]["catch_up_on_state"] is True


def test_paper_activity_reset(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    engine = PaperActivityEngine()
    engine.tick(force=True, now=1000)

    result = engine.reset()

    assert result["status"] == "ok"
    assert result["state"]["summary"]["trade_count"] == 0
