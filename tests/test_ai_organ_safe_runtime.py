from __future__ import annotations

import threading

from dashboard.ai_organ_state_safe_api import (
    SafeAIOrganRuntimeMonitor,
    _module_available,
    _module_has_callable,
)


def test_trading_intelligence_file_module_exposes_trade_gate() -> None:
    assert _module_has_callable("trading_intelligence", "trade_gate") is True


def test_dotted_probe_on_file_module_is_non_fatal() -> None:
    assert _module_available("trading_intelligence.trade_gate") is False


def test_monitor_startup_error_does_not_kill_application() -> None:
    events: list[tuple[str, str, str, dict[str, object]]] = []

    class Database:
        def append_event(
            self,
            namespace: str,
            entity_type: str,
            entity_id: str,
            payload: dict[str, object],
        ) -> None:
            events.append((namespace, entity_type, entity_id, payload))

    monitor = object.__new__(SafeAIOrganRuntimeMonitor)
    monitor._lock = threading.RLock()
    monitor._stop = threading.Event()
    monitor._thread = None
    monitor._last_error = ""
    monitor.database = Database()
    monitor.clock_ms = lambda: 123
    monitor._run = lambda: None

    def fail_refresh() -> None:
        raise RuntimeError("probe failed")

    monitor.refresh = fail_refresh
    monitor.start()
    monitor._thread.join(timeout=1)

    assert "RuntimeError: probe failed" in monitor._last_error
    assert events[0][:3] == ("system_runtime", "ai_organ_monitor", "startup_error")
    assert events[0][3]["checked_at_ms"] == 123
