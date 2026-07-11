"""Runtime manager for the source-based News Intelligence agent network."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

from storage import ProjectDatabase

from .agents import SourceAgent
from .hub import NewsHub
from .sources import SourceCollector, SourceDefinition, source_definitions


class NewsAgentNetwork:
    def __init__(
        self,
        *,
        collector: SourceCollector | None = None,
        database: ProjectDatabase | None = None,
    ) -> None:
        definitions = source_definitions()
        self.collector = collector or SourceCollector(definitions)
        self.database = database
        self.hub = NewsHub(database=database)
        self.agents = [SourceAgent(definition=definition) for definition in definitions]
        self.refresh_seconds = _bounded_int("NEWS_AGENT_REFRESH_SECONDS", default=60, minimum=15, maximum=3600)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._running_cycle = False
        self._last_cycle_at_ms = 0
        self._last_cycle_duration_ms = 0
        self._last_error = ""
        self._cycle_count = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="news-agent-network", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def cycle(self, *, source_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._running_cycle:
                return {"status": "busy", "message": "News agent cycle already running"}
            self._running_cycle = True
        started = int(time.time() * 1000)
        accepted = 0
        duplicates = 0
        fetched_sources = 0
        failures = 0
        selected_agents = [agent for agent in self.agents if source_id is None or agent.definition.source_id == source_id]
        if source_id is not None and not selected_agents:
            with self._lock:
                self._running_cycle = False
            raise KeyError(f"Unknown source agent: {source_id}")
        self.hub.event("cycle_started", "News agent cycle started", data={"source_id": source_id})
        try:
            for agent in selected_agents:
                articles, fetched = self.collector.collect(agent.definition)
                fetched_sources += 1
                result = self.hub.ingest(agent, articles, fetched)
                accepted += result.accepted
                duplicates += result.duplicates
                if fetched.error:
                    failures += 1
                    self.hub.event(
                        "source_error",
                        f"{agent.definition.name}: {fetched.error}",
                        level="warning",
                        data={"source_id": agent.definition.source_id},
                    )
            self._last_error = ""
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self.hub.event("cycle_error", self._last_error, level="error")
            raise
        finally:
            finished = int(time.time() * 1000)
            with self._lock:
                self._running_cycle = False
                self._last_cycle_at_ms = finished
                self._last_cycle_duration_ms = max(finished - started, 0)
                self._cycle_count += 1
        summary = {
            "status": "ok",
            "accepted": accepted,
            "duplicates": duplicates,
            "fetched_sources": fetched_sources,
            "failures": failures,
            "duration_ms": self._last_cycle_duration_ms,
        }
        self.hub.event("cycle_completed", "News agent cycle completed", data=summary)
        return summary

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            running_cycle = self._running_cycle
        return {
            "status": "running" if self._thread and self._thread.is_alive() else "stopped",
            "running_cycle": running_cycle,
            "refresh_seconds": self.refresh_seconds,
            "cycle_count": self._cycle_count,
            "last_cycle_at_ms": self._last_cycle_at_ms,
            "last_cycle_duration_ms": self._last_cycle_duration_ms,
            "last_error": self._last_error,
            "database_backed": self.database is not None,
            "agents": [agent.status() for agent in self.agents],
            "hub": self.hub.state(),
        }

    def agent_snapshot(self, source_id: str) -> dict[str, Any]:
        for agent in self.agents:
            if agent.definition.source_id == source_id:
                return {
                    "agent": agent.status(),
                    "memory": agent.memory(),
                    "hub_memory": [
                        item
                        for item in self.hub.memory(limit=500)
                        if item["agent_id"] == source_id
                    ],
                }
        raise KeyError(f"Unknown source agent: {source_id}")

    def definitions(self) -> list[SourceDefinition]:
        return [agent.definition for agent in self.agents]

    def _run(self) -> None:
        self.hub.event("network_started", "News Intelligence agent network started")
        try:
            self.cycle()
        except Exception:
            pass
        while not self._stop.wait(self.refresh_seconds):
            try:
                self.cycle()
            except Exception:
                continue
        self.hub.event("network_stopped", "News Intelligence agent network stopped")


def _bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)
