"""Bounded asynchronous evidence writer, isolated from PAPER decision authority."""
from __future__ import annotations

import time
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4

from learning_engine.paper_economic_shadow import assess_opportunity, digest, read_sources
from storage import ProjectDatabase, VersionConflict


class EconomicOpportunityObserver:
    def __init__(self, database: ProjectDatabase, *, capacity: int = 128) -> None:
        if capacity < 1:
            raise ValueError("observer capacity must be positive")
        self.database = database
        self.queue: Queue = Queue(maxsize=capacity)
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self.session_id = uuid4().hex
        self.recorded = self.dropped = self.failed = 0
        self.error_type: str | None = None
        self.last_recorded_at_ms: int | None = None
        self._source_watermark = None
        self._sources = None
        self.source_refreshes = self.source_cache_hits = 0

    def start(self) -> None:
        with self._lock:
            self._stop.clear()
            if self._thread is None or not self._thread.is_alive():
                self._thread = Thread(target=self._run, name="paper-economic-observer", daemon=True)
                self._thread.start()

    def submit(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self._lock:
            if self._stop.is_set():
                self.dropped += len(rows)
                return
            if self._thread is None:
                self._thread = Thread(target=self._run, name="paper-economic-observer", daemon=True)
                self._thread.start()
        try:
            self.queue.put_nowait(rows)
        except Full:
            self.dropped += len(rows)

    def status(self) -> dict[str, Any]:
        return {"status": "degraded" if self.dropped or self.failed else "ok" if self.recorded else "waiting",
            "session_id": self.session_id, "recorded": self.recorded,
            "dropped": self.dropped, "failed": self.failed, "queued_batches": self.queue.qsize(),
            "error_type": self.error_type, "last_recorded_at_ms": self.last_recorded_at_ms,
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "source_refreshes": self.source_refreshes, "source_cache_hits": self.source_cache_hits,
            "coverage": "GAPS_PRESENT" if self.dropped or self.failed else "ASYNC_BEST_EFFORT",
            "execution_authority": False, "policy_influence": "SHADOW_ONLY"}

    def stop(self) -> None:
        self._stop.set()

    def record_batch(self, rows: list[dict[str, Any]]) -> None:
        """Synchronous boundary used by the worker and deterministic validation."""
        if not rows:
            return
        scope = rows[0]["scope"]
        if any(row["scope"] != scope for row in rows):
            raise ValueError("opportunity batch must have one canonical PAPER scope")
        cutoff = max(row["decision_time_ms"] for row in rows)
        # Reuse immutable history only while its exact count/version/time
        # watermark is unchanged. New outcomes, epochs and equivalence revokes
        # invalidate it; every assessment still applies its own as-of cutoff.
        with self.database.connect() as connection:
            versions = self.database._fetchall(connection,
                "SELECT namespace,COUNT(*) AS n,MAX(updated_at_ms) AS latest,SUM(version) AS revisions "
                "FROM project_kv WHERE namespace IN (?,?,?) AND updated_at_ms < ? GROUP BY namespace",
                (f"paper_trades:{scope}", "self_learning_outcomes_v2", "paper_strategy_epochs", cutoff))
            links = self.database._fetchall(connection,
                "SELECT COUNT(*) AS n,MAX(created_at_ms) AS latest FROM project_events "
                "WHERE namespace=? AND entity_type=? AND created_at_ms < ?",
                ("paper_policy_equivalence", "equivalence", cutoff))
        watermark = digest([scope, versions, links])
        if self._sources is None or watermark != self._source_watermark:
            self._sources = read_sources(self.database, scope, asof_ms=cutoff)
            self._source_watermark = watermark
            self.source_refreshes += 1
        else:
            self.source_cache_hits += 1
        sources = self._sources
        for row in rows:
            namespace = "paper_economic_opportunities:" + scope
            existing = self.database.list_events(namespace, entity_type="opportunity",
                entity_id=row["opportunity_id"], limit=1)
            if existing:
                if existing[0]["payload"].get("capture_digest") != digest(row):
                    raise ValueError("conflicting opportunity capture is immutable")
                continue
            assessment = assess_opportunity(row, sources)
            context = assessment.pop("learning_context")
            context_id = digest(context)
            if self.database.get_json("paper_learning_shadow_contexts", context_id) is None:
                try:
                    self.database.put_json("paper_learning_shadow_contexts", context_id, context, expected_version=0)
                except VersionConflict:
                    pass  # Content-addressed immutable context; a concurrent identical write is safe.
            recorded_at = int(time.time() * 1000)
            payload = {**row, **assessment, "learning_context_id": context_id, "capture_digest": digest(row),
                "learning_sample_size": context["cohort"]["sample_size"],
                "observer_session_id": self.session_id, "recorded_at_ms": recorded_at,
                "capture_durability": "ASYNC_BEST_EFFORT; process-stop and queue gaps must be measured"}
            self.database.append_event(namespace, "opportunity",
                row["opportunity_id"], payload, event_id=row["opportunity_id"], created_at_ms=recorded_at)
            self.recorded += 1
            self.last_recorded_at_ms = recorded_at
        self.database.put_json("paper_economic_observer_status", scope, self.status())

    def _run(self) -> None:
        while not self._stop.is_set() or not self.queue.empty():
            try:
                rows = self.queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                self.record_batch(rows)
            except Exception as error:
                self.failed += len(rows)
                # DB exceptions can contain connection details: expose type only.
                self.error_type = type(error).__name__
                try:
                    self.database.put_json("paper_economic_observer_status", rows[0]["scope"], self.status())
                except Exception:
                    pass  # Live status still exposes the failure if storage is unavailable.
            finally:
                self.queue.task_done()
