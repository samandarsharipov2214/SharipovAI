from types import SimpleNamespace
import threading

import pytest
from fastapi import FastAPI

from dashboard.ai_organ_state_api import AIOrganRuntimeMonitor
from dashboard.ai_runtime_watchdog import RuntimeWatchdog
from exchange_connector.bybit_websocket_worker import BybitWebSocketWorker
from storage import ProjectDatabase, VersionConflict


class Thread:
    alive = False
    def is_alive(self):
        return self.alive


class Worker:
    def __init__(self):
        self._thread = Thread()
        self._stop = threading.Event()
        self.calls = 0
    def start(self):
        self.calls += 1
        self._thread.alive = True


def setup(tmp_path, *, available=True):
    db = ProjectDatabase(f'sqlite:///{tmp_path / "runtime.db"}')
    db.initialize()
    worker = Worker()
    app = FastAPI()
    app.state.news_agent_network = worker
    clock = [1_000_000]
    def watchdog():
        return RuntimeWatchdog(app, db, lambda: clock[0],
            resources=lambda: {'recovery_resources_available': available})
    return db, worker, app, clock, watchdog


def test_restart_requires_fresh_functional_result_not_just_live_thread(tmp_path):
    db, worker, app, clock, make = setup(tmp_path)
    watch = make()
    assert watch.cycle()['workers']['news_intelligence']['status'] == 'started_pending_verification'
    assert worker.calls == 1
    assert watch.cycle()['workers']['news_intelligence']['status'] == 'running'
    db.put_json('ai_organ_runtime', 'news_intelligence', {'status': 'healthy',
        'checked_at_ms': clock[0], 'metrics': {'last_valid_result_at_ms': clock[0]-100}})
    assert watch.cycle()['workers']['news_intelligence']['status'] == 'running'
    clock[0] += 1000
    db.put_json('ai_organ_runtime', 'news_intelligence', {'status': 'healthy',
        'checked_at_ms': clock[0], 'metrics': {'last_valid_result_at_ms': clock[0]}})
    assert make().cycle()['workers']['news_intelligence']['status'] == 'verified'
    assert worker.calls == 1


def test_crash_and_reboot_keep_claim_backoff_and_retry_budget(tmp_path):
    db, worker, app, clock, make = setup(tmp_path)
    for index, delay in enumerate([60_000, 300_000, 1_800_000]):
        worker._thread.alive = False
        assert make().cycle()['workers']['news_intelligence']['attempts'] == index + 1
        worker._thread.alive = False
        reason = make().cycle()['workers']['news_intelligence']['reason']
        assert reason == ('retry_budget_exhausted' if index == 2 else 'backoff')
        clock[0] += delay
    assert make().cycle()['workers']['news_intelligence']['reason'] == 'retry_budget_exhausted'
    assert worker.calls == 3


@pytest.mark.parametrize('condition', ['resource', 'shutdown', 'stopped', 'alive', 'disabled'])
def test_no_recovery_without_explicit_safe_conditions(tmp_path, condition):
    db, worker, app, clock, make = setup(tmp_path, available=condition != 'resource')
    if condition == 'stopped': worker._stop.set()
    if condition == 'alive': worker._thread.alive = True
    if condition == 'disabled': worker.enabled = lambda: False
    make().cycle(stopping=condition == 'shutdown')
    assert worker.calls == 0
    assert db.get_json('system_runtime', 'ai_worker_recovery:news_intelligence') is None


def test_failed_restart_is_bounded_and_cannot_touch_execution(tmp_path):
    db, worker, app, clock, make = setup(tmp_path)
    def fail(): raise RuntimeError('not copied to evidence')
    worker.start = fail
    app.state.autonomous_paper_loop = Worker()
    result = make().cycle()['workers']['news_intelligence']
    assert result['status'] == 'failed' and result['reason'] == 'RuntimeError'
    assert app.state.autonomous_paper_loop.calls == 0
    assert make().cycle()['workers']['news_intelligence']['reason'] == 'backoff'


def test_cas_prevents_second_executor_start(tmp_path, monkeypatch):
    db, worker, app, clock, make = setup(tmp_path)
    original = db.put_json
    def competing(namespace, key, value, **kw):
        if key == 'ai_worker_recovery:news_intelligence':
            raise VersionConflict('other observer claimed')
        return original(namespace, key, value, **kw)
    monkeypatch.setattr(db, 'put_json', competing)
    assert make().cycle()['workers']['news_intelligence']['reason'] == 'concurrent_claim'
    assert worker.calls == 0


def test_failed_component_does_not_block_other_recovery(tmp_path):
    db, worker, app, clock, make = setup(tmp_path)
    bad = Worker()
    def fail(): raise RuntimeError('failed status')
    bad.enabled = fail
    app.state.bybit_websocket_worker = bad
    result = make().cycle()
    assert result['workers']['market_intelligence']['status'] == 'blocked'
    assert result['workers']['news_intelligence']['status'] == 'started_pending_verification'


def test_connected_socket_with_incomplete_quotes_is_not_verified(monkeypatch):
    monkeypatch.setenv('BYBIT_WS_SYMBOLS', 'BTCUSDT,ETHUSDT')
    worker = BybitWebSocketWorker()
    monkeypatch.setattr(worker.state, 'status', lambda: {'verified': True,
        'connected': True, 'quote_ages_seconds': {'BTCUSDT': .1}})
    assert worker.status()['missing_symbols'] == ['ETHUSDT']
    assert worker.status()['verified'] is False
    monkeypatch.setattr(worker.state, 'status', lambda: {'verified': True,
        'connected': True, 'quote_ages_seconds': {'BTCUSDT': .1, 'ETHUSDT': .2}})
    assert worker.status()['verified'] is True


def test_future_evidence_is_not_fresh(tmp_path):
    db, worker, app, clock, make = setup(tmp_path)
    monitor = AIOrganRuntimeMonitor(app, db, clock_ms=lambda: clock[0])
    evidence, blockers = [], []
    monitor._append_freshness(evidence, blockers, 'decision', clock[0]+1)
    assert any('future' in x for x in blockers)
    assert monitor._probe_results['decision']['valid'] is False


def test_live_but_stalled_paper_worker_degrades_controller(tmp_path, monkeypatch):
    db, worker, app, clock, make = setup(tmp_path)
    monkeypatch.setenv('AUTONOMOUS_PAPER_ENABLED', '1')
    app.state.control_plane_api_installed = True
    app.state.project_database = db
    app.state.autonomous_paper_loop = SimpleNamespace(work_metrics=lambda: {
        'last_successful_cycle_at_ms': clock[0]-120_000, 'tick_seconds': 5,
        'last_cycle_error': 'TimeoutError'})
    monitor = AIOrganRuntimeMonitor(app, db, clock_ms=lambda: clock[0])
    evidence, blockers = monitor._general_controller()
    assert any('stale' in x for x in blockers)
    assert any('TimeoutError' in x for x in blockers)
