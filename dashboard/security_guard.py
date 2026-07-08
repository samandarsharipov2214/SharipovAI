"""Security guard utilities for authentication protection."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


DEFAULT_MAX_FAILED_ATTEMPTS = 5
DEFAULT_LOCK_SECONDS = 15 * 60


class LoginAttemptGuard:
    """Track failed login attempts and temporary lockouts."""

    def __init__(self, path: str | Path, *, max_failed_attempts: int = DEFAULT_MAX_FAILED_ATTEMPTS, lock_seconds: int = DEFAULT_LOCK_SECONDS) -> None:
        self.path = Path(path)
        self.max_failed_attempts = max_failed_attempts
        self.lock_seconds = lock_seconds

    def is_locked(self, username: str, *, now: int | None = None) -> bool:
        """Return whether a username is currently locked."""

        now = int(time.time()) if now is None else now
        record = self._load().get("users", {}).get(self._key(username), {})
        locked_until = int(record.get("locked_until", 0) or 0)
        return locked_until > now

    def seconds_left(self, username: str, *, now: int | None = None) -> int:
        """Return remaining lockout seconds."""

        now = int(time.time()) if now is None else now
        record = self._load().get("users", {}).get(self._key(username), {})
        locked_until = int(record.get("locked_until", 0) or 0)
        return max(0, locked_until - now)

    def record_failure(self, username: str, *, now: int | None = None) -> dict[str, Any]:
        """Record one failed login attempt and lock the user if needed."""

        now = int(time.time()) if now is None else now
        data = self._load()
        users = data.setdefault("users", {})
        key = self._key(username)
        record = users.setdefault(key, {"failed_attempts": 0, "locked_until": 0})

        if int(record.get("locked_until", 0) or 0) > now:
            self._save(data)
            return {"status": "locked", "failed_attempts": int(record.get("failed_attempts", 0) or 0), "locked_until": int(record.get("locked_until", 0) or 0)}

        failed_attempts = int(record.get("failed_attempts", 0) or 0) + 1
        record["failed_attempts"] = failed_attempts
        record["last_failed_at"] = now

        if failed_attempts >= self.max_failed_attempts:
            record["locked_until"] = now + self.lock_seconds
            status = "locked"
        else:
            status = "failed"

        self._save(data)
        return {"status": status, "failed_attempts": failed_attempts, "locked_until": int(record.get("locked_until", 0) or 0)}

    def record_success(self, username: str) -> None:
        """Clear failed attempts after a successful login."""

        data = self._load()
        users = data.setdefault("users", {})
        users[self._key(username)] = {"failed_attempts": 0, "locked_until": 0, "last_success_at": int(time.time())}
        self._save(data)

    def snapshot(self, *, now: int | None = None) -> dict[str, Any]:
        """Return a safe snapshot of lockout state."""

        now = int(time.time()) if now is None else now
        data = self._load()
        users: dict[str, Any] = {}
        for username, record in data.get("users", {}).items():
            locked_until = int(record.get("locked_until", 0) or 0)
            users[username] = {
                "failed_attempts": int(record.get("failed_attempts", 0) or 0),
                "locked": locked_until > now,
                "locked_until": locked_until,
                "seconds_left": max(0, locked_until - now),
                "last_failed_at": int(record.get("last_failed_at", 0) or 0),
                "last_success_at": int(record.get("last_success_at", 0) or 0),
            }
        return {"users": users, "max_failed_attempts": self.max_failed_attempts, "lock_seconds": self.lock_seconds}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"users": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("users"), dict):
                return data
        except Exception:
            return {"users": {}}
        return {"users": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _key(username: str) -> str:
        return username.strip().lower()
