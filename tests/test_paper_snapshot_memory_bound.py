from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from autonomous_trading.loop import SNAPSHOT_TRADE_WINDOW, AutonomousPaperLoop
from autonomous_trading.status_snapshot import nonblocking_loop_snapshot
from dashboard.news_agent_network_api import _bridge_status
from news_intelligence.hub import NewsHub
from storage import ProjectDatabase
from telegram_runtime_state import canonical_state_from_app


ROOT = Path(__file__).resolve().parents[1]


class _Stream:
    symbols = ("BTCUSDT",)

    def snapshot(self):
        return {
            "status": "live",
            "connected": True,
            "verified": True,
            "age_seconds": 0.1,
            "last_error": "",
            "quotes": {},
        }


def _loop(tmp_path, monkeypatch) -> AutonomousPaperLoop:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    return AutonomousPaperLoop(_Stream(), database=database)


def _spy_list_json_items(monkeypatch, target: str):
    calls: list[dict[str, object]] = []
    import importlib

    module_name, attr = target.rsplit(".", 1)
    module = importlib.import_module(module_name)
    real = getattr(module, attr)

    def spy(database, namespace, *, limit=None, newest_first=False):
        calls.append({"namespace": str(namespace), "limit": limit, "newest_first": newest_first})
        if limit is None:
            raise AssertionError(f"unbounded list_json_items({namespace!r})")
        return real(database, namespace, limit=limit, newest_first=newest_first)

    monkeypatch.setattr(target, spy)
    return calls


def test_snapshot_counts_without_materializing_full_history(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path, monkeypatch)
    for index in range(40):
        loop.database.put_json(
            loop.trade_namespace,
            f"extra-{index}",
            {"trade_id": f"extra-{index}", "symbol": "BTCUSDT"},
        )
        loop.database.put_json(
            loop.event_namespace,
            f"event-{index}",
            {"event_id": f"event-{index}", "action": "WAIT"},
        )

    calls = _spy_list_json_items(monkeypatch, "autonomous_trading.loop.list_json_items")
    snapshot = loop.snapshot()

    assert calls == []
    assert snapshot["trade_history_count"] == 40
    assert snapshot["event_history_count"] == 40
    assert len(snapshot["trades"]) <= SNAPSHOT_TRADE_WINDOW
    assert len(snapshot["events"]) <= 20


def test_nonblocking_snapshot_does_not_call_unbounded_history_readers(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path, monkeypatch)
    loop.database.put_json(loop.trade_namespace, "t1", {"trade_id": "t1"})
    loop.database.put_json(loop.event_namespace, "e1", {"event_id": "e1"})

    def boom(*_args, **_kwargs):
        raise AssertionError("nonblocking snapshot must not list full history")

    monkeypatch.setattr(loop, "trade_history", boom)
    monkeypatch.setattr(loop, "event_history", boom)
    monkeypatch.setattr("autonomous_trading.loop.list_json_items", boom)

    snapshot = nonblocking_loop_snapshot(loop)

    assert snapshot["trade_history_count"] == 1
    assert snapshot["event_history_count"] == 1
    assert snapshot["snapshot_state_source"] == "memory"


def test_telegram_recent_trades_are_capped_and_count_is_full(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path, monkeypatch)
    for index in range(35):
        loop._trade("BTCUSDT", "BUY", 0.01, 100 + index, 0.01, f"trade-{index}", None)

    calls: list[int | None] = []
    real = loop.trade_history

    def spy(*, limit=None):
        calls.append(limit)
        return real(limit=limit)

    loop.trade_history = spy
    app = SimpleNamespace(state=SimpleNamespace(autonomous_paper_loop=loop))
    state = canonical_state_from_app(app)

    assert calls == [20]
    assert len(state["trades"]) == 20
    assert state["trade_count"] == 35


def test_news_status_counts_without_materializing_memory(tmp_path, monkeypatch) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'news.db'}")
    database.initialize()
    for index in range(12):
        database.put_json("news_memory", f"m{index}", {"article": {"title": str(index)}})
        database.put_json("news_events", f"e{index}", {"type": "cycle"})

    def boom(*_args, **_kwargs):
        raise AssertionError("news status must not materialize full memory/events")

    monkeypatch.setattr("storage.collections.list_json_items", boom)
    payload = _bridge_status(database)
    assert payload["memory_records"] == 12
    assert payload["event_records"] == 12

    empty = ProjectDatabase(f"sqlite:///{tmp_path / 'empty-news.db'}")
    empty.initialize()
    hub = NewsHub(database=empty)
    list_calls = _spy_list_json_items(monkeypatch, "news_intelligence.hub.list_json_items")
    status = hub.state()
    assert status["article_history_count"] == 0
    assert status["event_history_count"] == 0
    assert list_calls == []


def test_compose_bounds_sharipovai_memory_without_enabling_live() -> None:
    compose = (ROOT / "deploy" / "vps" / "docker-compose.yml").read_text(encoding="utf-8")
    app = compose.split("  sharipovai:\n", 1)[1].split("  caddy:\n", 1)[0]
    assert "mem_limit: 1g" in app
    assert 'EXECUTION_KILL_SWITCH: "1"' in app
    assert 'EXCHANGE_LIVE_TRADING_ENABLED: "0"' in app
