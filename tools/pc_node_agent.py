"""Self-healing supervisor for the SharipovAI Windows PC node."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def web_healthy(url: str, timeout: float = 4.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except OSError:
        return False


def backup_fresh(manifest: Path, maximum_age: int) -> bool:
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
        return time.time() - created.timestamp() <= maximum_age
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


@dataclass
class Status:
    started_at: str
    updated_at: str
    web_healthy: bool = False
    backup_healthy: bool = False
    node_restarts: int = 0
    backup_restarts: int = 0
    last_error: str | None = None


class SingleInstance:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "SingleInstance":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("SharipovAI PC agent is already running") from exc
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is not None:
            if os.name == "nt":
                import msvcrt
                try:
                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            self.handle.close()


class Agent:
    def __init__(self, project_root: Path) -> None:
        self.root = project_root.resolve()
        self.env = load_env(self.root / ".env.local")
        self.host = self.env.get("SHARIPOVAI_HOST", "127.0.0.1")
        self.port = int(self.env.get("SHARIPOVAI_PORT", "8000"))
        self.interval = max(int(self.env.get("PC_AGENT_INTERVAL_SECONDS", "15")), 5)
        self.max_backup_age = max(int(self.env.get("PC_AGENT_BACKUP_MAX_AGE_SECONDS", "45")), 20)
        self.cooldown = max(int(self.env.get("PC_AGENT_RESTART_COOLDOWN_SECONDS", "30")), 10)
        self.runtime = self.root / "runtime"
        self.logs = self.runtime / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        stamp = now_iso()
        self.status = Status(stamp, stamp)
        self.last_node_restart = 0.0
        self.last_backup_restart = 0.0
        self.python = self.root / ".venv" / "Scripts" / "python.exe"

    def log(self, level: str, event: str, **details: object) -> None:
        record = {"time": now_iso(), "level": level, "event": event, **details}
        with (self.logs / "pc_agent.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def save(self) -> None:
        self.status.updated_at = now_iso()
        path = self.runtime / "pc_agent_status.json"
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(asdict(self.status), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def spawn(self, args: list[str], log_name: str, env: dict[str, str] | None = None) -> None:
        if not self.python.exists():
            raise FileNotFoundError(f"Python environment not found: {self.python}")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with (self.logs / log_name).open("a", encoding="utf-8") as output:
            subprocess.Popen(
                args,
                cwd=self.root,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                close_fds=True,
            )

    def start_node(self) -> None:
        env = os.environ.copy()
        env.update(self.env)
        self.spawn(
            [str(self.python), "-m", "uvicorn", "dashboard:app", "--host", self.host, "--port", str(self.port)],
            "pc_node.log",
            env,
        )

    def start_backup(self) -> None:
        source = self.env.get("SHARIPOVAI_DATA_DIR", str(self.root / "data"))
        destination = self.env.get("SHARIPOVAI_BACKUP_DIR", str(self.runtime / "backups"))
        self.spawn(
            [str(self.python), str(self.root / "tools" / "pc_node_backup.py"), "--source", source, "--backup-root", destination, "--interval", "10"],
            "pc_backup.log",
        )

    def tick(self) -> None:
        self.status.web_healthy = web_healthy(f"http://{self.host}:{self.port}/health")
        self.status.backup_healthy = backup_fresh(
            self.runtime / "backups" / "current" / "manifest.json",
            self.max_backup_age,
        )
        current = time.time()

        if not self.status.web_healthy and current - self.last_node_restart >= self.cooldown:
            try:
                self.start_node()
                self.last_node_restart = current
                self.status.node_restarts += 1
                self.log("warning", "node_restart", count=self.status.node_restarts)
            except Exception as exc:
                self.status.last_error = f"node: {type(exc).__name__}: {exc}"
                self.log("error", "node_restart_failed", error=self.status.last_error)

        if not self.status.backup_healthy and current - self.last_backup_restart >= self.cooldown:
            try:
                self.start_backup()
                self.last_backup_restart = current
                self.status.backup_restarts += 1
                self.log("warning", "backup_restart", count=self.status.backup_restarts)
            except Exception as exc:
                self.status.last_error = f"backup: {type(exc).__name__}: {exc}"
                self.log("error", "backup_restart_failed", error=self.status.last_error)

        if self.status.web_healthy and self.status.backup_healthy:
            self.status.last_error = None
        self.save()

    def run(self) -> None:
        self.log("info", "agent_started", project_root=str(self.root))
        while True:
            try:
                self.tick()
            except Exception as exc:
                self.status.last_error = f"agent: {type(exc).__name__}: {exc}"
                self.log("error", "agent_tick_failed", error=self.status.last_error)
                self.save()
            time.sleep(self.interval)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    lock = args.project_root / "runtime" / "pc_agent.lock"
    try:
        with SingleInstance(lock):
            agent = Agent(args.project_root)
            if args.once:
                agent.tick()
                print(json.dumps(asdict(agent.status), ensure_ascii=False, indent=2))
                return 0
            agent.run()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
