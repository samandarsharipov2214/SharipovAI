"""Bounded recovery of dead non-financial threads owned by the existing monitor.

Never stops a live/stalled worker, restarts Docker, executes an order or invokes
a model. Claims and retry budgets survive application restarts in ProjectDatabase.
"""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Any

from storage import VersionConflict

WORKERS = {
    'market_intelligence': 'bybit_websocket_worker',
    'news_intelligence': 'news_agent_network',
    'learning_engine': 'self_learning_supervisor',
}
MAX_ATTEMPTS = 3
BACKOFF_MS = (60_000, 300_000, 1_800_000)


def resource_observation(database=None) -> dict[str, Any]:
    result: dict[str, Any] = {'load_1m': os.getloadavg()[0], 'available_memory_bytes': None}
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            result['available_memory_bytes'] = int(line.split()[1]) * 1024
            break
    storage = Path('/var/lib/sharipovai')
    if getattr(database, 'backend', None) == 'sqlite':
        path = Path(database.dsn.removeprefix('sqlite:///'))
        storage = path.parent
        for name, file in [('sqlite_size_bytes', path), ('sqlite_wal_bytes', Path(str(path)+'-wal'))]:
            result[name] = file.stat().st_size if file.exists() else 0
    result['disk_free_bytes'] = shutil.disk_usage(storage if storage.exists() else '/').free
    result['sqlite_integrity'] = 'not_scanned_by_lightweight_monitor'
    result['recovery_resources_available'] = (
        result['load_1m'] <= 1.5 and result['available_memory_bytes'] is not None
        and result['available_memory_bytes'] >= 1024**3 and result['disk_free_bytes'] >= 2*1024**3)
    return result


class RuntimeWatchdog:
    def __init__(self, app, database, clock_ms, *, resources=None):
        self.app, self.database, self.clock_ms = app, database, clock_ms
        self.resources = resources or (lambda: resource_observation(database))
        self._lock = threading.Lock()

    def cycle(self, *, stopping: bool = False) -> dict[str, Any]:
        if stopping or not self._lock.acquire(blocking=False):
            return {'status': 'skipped', 'reason': 'shutdown_or_cycle_busy'}
        try:
            resources = self.resources()
            outcomes = {}
            for organ, attribute in WORKERS.items():
                try:
                    outcomes[organ] = self._observe(organ, getattr(self.app.state, attribute, None), resources)
                except Exception as exc:
                    outcomes[organ] = {'status': 'blocked', 'reason': type(exc).__name__}
            result = {'checked_at_ms': self.clock_ms(), 'resources': resources, 'workers': outcomes,
                      'execution_authority': False, 'maximum_attempts_per_worker': MAX_ATTEMPTS}
            previous = self.database.get_json('system_runtime', 'ai_worker_recovery')
            previous = previous['value'] if previous else {}
            if (previous.get('workers') != outcomes
                    or self.clock_ms() - previous.get('checked_at_ms', 0) >= 300_000):
                self.database.put_json('system_runtime', 'ai_worker_recovery', result)
            return result
        finally:
            self._lock.release()

    def _observe(self, organ, worker, resources):
        thread = getattr(worker, '_thread', None)
        if thread is None:
            return {'status': 'blocked', 'reason': 'worker_not_initialized'}
        stop = getattr(worker, '_stop', None)
        if stop is None or stop.is_set():
            return {'status': 'skipped', 'reason': 'intentional_stop_or_no_stop_contract'}
        enabled = getattr(worker, 'enabled', None)
        if callable(enabled) and enabled() is not True:
            return {'status': 'skipped', 'reason': 'disabled_by_policy'}
        key = 'ai_worker_recovery:' + organ
        row = self.database.get_json('system_runtime', key)
        value = dict(row['value']) if row else {'attempts': 0}
        version = row['version'] if row else 0
        if thread.is_alive():
            # Liveness is not functional recovery. The monitor separately checks
            # fresh results; do not turn a restarted thread into a success claim.
            if value.get('status') in {'claimed', 'started_pending_verification'}:
                observed = self.database.get_json('ai_organ_runtime', organ)
                observed = observed['value'] if observed else {}
                result_at = observed.get('metrics', {}).get('last_valid_result_at_ms') or 0
                if (observed.get('status') == 'healthy'
                        and value['last_attempt_at_ms'] < result_at <= self.clock_ms()
                        and self.clock_ms() - result_at <= 300_000
                        and value['last_attempt_at_ms'] < observed.get('checked_at_ms', 0) <= self.clock_ms()):
                    self.database.put_json('system_runtime', key,
                        {**value, 'status': 'verified', 'verified_result_at_ms': result_at},
                        expected_version=version)
                    return {'status': 'verified', 'attempts': value['attempts'],
                            'verified_result_at_ms': result_at}
            return {'status': 'running', 'reason': 'functional_result_checked_by_organ_monitor',
                    'attempts': value['attempts'], 'last_attempt': value.get('last_attempt_at_ms')}
        now = self.clock_ms()
        if value['attempts'] >= MAX_ATTEMPTS:
            return {'status': 'blocked', 'reason': 'retry_budget_exhausted', 'attempts': value['attempts']}
        if now < value.get('next_attempt_at_ms', 0):
            return {'status': 'waiting', 'reason': 'backoff', 'next_attempt_at_ms': value['next_attempt_at_ms']}
        if resources.get('recovery_resources_available') is not True:
            return {'status': 'waiting', 'reason': 'resource_guard'}
        start = getattr(worker, 'start', None)
        if not callable(start):
            return {'status': 'blocked', 'reason': 'no_supported_start'}
        attempt = int(value['attempts']) + 1
        claim = {'attempts': attempt, 'status': 'claimed', 'last_attempt_at_ms': now,
                 'next_attempt_at_ms': now + BACKOFF_MS[attempt-1], 'pid': os.getpid(),
                 'execution_authority': False}
        try:
            claimed_version = self.database.put_json('system_runtime', key, claim, expected_version=version)
        except VersionConflict:
            return {'status': 'waiting', 'reason': 'concurrent_claim'}
        # Recheck immediately before invoking the documented idempotent start.
        if stop.is_set() or thread.is_alive():
            outcome = {'status': 'skipped', 'reason': 'worker_state_changed'}
        else:
            try:
                start()
                outcome = {'status': 'started_pending_verification', 'reason': 'dead_thread_start_requested'}
            except Exception as exc:
                outcome = {'status': 'failed', 'reason': type(exc).__name__}
        self.database.put_json('system_runtime', key, {**claim, **outcome}, expected_version=claimed_version)
        return {**outcome, 'attempts': attempt, 'next_attempt_at_ms': claim['next_attempt_at_ms']}


__all__ = ['RuntimeWatchdog', 'resource_observation']
