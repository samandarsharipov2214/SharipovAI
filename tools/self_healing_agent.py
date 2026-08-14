#!/usr/bin/env python3
"""Bounded, fail-safe self-healing agent for the SharipovAI VPS runtime.

The agent runs *inside* the ``sharipovai`` container.  Host-level actions that
would terminate the current container (restart, compose up, database swap or
Git revert) are requested through small files in the persistent data volume.
The systemd host wrapper validates and executes only an allow-listed action.

This module intentionally does not generate arbitrary source-code patches.
It performs deterministic recovery, verifies evidence, and reverts only a
previous commit explicitly marked as automatic.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest


EXIT_OK = 0
EXIT_ACTION_REQUESTED = 20
EXIT_UNRESOLVED = 30

ACTION_PRIORITY = {
    "none": 0,
    "restart_caddy": 10,
    "compose_up": 30,
    "restart_sharipovai": 35,
    "git_revert": 40,
    "restore_database": 50,
}
CRITICAL_ACTIONS = frozenset({"git_revert", "restore_database"})

AUTO_COMMIT_PREFIX = "[self-healing]"
EXPECTED_CONTAINERS = ("sharipovai", "sharipovai-caddy")
RUNTIME_IGNORES = {
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    ".venv",
    "venv",
}
PATH_PREFIX_IGNORES = (
    "deploy/vps/backups/",
    "deploy/vps/emergency-recovery/",
)
LOG_MARKERS = (
    re.compile(r'"level"\s*:\s*"(ERROR|CRITICAL)"'),
    re.compile(r"^\s*(ERROR|CRITICAL|FATAL)\b", re.MULTILINE),
    re.compile(r"^Traceback \(most recent call last\):", re.MULTILINE),
)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def epoch_seconds() -> int:
    return int(time.time())


def atomic_write_text(path: Path, value: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = {} if default is None else dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return fallback
    return payload if isinstance(payload, dict) else fallback


@dataclass(frozen=True)
class Config:
    repo_dir: Path
    data_dir: Path
    work_dir: Path
    log_file: Path
    state_file: Path
    lock_file: Path
    host_status_file: Path
    host_logs_file: Path
    action_file: Path
    action_meta_file: Path
    expected_sha_file: Path
    db_path: Path
    backup_path: Path
    restore_candidate: Path
    health_url: str
    websocket_url: str
    request_timeout_seconds: float
    pytest_timeout_seconds: int
    websocket_alert_after_seconds: int
    alert_cooldown_seconds: int
    restart_cooldown_seconds: int
    max_related_tests: int
    max_log_bytes: int

    @classmethod
    def from_env(cls) -> "Config":
        data_dir = Path(os.getenv("SHARIPOVAI_DATA_DIR", "/var/lib/sharipovai"))
        work_dir = data_dir / ".self_healing"
        return cls(
            repo_dir=Path(os.getenv("SELF_HEALING_REPO_DIR", "/workspace")),
            data_dir=data_dir,
            work_dir=work_dir,
            log_file=Path(os.getenv("SELF_HEALING_LOG_FILE", str(data_dir / "agent.log"))),
            state_file=Path(os.getenv("SELF_HEALING_STATE_FILE", str(work_dir / "state.json"))),
            lock_file=Path(os.getenv("SELF_HEALING_LOCK_FILE", str(work_dir / "agent.lock"))),
            host_status_file=Path(
                os.getenv("SELF_HEALING_HOST_STATUS_FILE", str(work_dir / "container_status.json"))
            ),
            host_logs_file=Path(
                os.getenv("SELF_HEALING_HOST_LOGS_FILE", str(work_dir / "docker_logs_15m.log"))
            ),
            action_file=Path(os.getenv("SELF_HEALING_ACTION_FILE", str(work_dir / "action"))),
            action_meta_file=Path(
                os.getenv("SELF_HEALING_ACTION_META_FILE", str(work_dir / "action.json"))
            ),
            expected_sha_file=Path(
                os.getenv("SELF_HEALING_EXPECTED_SHA_FILE", str(work_dir / "expected_sha"))
            ),
            db_path=Path(
                os.getenv(
                    "SELF_HEALING_DATABASE_PATH",
                    "/var/lib/sharipovai/sharipovai_shared.db",
                )
            ),
            backup_path=Path(
                os.getenv(
                    "SELF_HEALING_BACKUP_PATH",
                    "/workspace/deploy/vps/backups/latest.tar.gz",
                )
            ),
            restore_candidate=Path(
                os.getenv(
                    "SELF_HEALING_RESTORE_CANDIDATE",
                    str(work_dir / "restore_candidate.db"),
                )
            ),
            health_url=os.getenv("SELF_HEALING_HEALTH_URL", "http://127.0.0.1:8000/health"),
            websocket_url=os.getenv(
                "SELF_HEALING_WEBSOCKET_URL",
                "http://127.0.0.1:8000/api/market/bybit-websocket/status",
            ),
            request_timeout_seconds=float(os.getenv("SELF_HEALING_HTTP_TIMEOUT_SECONDS", "5")),
            pytest_timeout_seconds=int(os.getenv("SELF_HEALING_PYTEST_TIMEOUT_SECONDS", "900")),
            websocket_alert_after_seconds=int(
                os.getenv("SELF_HEALING_WEBSOCKET_ALERT_AFTER_SECONDS", "300")
            ),
            alert_cooldown_seconds=int(
                os.getenv("SELF_HEALING_ALERT_COOLDOWN_SECONDS", "3600")
            ),
            restart_cooldown_seconds=int(
                os.getenv("SELF_HEALING_RESTART_COOLDOWN_SECONDS", "1800")
            ),
            max_related_tests=int(os.getenv("SELF_HEALING_MAX_RELATED_TESTS", "25")),
            max_log_bytes=int(os.getenv("SELF_HEALING_MAX_LOG_BYTES", str(2 * 1024 * 1024))),
        )


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.value = load_json(path)

    def save(self) -> None:
        atomic_write_json(self.path, self.value)


class TelegramNotifier:
    def __init__(self, state: StateStore, logger: logging.Logger, cooldown_seconds: int) -> None:
        self.state = state
        self.logger = logger
        self.cooldown_seconds = cooldown_seconds
        self.token = os.getenv("BOT_TOKEN", "").strip()
        self.owner_id = os.getenv("TELEGRAM_OWNER_ID", "").strip()

    def send(self, title: str, body: str, *, fingerprint: str, force: bool = False) -> bool:
        now = epoch_seconds()
        alerts = self.state.value.setdefault("alerts", {})
        last_sent = int(alerts.get(fingerprint, 0) or 0)
        if not force and now - last_sent < self.cooldown_seconds:
            self.logger.info("Telegram alert suppressed by cooldown: %s", fingerprint)
            return False

        message = f"🛠 SharipovAI Self-Healing\n{title}\n\n{body}".strip()
        message = message[:3900]
        if not self.token or not self.owner_id:
            self.logger.warning(
                "Telegram credentials unavailable; alert retained in log: %s — %s",
                title,
                body[:500],
            )
            return False

        endpoint = f"https://api.telegram.org/bot{self.token}/sendMessage"
        encoded = urlparse.urlencode(
            {
                "chat_id": self.owner_id,
                "text": message,
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        request = urlrequest.Request(endpoint, data=encoded, method="POST")
        try:
            with urlrequest.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise RuntimeError(f"Telegram API rejected alert: {payload!r}")
        except Exception as exc:  # noqa: BLE001 - alerting must never crash recovery
            self.logger.error("Telegram alert failed: %s: %s", type(exc).__name__, exc)
            return False

        alerts[fingerprint] = now
        self.state.save()
        self.logger.info("Telegram alert sent: %s", fingerprint)
        return True


class ActionRequest:
    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.action = "none"
        self.reason = ""
        self.expected_sha = ""
        self.details: dict[str, Any] = {}

    def request(
        self,
        action: str,
        reason: str,
        *,
        expected_sha: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        if action not in ACTION_PRIORITY:
            raise ValueError(f"Unsupported self-healing action: {action}")
        if ACTION_PRIORITY[action] < ACTION_PRIORITY[self.action]:
            self.logger.info(
                "Lower-priority action ignored: requested=%s current=%s",
                action,
                self.action,
            )
            return
        self.action = action
        self.reason = reason.strip()
        self.expected_sha = expected_sha.strip()
        self.details = dict(details or {})
        self.logger.warning("Host action requested: %s — %s", action, self.reason)

    def persist(self) -> None:
        if self.action == "none":
            # A previous unacknowledged host action must never be erased by a
            # later read-only cycle.  The host wrapper clears action files only
            # after the allow-listed recovery command succeeds.
            return

        if self.action in CRITICAL_ACTIONS:
            self._request_critical_owner_approval()
            return

        atomic_write_text(self.config.action_file, self.action + "\n")
        atomic_write_text(self.config.expected_sha_file, self.expected_sha + "\n")
        metadata = {
            "action": self.action,
            "reason": self.reason,
            "expected_sha": self.expected_sha,
            "details": self.details,
            "created_at": utc_now_iso(),
        }
        atomic_write_json(
            self.config.action_meta_file,
            metadata,
        )

    def _request_critical_owner_approval(self) -> None:
        """Create one canonical DCC request; never expose a host action early."""

        pending_path = self.config.work_dir / "critical_action_request.json"
        pending = load_json(pending_path)
        if pending.get("action") == self.action and pending.get("decision_id"):
            self.logger.info("Critical action already awaits owner decision: %s", self.action)
            return
        try:
            head = self.expected_sha or subprocess.run(
                ["git", "-C", str(self.config.repo_dir), "rev-parse", "HEAD"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=15,
            ).stdout.strip().lower()
            from development_control.general_controller import DevelopmentChangeController

            controller = DevelopmentChangeController()
            decision = controller.submit_critical_action(
                self.action,
                reason=self.reason,
                base_sha=head,
                details=self.details,
            )
            decision = controller.security_review(decision.decision_id)
            decision = controller.request_owner_approval(decision.decision_id)
            atomic_write_json(
                pending_path,
                {"action": self.action, "decision_id": decision.decision_id, "created_at": utc_now_iso()},
            )
        except Exception as exc:  # noqa: BLE001 - destructive action must fail closed
            self.logger.error("Critical self-healing approval was not requested: %s", type(exc).__name__)


class SelfHealingAgent:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.config.work_dir.mkdir(parents=True, exist_ok=True)
        self.logger = build_logger(config.log_file)
        self.state = StateStore(config.state_file)
        self.notifier = TelegramNotifier(
            self.state,
            self.logger,
            config.alert_cooldown_seconds,
        )
        self.action = ActionRequest(config, self.logger)
        self.unresolved: list[str] = []
        self.healed: list[str] = []

    def run(self, *, verify_only: bool = False) -> int:
        self.logger.info(
            "Self-healing cycle started: verify_only=%s pid=%s",
            verify_only,
            os.getpid(),
        )
        with self._exclusive_lock():
            self._record_cycle_start()
            self.check_container_snapshot()
            self.check_health()
            self.check_database(allow_restore=not verify_only)
            self.check_recent_logs(allow_repair=not verify_only)
            if not verify_only:
                self.check_changed_modules()
            self.check_websocket(allow_restart=not verify_only)
            self.action.persist()
            self._record_cycle_end()

        if self.action.action != "none":
            return EXIT_ACTION_REQUESTED
        if self.unresolved:
            return EXIT_UNRESOLVED
        return EXIT_OK

    def _record_cycle_start(self) -> None:
        self.state.value["last_cycle_started_at"] = utc_now_iso()
        self.state.value["last_cycle_pid"] = os.getpid()
        self.state.save()

    def _record_cycle_end(self) -> None:
        self.state.value.update(
            {
                "last_cycle_finished_at": utc_now_iso(),
                "last_cycle_result": (
                    "action_requested"
                    if self.action.action != "none"
                    else "unresolved"
                    if self.unresolved
                    else "ok"
                ),
                "last_action": self.action.action,
                "last_healed": self.healed[-20:],
                "last_unresolved": self.unresolved[-20:],
            }
        )
        self.state.save()
        self.logger.info(
            "Self-healing cycle finished: action=%s healed=%d unresolved=%d",
            self.action.action,
            len(self.healed),
            len(self.unresolved),
        )

    def _exclusive_lock(self):
        self.config.lock_file.parent.mkdir(parents=True, exist_ok=True)
        handle = self.config.lock_file.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise RuntimeError("Another self-healing cycle is already running")

        class _Lock:
            def __enter__(inner_self):
                return handle

            def __exit__(inner_self, exc_type, exc, tb):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
                return False

        return _Lock()

    def check_container_snapshot(self) -> None:
        payload = load_json(self.config.host_status_file)
        containers = payload.get("containers")
        if not isinstance(containers, dict):
            message = "Host wrapper did not provide a valid container snapshot."
            self.unresolved.append(message)
            self.notifier.send(
                "Нет снимка Docker",
                message,
                fingerprint="container_snapshot_missing",
            )
            return

        missing_or_stopped: list[str] = []
        for name in EXPECTED_CONTAINERS:
            item = containers.get(name)
            if not isinstance(item, dict) or not item.get("exists") or not item.get("running"):
                missing_or_stopped.append(name)

        if missing_or_stopped:
            names = ", ".join(missing_or_stopped)
            self.action.request("compose_up", f"Containers are missing or stopped: {names}")
            self.notifier.send(
                "Docker требует восстановления",
                f"Не запущены контейнеры: {names}. Запрошен docker compose up -d.",
                fingerprint=f"containers_down:{names}",
            )
            return

        app_health = str((containers.get("sharipovai") or {}).get("health", "none"))
        if app_health not in {"healthy", "none"}:
            self.action.request(
                "restart_sharipovai",
                f"Docker health state is {app_health}",
            )
        self.logger.info("Container snapshot is healthy: %s", containers)

    def check_health(self) -> None:
        try:
            status, payload = self._get_json(self.config.health_url)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            if isinstance(payload, dict) and str(payload.get("status", "ok")).lower() not in {
                "ok",
                "healthy",
            }:
                raise RuntimeError(f"Unexpected health payload: {payload!r}")
        except Exception as exc:  # noqa: BLE001 - recovery boundary
            message = f"Health endpoint failed: {type(exc).__name__}: {exc}"
            self.unresolved.append(message)
            if self._restart_allowed("health"):
                self.action.request("restart_sharipovai", message)
                self._mark_restart_requested("health")
            self.notifier.send(
                "Health endpoint недоступен",
                self._with_log_excerpt(message),
                fingerprint="health_endpoint_failed",
            )
            return

        self.state.value["health_last_ok_at"] = utc_now_iso()
        self.logger.info("Health endpoint is OK")

    def check_database(self, *, allow_restore: bool) -> None:
        result = sqlite_integrity(self.config.db_path)
        if result == "ok":
            self.state.value["database_last_ok_at"] = utc_now_iso()
            self.logger.info("SQLite integrity_check: ok")
            return

        message = f"SQLite integrity_check failed for {self.config.db_path}: {result}"
        self.unresolved.append(message)
        self.logger.critical(message)
        if allow_restore:
            try:
                candidate_info = self.prepare_restore_candidate()
            except Exception as exc:  # noqa: BLE001 - recovery boundary
                failure = (
                    "Database backup recovery preparation failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                self.unresolved.append(failure)
                self.notifier.send(
                    "SQLite повреждена, восстановление не подготовлено",
                    f"{message}\n{failure}",
                    fingerprint="database_restore_failed",
                    force=True,
                )
                return

            self.action.request(
                "restore_database",
                message,
                details=candidate_info,
            )
            self.notifier.send(
                "SQLite повреждена",
                (
                    f"{message}\n"
                    f"Проверенный кандидат восстановления подготовлен: "
                    f"{candidate_info['candidate_path']}. Восстановление не будет "
                    "выполнено без явного одобрения владельца в Telegram."
                ),
                fingerprint="database_restore_requested",
                force=True,
            )
        else:
            self.notifier.send(
                "SQLite integrity_check не пройден",
                message,
                fingerprint="database_integrity_failed_verify",
                force=True,
            )

    def prepare_restore_candidate(self) -> dict[str, Any]:
        backup = self.config.backup_path
        if not backup.is_file():
            raise FileNotFoundError(f"Backup not found: {backup}")
        if backup.stat().st_size <= 0:
            raise RuntimeError(f"Backup is empty: {backup}")

        self.config.restore_candidate.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.restore_candidate.with_suffix(".tmp")
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

        with tarfile.open(backup, mode="r:gz") as archive:
            member = choose_database_member(archive.getmembers(), self.config.db_path.name)
            if member is None:
                raise RuntimeError(
                    f"{self.config.db_path.name} is absent from {backup}"
                )
            if not member.isfile() or member.size <= 0:
                raise RuntimeError("Database backup member is not a regular non-empty file")
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError("Cannot read database member from backup")
            with source, temporary.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
                destination.flush()
                os.fsync(destination.fileno())

        os.chmod(temporary, 0o600)
        candidate_integrity = sqlite_integrity(temporary)
        if candidate_integrity != "ok":
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"Backup database is invalid: {candidate_integrity}")

        os.replace(temporary, self.config.restore_candidate)
        digest = sha256_file(self.config.restore_candidate)
        return {
            "candidate_path": str(self.config.restore_candidate),
            "candidate_sha256": digest,
            "source_backup": str(backup),
            "source_backup_mtime": datetime.fromtimestamp(
                backup.stat().st_mtime, tz=UTC
            ).isoformat(),
            "database_member": member.name,
        }

    def check_recent_logs(self, *, allow_repair: bool) -> None:
        path = self.config.host_logs_file
        try:
            text = read_tail(path, self.config.max_log_bytes)
        except FileNotFoundError:
            self.logger.warning("Docker log snapshot is missing: %s", path)
            return
        if not text.strip():
            self.logger.info("No recent Docker logs")
            return

        excerpts = extract_error_excerpts(text)
        if not excerpts:
            self.logger.info("No fresh ERROR/CRITICAL markers in Docker logs")
            return

        joined = "\n---\n".join(excerpts[-8:])
        fingerprint = "docker_errors:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
        self.logger.error("Fresh Docker errors detected:\n%s", joined)

        lowered = joined.lower()
        if allow_repair and any(
            token in lowered
            for token in (
                "permission denied",
                "unable to open database file",
                "attempt to write a readonly database",
                "read-only database",
            )
        ):
            repaired = self.repair_data_permissions()
            if repaired:
                self.healed.append("data_permissions_repaired")
                if self._restart_allowed("permissions"):
                    self.action.request(
                        "restart_sharipovai",
                        "Repaired /var/lib/sharipovai permissions after log errors",
                    )
                    self._mark_restart_requested("permissions")

        if allow_repair and "database is locked" in lowered and self._restart_allowed(
            "database_locked"
        ):
            self.action.request(
                "restart_sharipovai",
                "Persistent SQLite lock detected in recent logs",
            )
            self._mark_restart_requested("database_locked")

        hard_failures = (
            "no space left on device",
            "out of memory",
            "killed process",
            "segmentation fault",
            "syntaxerror",
            "modulenotfounderror",
            "importerror",
        )
        if any(token in lowered for token in hard_failures):
            self.unresolved.append("Critical application error found in recent logs")

        self.notifier.send(
            "Свежие ERROR/CRITICAL в логах",
            joined[-3000:],
            fingerprint=fingerprint,
        )

    def repair_data_permissions(self) -> bool:
        if os.geteuid() != 0:
            self.logger.error("Permission repair requires root inside the container")
            return False
        uid = int(os.getenv("SELF_HEALING_RUNTIME_UID", "10001"))
        gid = int(os.getenv("SELF_HEALING_RUNTIME_GID", "10001"))
        changed = 0
        for root, directories, files in os.walk(self.config.data_dir, followlinks=False):
            root_path = Path(root)
            if root_path == self.config.work_dir:
                # The self-healing directory is maintained by the root-run agent.
                directories[:] = []
                continue
            for name in directories:
                path = root_path / name
                if path.is_symlink():
                    continue
                os.chown(path, uid, gid)
                os.chmod(path, 0o750)
                changed += 1
            for name in files:
                path = root_path / name
                if path.is_symlink() or path == self.config.log_file:
                    continue
                os.chown(path, uid, gid)
                os.chmod(path, 0o600)
                changed += 1
        os.chown(self.config.data_dir, uid, gid)
        os.chmod(self.config.data_dir, 0o750)
        self.logger.warning("Repaired ownership/mode for %d data paths", changed)
        return True

    def check_changed_modules(self) -> None:
        repo = self.config.repo_dir
        if not (repo / ".git").exists():
            self._record_git_verification_unavailable(
                f"Git repository is unavailable at {repo}"
            )
            return

        try:
            head = self._git("rev-parse", "HEAD").strip()
            last_tested = str(self.state.value.get("last_tested_sha", "")).strip()
            bootstrap = not bool(last_tested)
            if last_tested and self._git_ok("cat-file", "-e", f"{last_tested}^{{commit}}"):
                base = last_tested
            else:
                base = self._git("rev-parse", "HEAD^").strip() if self._git_ok(
                    "rev-parse", "HEAD^"
                ) else head

            changed = set(self._git_lines("diff", "--name-only", f"{base}..{head}"))
            changed.update(self._git_lines("diff", "--name-only"))
            changed.update(self._git_lines("diff", "--name-only", "--cached"))
            changed.update(self._git_lines("ls-files", "--others", "--exclude-standard"))
        except RuntimeError as exc:
            self._record_git_verification_unavailable(str(exc))
            return
        changed = {
            item
            for item in changed
            if not any(item.startswith(prefix) for prefix in PATH_PREFIX_IGNORES)
        }

        fingerprint = self._worktree_fingerprint(head, changed)
        if (
            head == last_tested
            and fingerprint == self.state.value.get("last_tested_fingerprint")
        ):
            self.logger.info("No untested Python changes")
            return
        if not changed:
            self.state.value["last_tested_sha"] = head
            self.state.value["last_tested_fingerprint"] = fingerprint
            self.state.save()
            self.logger.info("No changed Python modules require pytest")
            return

        self.logger.info("Changed Python paths: %s", sorted(changed))
        with tempfile.TemporaryDirectory(prefix="sharipovai-self-healing-") as temporary:
            snapshot = Path(temporary) / "repo"
            copy_repository_snapshot(repo, snapshot)
            tests = discover_related_tests(
                snapshot,
                changed,
                max_tests=self.config.max_related_tests,
            )
            if bootstrap:
                for fixed_test in (
                    "tests/test_self_healing_agent.py",
                    "tests/test_phase11_production_audit.py",
                ):
                    if (snapshot / fixed_test).is_file() and fixed_test not in tests:
                        tests.append(fixed_test)
                tests = sorted(tests)[: self.config.max_related_tests]
            if not tests:
                changed_python = sorted(item for item in changed if item.endswith(".py"))
                if not changed_python:
                    self.logger.info(
                        "Changed paths have no related Python tests: %s",
                        sorted(changed),
                    )
                    self.state.value["last_tested_sha"] = head
                    self.state.value["last_tested_fingerprint"] = fingerprint
                    self.state.save()
                    return
                compile_result = self._run_command(
                    [sys.executable, "-m", "compileall", "-q", *changed_python],
                    cwd=snapshot,
                    timeout=min(self.config.pytest_timeout_seconds, 300),
                    env=self._test_environment(snapshot),
                )
                self._save_test_output(compile_result)
                if compile_result.returncode != 0:
                    self._handle_test_failure(
                        head=head,
                        output=compile_result.stdout,
                        command=compile_result.args,
                    )
                    return
            else:
                result = self._run_command(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "--tb=short",
                        *tests,
                    ],
                    cwd=snapshot,
                    timeout=self.config.pytest_timeout_seconds,
                    env=self._test_environment(snapshot),
                )
                self._save_test_output(result)
                if result.returncode != 0:
                    self._handle_test_failure(
                        head=head,
                        output=result.stdout,
                        command=result.args,
                    )
                    return

        self.state.value["last_tested_sha"] = head
        self.state.value["last_tested_fingerprint"] = fingerprint
        self.state.value["last_pytest_ok_at"] = utc_now_iso()
        self.state.save()
        self.logger.info("Changed-module tests passed")

    def _record_git_verification_unavailable(self, reason: str) -> None:
        """Fail closed without aborting the health checks that follow Git verification."""
        message = f"Changed-module verification unavailable: {reason}"
        self.logger.error(message)
        self.unresolved.append(message)
        self.notifier.send(
            "Self-Healing: Git-проверка недоступна",
            message,
            fingerprint="self_healing_git_unavailable",
        )

    def _handle_test_failure(self, *, head: str, output: str, command: Any) -> None:
        excerpt = output[-3000:]
        subject = self._git("log", "-1", "--pretty=%s").strip()
        last_auto_commit = str(self.state.value.get("last_auto_commit", "")).strip()
        automatic = head == last_auto_commit or subject.startswith(AUTO_COMMIT_PREFIX)

        if automatic:
            self.action.request(
                "git_revert",
                f"Changed-module tests failed after automatic commit: {subject}",
                expected_sha=head,
                details={"command": command, "output_tail": excerpt},
            )
            title = "Автоматический коммит не прошёл тесты"
            body = (
                f"HEAD={head}\nsubject={subject}\n"
                "Git revert ожидает явного одобрения владельца в Telegram "
                "и проверки точного SHA.\n\n"
                f"{excerpt}"
            )
            self.notifier.send(
                title,
                body,
                fingerprint=f"auto_commit_test_failure:{head}",
                force=True,
            )
            return

        self.unresolved.append("Changed-module pytest failed for a non-automatic commit")
        self.notifier.send(
            "Тесты изменённых модулей упали",
            (
                f"HEAD={head}\nКоммит не помечен как автоматический, поэтому откат "
                f"не выполнен.\n\n{excerpt}"
            ),
            fingerprint=f"manual_commit_test_failure:{head}",
            force=True,
        )

    def check_websocket(self, *, allow_restart: bool) -> None:
        try:
            status_code, payload = self._get_json(self.config.websocket_url)
            if status_code != 200 or not isinstance(payload, dict):
                raise RuntimeError(f"HTTP {status_code}: {payload!r}")
        except Exception as exc:  # noqa: BLE001 - recovery boundary
            message = f"Cannot read Bybit WebSocket status: {type(exc).__name__}: {exc}"
            self.unresolved.append(message)
            self.notifier.send(
                "Статус Bybit WebSocket недоступен",
                message,
                fingerprint="bybit_ws_status_unavailable",
            )
            return

        if payload.get("enabled") is False:
            self.state.value.pop("websocket_disconnected_since", None)
            self.logger.info("Bybit WebSocket feature is disabled")
            return

        if payload.get("connected") is True:
            self.state.value.pop("websocket_disconnected_since", None)
            self.state.value["websocket_last_connected_at"] = utc_now_iso()
            self.logger.info("Bybit WebSocket is connected")
            return

        now = epoch_seconds()
        disconnected_at_ms = int(payload.get("disconnected_at_ms") or 0)
        if disconnected_at_ms > 0:
            disconnected_since = disconnected_at_ms // 1000
        else:
            disconnected_since = int(
                self.state.value.setdefault("websocket_disconnected_since", now)
            )
        self.state.save()
        age = max(0, now - disconnected_since)
        self.logger.warning("Bybit WebSocket disconnected for %d seconds", age)

        if age < self.config.websocket_alert_after_seconds:
            return

        message = (
            f"Bybit public WebSocket disconnected for {age} seconds.\n"
            f"worker_running={payload.get('worker_running')}\n"
            f"last_error={payload.get('last_error')}\n"
            f"disconnect_count={payload.get('disconnect_count')}"
        )
        self.unresolved.append(message)
        self.notifier.send(
            "Bybit WebSocket отключён более 5 минут",
            message,
            fingerprint="bybit_ws_disconnected_5m",
        )
        if allow_restart and self._restart_allowed("bybit_ws"):
            self.action.request("restart_sharipovai", message)
            self._mark_restart_requested("bybit_ws")

    def _get_json(self, url: str) -> tuple[int, Any]:
        request = urlrequest.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "SharipovAI-SelfHealing/1.0"},
        )
        try:
            with urlrequest.urlopen(
                request,
                timeout=self.config.request_timeout_seconds,
            ) as response:
                status = int(response.status)
                raw = response.read(2 * 1024 * 1024)
        except urlerror.HTTPError as exc:
            raw = exc.read(2 * 1024 * 1024)
            status = int(exc.code)
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        return status, payload

    def _with_log_excerpt(self, message: str) -> str:
        try:
            text = read_tail(self.config.host_logs_file, 24_000)
        except FileNotFoundError:
            return message
        excerpts = extract_error_excerpts(text)
        if not excerpts:
            return message
        return f"{message}\n\nПоследние ошибки:\n" + "\n---\n".join(excerpts[-3:])[-2500:]

    def _restart_allowed(self, reason: str) -> bool:
        now = epoch_seconds()
        requests = self.state.value.setdefault("restart_requests", {})
        last = int(requests.get(reason, 0) or 0)
        return now - last >= self.config.restart_cooldown_seconds

    def _mark_restart_requested(self, reason: str) -> None:
        requests = self.state.value.setdefault("restart_requests", {})
        requests[reason] = epoch_seconds()
        self.state.save()

    def _git(self, *arguments: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-c", f"safe.directory={self.config.repo_dir}", *arguments],
                cwd=self.config.repo_dir,
                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise RuntimeError(
                f"git executable is unavailable: {type(exc).__name__}: {exc}"
            ) from exc
        stderr = result.stderr.strip()
        if result.returncode != 0:
            details = result.stdout.strip()
            if stderr:
                details = f"{details}\n{stderr}".strip()
            raise RuntimeError(
                f"git {' '.join(arguments)} failed: {details}"
            )
        if stderr:
            self.logger.warning(
                "Git diagnostic for %s: %s",
                " ".join(arguments),
                stderr[:2000],
            )
        return result.stdout

    def _git_ok(self, *arguments: str) -> bool:
        try:
            self._git(*arguments)
        except RuntimeError:
            return False
        return True

    def _git_lines(self, *arguments: str) -> list[str]:
        return [line.strip() for line in self._git(*arguments).splitlines() if line.strip()]

    def _worktree_fingerprint(self, head: str, changed: Iterable[str]) -> str:
        digest = hashlib.sha256(head.encode("utf-8"))
        for relative in sorted(changed):
            digest.update(relative.encode("utf-8"))
            path = self.config.repo_dir / relative
            try:
                if path.is_file():
                    digest.update(path.read_bytes())
                else:
                    digest.update(b"<deleted>")
            except OSError as exc:
                digest.update(
                    f"<unreadable:{type(exc).__name__}>".encode("utf-8")
                )
        return digest.hexdigest()

    def _test_environment(self, snapshot: Path) -> dict[str, str]:
        runtime = snapshot.parent / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        temporary_db = runtime / "pytest-self-healing.db"
        environment = dict(os.environ)
        environment.update(
            {
                "PYTHONPATH": str(snapshot),
                "ENVIRONMENT": "development",
                "SHARIPOVAI_DISABLE_AUTH": "1",
                "AUTH_SECRET": "self-healing-test-secret-not-production",
                "ADMIN_USERNAME": "self-healing-ci",
                "ADMIN_PASSWORD": "self-healing-ci-password",
                "DATABASE_URL": f"sqlite:///{temporary_db}",
                "VIRTUAL_ACCOUNT_STATE_FILE": str(
                    runtime / "pytest-virtual-account.json"
                ),
                "DEMO_STATE_FILE": str(runtime / "pytest-demo.json"),
                "AUTONOMOUS_PAPER_STATE_FILE": str(
                    runtime / "pytest-paper.json"
                ),
                "TESTNET_BRIDGE_STATE_FILE": str(
                    runtime / "pytest-testnet-bridge.json"
                ),
                "EXECUTION_JOURNAL_FILE": str(
                    runtime / "pytest-execution-journal.json"
                ),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTEST_ADDOPTS": "-p no:cacheprovider",
                "FEATURE_BYBIT_LIVE_EXECUTION": "0",
                "FEATURE_BYBIT_TESTNET": "0",
                "EXECUTION_KILL_SWITCH": "1",
            }
        )
        return environment

    def _run_command(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout: int,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        self.logger.info("Running verification command: %s", command)
        try:
            return subprocess.run(
                command,
                cwd=cwd,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raw_output = exc.stdout or ""
            if isinstance(raw_output, bytes):
                raw_output = raw_output.decode("utf-8", errors="replace")
            output = str(raw_output) + "\nSELF_HEALING_TIMEOUT\n"
            return subprocess.CompletedProcess(command, 124, output, "")

    def _save_test_output(self, result: subprocess.CompletedProcess[str]) -> None:
        output_path = self.config.work_dir / "last_pytest.log"
        text = str(result.stdout or "")
        if len(text.encode("utf-8")) > self.config.max_log_bytes:
            text = text[-self.config.max_log_bytes :]
        atomic_write_text(
            output_path,
            f"command={result.args!r}\nreturncode={result.returncode}\n{text}",
        )


def build_logger(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sharipovai.self_healing")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            "%Y-%m-%dT%H:%M:%S%z",
        )
        file_handler = RotatingFileHandler(
            path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        if os.getenv("SELF_HEALING_STDERR", "0").strip().lower() in {
            "1",
            "true",
            "yes",
        }:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)
    return logger


def sqlite_integrity(path: Path) -> str:
    if not path.is_file():
        return "database file is missing"
    if path.stat().st_size <= 0:
        return "database file is empty"
    uri = f"file:{urlparse.quote(str(path), safe='/')}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        return f"{type(exc).__name__}: {exc}"
    values = [str(row[0]) for row in rows if row]
    return "ok" if values == ["ok"] else "; ".join(values[:20]) or "no integrity result"


def choose_database_member(
    members: Iterable[tarfile.TarInfo],
    expected_name: str,
) -> tarfile.TarInfo | None:
    regular = [member for member in members if member.isfile()]
    exact = [
        member
        for member in regular
        if Path(member.name).name == expected_name
    ]
    if not exact:
        return None
    exact.sort(key=lambda item: (item.name.count("/"), -item.size, item.name))
    return exact[0]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tail(path: Path, max_bytes: int) -> str:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        raw = handle.read()
    return raw.decode("utf-8", errors="replace")


def extract_error_excerpts(text: str, *, context_lines: int = 4) -> list[str]:
    lines = text.splitlines()
    indexes: set[int] = set()
    for index, line in enumerate(lines):
        if any(pattern.search(line) for pattern in LOG_MARKERS):
            indexes.add(index)
    if not indexes:
        return []

    groups: list[tuple[int, int]] = []
    for index in sorted(indexes):
        start = max(0, index - context_lines)
        end = min(len(lines), index + context_lines + 1)
        if groups and start <= groups[-1][1] + 1:
            groups[-1] = (groups[-1][0], max(groups[-1][1], end))
        else:
            groups.append((start, end))
    return ["\n".join(lines[start:end]) for start, end in groups[-12:]]


def copy_repository_snapshot(source: Path, destination: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        directory_path = Path(directory)
        try:
            relative = directory_path.relative_to(source).as_posix()
        except ValueError:
            relative = ""
        ignored = {
            name
            for name in names
            if name in RUNTIME_IGNORES
            or name.startswith(".env")
            or name.endswith((".pem", ".key", ".p12", ".pfx"))
        }
        if relative == "deploy/vps":
            ignored.update(
                name
                for name in names
                if name in {"backups", "emergency-recovery"}
                or name.startswith("docker-compose.yml.bak-")
                or name.startswith(".env")
            )
        ignored.update(
            name
            for name in names
            if name.endswith(
                (
                    ".db",
                    ".db-wal",
                    ".db-shm",
                    ".sqlite",
                    ".sqlite3",
                    ".log",
                    ".pyc",
                )
            )
        )
        return ignored

    shutil.copytree(source, destination, ignore=ignore, symlinks=False)


def discover_related_tests(
    repo: Path,
    changed: set[str],
    *,
    max_tests: int,
) -> list[str]:
    candidates: list[Path] = []
    for root in (repo / "tests", repo / "dashboard" / "tests"):
        if root.is_dir():
            candidates.extend(sorted(root.rglob("test_*.py")))

    selected: set[str] = set()
    tokens: set[str] = set()
    for relative in changed:
        path = Path(relative)
        if path.name.startswith("test_") and path.suffix == ".py":
            selected.add(relative)
        if relative == "Dockerfile" or relative.startswith("deploy/vps/"):
            audit = repo / "tests" / "test_phase11_production_audit.py"
            if audit.is_file():
                selected.add(audit.relative_to(repo).as_posix())
        if path.suffix != ".py" or path.stem in {"__init__", "conftest"}:
            continue
        dotted = ".".join(path.with_suffix("").parts)
        tokens.add(dotted)
        if len(path.stem) >= 5:
            tokens.add(path.stem)

        if relative.startswith("dashboard/"):
            for candidate in candidates:
                if "dashboard/tests" in candidate.as_posix():
                    selected.add(candidate.relative_to(repo).as_posix())
        if relative.startswith(("exchange_connector/", "autonomous_trading/")):
            for candidate in candidates:
                name = candidate.name.lower()
                if any(part in name for part in ("bybit", "market_stream", "exchange")):
                    selected.add(candidate.relative_to(repo).as_posix())

    for candidate in candidates:
        if len(selected) >= max_tests:
            break
        try:
            content = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(token in content for token in tokens):
            selected.add(candidate.relative_to(repo).as_posix())

    return sorted(selected)[:max_tests]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Run checks without preparing repairs or requesting restarts.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = Config.from_env()
    try:
        return SelfHealingAgent(config).run(verify_only=args.verify_only)
    except RuntimeError as exc:
        logger = build_logger(config.log_file)
        logger.error("Self-healing agent aborted: %s", exc)
        return EXIT_UNRESOLVED
    except Exception as exc:  # noqa: BLE001 - final safety boundary
        logger = build_logger(config.log_file)
        logger.exception("Unexpected self-healing failure: %s", exc)
        state = StateStore(config.state_file)
        notifier = TelegramNotifier(
            state,
            logger,
            config.alert_cooldown_seconds,
        )
        notifier.send(
            "Self-Healing Agent аварийно завершился",
            f"{type(exc).__name__}: {exc}",
            fingerprint="self_healing_unexpected_failure",
            force=True,
        )
        return EXIT_UNRESOLVED


if __name__ == "__main__":
    raise SystemExit(main())
