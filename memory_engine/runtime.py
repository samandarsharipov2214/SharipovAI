"""Background runtime for passive collection and optional extraction."""
from __future__ import annotations

import threading
from typing import Any

from .learning_bridge import DevelopmentLearningMemoryBridge
from .service import MemoryService


class MemoryRuntime:
    def __init__(self, service: MemoryService, bridge: DevelopmentLearningMemoryBridge | None = None) -> None:
        self.service = service
        self.bridge = bridge or DevelopmentLearningMemoryBridge(service)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_cycle: dict[str, Any] = {}

    def start(self) -> None:
        if not self.service.settings.enabled:
            return
        self.service.initialize()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="memory-layer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def collect_once(self) -> dict[str, Any]:
        bridge = self.bridge.collect_once()
        extraction = self.service.extract_pending()
        self._last_cycle = {"bridge": bridge, "extraction": extraction}
        return dict(self._last_cycle)

    def health(self) -> dict[str, Any]:
        return {
            **self.service.health(),
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "last_cycle": dict(self._last_cycle),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.collect_once()
            except Exception as exc:
                self._last_cycle = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            self._stop.wait(self.service.settings.poll_interval_seconds)


__all__ = ["MemoryRuntime"]
