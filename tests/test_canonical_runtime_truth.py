from __future__ import annotations

import time
from types import SimpleNamespace

from fastapi import FastAPI

import dashboard.realtime_status_api as realtime
import telegram_health as telegram_module
from dashboard.ai_organ_state_api import AIOrganRuntimeMonitor
from storage import ProjectDatabase


class _NewsNetwork:
    def __init__(self, database: ProjectDatabase, now_ms: int) -> None:
        self.database = database
        self.agents = [object()]
        self._now_ms = now_ms

    def snapshot(self):
        return {
            "status": "running",
            "last_cycle_at_ms": self._now_ms,
            "last_error": "",
        }


class _Monitor:
    def snapshot(self):
        return {
            "status": "healthy",
            "organ_count": 1,
            "organs": [
                {
                    "organ_id": "market_intelligence",
                    "status": "healthy",
                    "responsibility": "market",
                    "evidence": ["verified_quotes_persisted"],
                    "blockers": [],
                    "checked_at_ms": int(time.time() * 1000),
                }
            ],
        }


class _PaperLoop:
    def __init__(self) -> None:
        self.snapshot_calls = 0
        self.tick_calls = 0

    def snapshot(self):
        self.snapshot_calls += 1
        return {
            "status": "ok",
            "mode": "autonomous_paper",
            "worker_running": True,
            "database_backed": True,
            "decision_mode": "CANONICAL_COUNCIL_REQUIRED",
            "entry_without_authorization_allowed": False,
            "cash": 10_000.0,
            "equity": 10_000.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_fees": 0.0,
            "positions": {},
            "trades": [],
            "trade_history_count": 0,
            "updated_at": "2099-01-01T00:00:00+00:00",
            "suppressed_wait_events": 2,
        }

    def tick(self):
        self.tick_calls += 1
        raise AssertionError("GET status must not tick the paper loop")


def test_monitor_accepts_distinct_database_objects_with_same_dsn(tmp_path) -> None:
    dsn = f"sqlite:///{tmp_path / 'project.db'}"
    canonical = ProjectDatabase(dsn)
    canonical.initialize()
    separate_wrapper = ProjectDatabase(dsn)
    now_ms = int(time.time() * 1000)
    app = FastAPI()
    app.state.project_database = canonical
    app.state.news_agent_network = _NewsNetwork(separate_wrapper, now_ms)
    monitor = AIOrganRuntimeMonitor(app, canonical, clock_ms=lambda: now_ms)

    evidence, blockers = monitor._news_intelligence()

    assert "news_memory_database_backed" in evidence
    assert "news_worker_running" in evidence
    assert not any("canonical database" in item for item in blockers)


def test_realtime_status_reads_only_canonical_runtime(monkeypatch) -> None:
    app = FastAPI()
    loop = _PaperLoop()
    app.state.autonomous_paper_loop = loop
    app.state.ai_organ_runtime_monitor = _Monitor()
    app.state.news_agent_network_install_error = None
    monkeypatch.setattr(
        realtime,
        "network_status",
        lambda run_due=False, app=None: {
            "status": "ok",
            "last_error": "",
            "last_cycle_at_ms": int(time.time() * 1000),
            "hub": {"article_history_count": 4, "urgency_counts": {}},
            "agents": [],
        },
    )
    monkeypatch.setattr(
        realtime,
        "bridge_status",
        lambda app=None: {
            "status": "ok",
            "delivery_mode": "shared_database",
            "consumer_active": True,
        },
    )
    monkeypatch.setattr(
        realtime,
        "telegram_health",
        lambda: {"status": "ok", "verdict": "working"},
    )

    result = realtime.build_realtime_status(app)

    assert loop.snapshot_calls == 1
    assert loop.tick_calls == 0
    assert result["virtual_account"]["source_of_truth"] == "autonomous_paper"
    assert result["virtual_account"]["mutation_on_get"] is False
    assert result["paper_activity"]["deprecated"] is True
    assert result["paper_activity"]["active"] is False
    assert result["agents"]["summary"]["working"] == 1


def test_telegram_ignores_stale_historical_webhook_error(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "not-printed")
    monkeypatch.setenv("WEBAPP_URL", "https://example.test")
    monkeypatch.setattr(telegram_module, "_LAST_SUCCESSFUL_WEBHOOK_PROBE_AT", 0)
    old_error = int(time.time()) - 1_000

    def fake_call(token, method, payload=None):
        assert token == "not-printed"
        if method == "getMe":
            return {"ok": True, "result": {"username": "bot"}}
        return {
            "ok": True,
            "result": {
                "url": "https://example.test/telegram/webhook",
                "last_error_date": old_error,
                "last_error_message": "historical failure",
            },
        }

    monkeypatch.setattr(telegram_module, "_telegram", fake_call)

    result = telegram_module.telegram_health()

    assert result["verdict"] == "working"
    assert result["stale_webhook_error_ignored"] is True


def test_telegram_keeps_recent_webhook_error_visible(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "not-printed")
    monkeypatch.setenv("WEBAPP_URL", "https://example.test")
    monkeypatch.setattr(telegram_module, "_LAST_SUCCESSFUL_WEBHOOK_PROBE_AT", 0)
    recent_error = int(time.time()) - 10

    def fake_call(token, method, payload=None):
        if method == "getMe":
            return {"ok": True, "result": {"username": "bot"}}
        return {
            "ok": True,
            "result": {
                "url": "https://example.test/telegram/webhook",
                "last_error_date": recent_error,
                "last_error_message": "recent failure",
            },
        }

    monkeypatch.setattr(telegram_module, "_telegram", fake_call)

    result = telegram_module.telegram_health()

    assert result["verdict"] == "webhook_error"
    assert result["stale_webhook_error_ignored"] is False
