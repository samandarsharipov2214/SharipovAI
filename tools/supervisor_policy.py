"""Restart budgets, cooldowns, and quarantine for SharipovAI services."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class ServicePolicy:
    max_restarts: int = 4
    window_seconds: int = 300
    cooldown_seconds: int = 30
    quarantine_seconds: int = 600
    restarts: deque[float] = field(default_factory=deque)
    last_restart: float = 0.0
    quarantined_until: float = 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self.restarts and self.restarts[0] < cutoff:
            self.restarts.popleft()

    def decision(self, now: float | None = None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        self._prune(now)
        if now < self.quarantined_until:
            return False, "quarantined"
        if now - self.last_restart < self.cooldown_seconds:
            return False, "cooldown"
        if len(self.restarts) >= self.max_restarts:
            self.quarantined_until = now + self.quarantine_seconds
            return False, "quarantined"
        return True, "allowed"

    def record_restart(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._prune(now)
        self.restarts.append(now)
        self.last_restart = now

    def record_healthy(self) -> None:
        self.restarts.clear()
        self.quarantined_until = 0.0

    def snapshot(self, now: float | None = None) -> dict[str, object]:
        now = time.time() if now is None else now
        self._prune(now)
        allowed, reason = self.decision(now)
        return {
            "allowed": allowed,
            "reason": reason,
            "restart_count_window": len(self.restarts),
            "quarantined_until": self.quarantined_until or None,
            "cooldown_remaining": max(0.0, self.cooldown_seconds - (now - self.last_restart)),
        }
