"""Fail-closed CI runtime-state reset and execution-safety audit.

The test workflows run several independent pytest processes on the same
self-hosted workspace. This module removes only explicitly configured runtime
state targets and rejects unsafe trading environment values before a suite is
started. It never scans arbitrary directories and it never mutates credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

_FILE_ENVIRONMENT_VARIABLES: tuple[str, ...] = (
    "AUTONOMOUS_PAPER_STATE_FILE",
    "VIRTUAL_ACCOUNT_STATE_FILE",
    "MARKET_STREAM_STATE_FILE",
    "TESTNET_BRIDGE_STATE_FILE",
    "EXECUTION_JOURNAL_FILE",
)
_DIRECTORY_ENVIRONMENT_VARIABLES: tuple[str, ...] = (
    "SHARIPOVAI_DATA_DIR",
)
_DISABLED_EXECUTION_VARIABLES: tuple[str, ...] = (
    "AUTONOMOUS_PAPER_ENABLED",
    "AUTONOMOUS_TESTNET_ENABLED",
    "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
    "TESTNET_EXECUTION_ENABLED",
    "FEATURE_BYBIT_PRIVATE_ORDER_WS",
    "RUNTIME_FILL_HARVESTER_ENABLED",
    "SCHEDULED_CAMPAIGN_ORCHESTRATOR_ENABLED",
    "EXCHANGE_LIVE_TRADING_ENABLED",
    "FEATURE_BYBIT_LIVE_EXECUTION",
    "FEATURE_BYBIT_TESTNET_EXECUTION",
    "LIVE_EXECUTION_MANUAL_UNLOCK",
)
_FALSE_VALUES = {"", "0", "false", "no", "off"}
_TRUE_VALUES = {"1", "true", "yes", "on"}
_SQLITE_PREFIXES = ("sqlite:///", "sqlite+pysqlite:///")


@dataclass(frozen=True, slots=True)
class RuntimeStateTarget:
    source: str
    path: str
    kind: str


@dataclass(frozen=True, slots=True)
class RuntimeStateResetReport:
    status: str
    apply: bool
    authorized: bool
    workspace: str
    targets: tuple[RuntimeStateTarget, ...]
    removed: tuple[str, ...]
    absent: tuple[str, ...]
    violations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "targets": [asdict(target) for target in self.targets],
            "removed": list(self.removed),
            "absent": list(self.absent),
            "violations": list(self.violations),
        }


def execution_safety_violations(environment: Mapping[str, str]) -> list[str]:
    """Return deterministic violations for a CI environment that could trade."""

    violations: list[str] = []
    if str(environment.get("EXECUTION_KILL_SWITCH", "1")).strip().lower() not in _TRUE_VALUES:
        violations.append("EXECUTION_KILL_SWITCH must remain enabled")

    for name in _DISABLED_EXECUTION_VARIABLES:
        value = str(environment.get(name, "0")).strip().lower()
        if value not in _FALSE_VALUES:
            violations.append(f"{name} must be disabled")

    mode = str(environment.get("EXCHANGE_MODE", "sandbox")).strip().lower()
    if mode not in {"sandbox", "testnet"}:
        violations.append("EXCHANGE_MODE must be sandbox or testnet")

    base_url = str(environment.get("EXCHANGE_BASE_URL", "")).strip().lower().rstrip("/")
    if base_url in {"https://api.bybit.com", "http://api.bybit.com"}:
        violations.append("production Bybit base URL is forbidden in CI")

    release_gate = str(environment.get("PHASE6_TESTNET_RELEASE_GATE", "blocked")).strip().lower()
    if release_gate == "green":
        violations.append("PHASE6_TESTNET_RELEASE_GATE must not be green in CI")
    return sorted(set(violations))


def collect_runtime_state_targets(
    environment: Mapping[str, str],
    *,
    workspace: str | os.PathLike[str],
) -> tuple[RuntimeStateTarget, ...]:
    """Collect explicit state targets; no filesystem discovery is performed."""

    workspace_path = Path(workspace).expanduser().resolve(strict=False)
    targets: list[RuntimeStateTarget] = []

    database_url = str(environment.get("DATABASE_URL", "")).strip()
    sqlite_path = _sqlite_path(database_url)
    if sqlite_path is not None and sqlite_path != Path(":memory:"):
        targets.append(RuntimeStateTarget("DATABASE_URL", str(sqlite_path), "file"))
        for suffix in ("-journal", "-shm", "-wal"):
            targets.append(
                RuntimeStateTarget("DATABASE_URL", f"{sqlite_path}{suffix}", "file")
            )

    for name in _FILE_ENVIRONMENT_VARIABLES:
        value = str(environment.get(name, "")).strip()
        if value:
            targets.append(RuntimeStateTarget(name, value, "file"))

    for name in _DIRECTORY_ENVIRONMENT_VARIABLES:
        value = str(environment.get(name, "")).strip()
        if value:
            targets.append(RuntimeStateTarget(name, value, "directory"))

    # A local coverage data file can otherwise leak between coverage subprocesses.
    targets.append(RuntimeStateTarget("coverage", str(workspace_path / ".coverage"), "file"))

    deduplicated: dict[tuple[str, str], RuntimeStateTarget] = {}
    for target in targets:
        resolved = str(Path(target.path).expanduser().resolve(strict=False))
        deduplicated[(resolved, target.kind)] = RuntimeStateTarget(
            source=target.source,
            path=resolved,
            kind=target.kind,
        )
    return tuple(
        sorted(deduplicated.values(), key=lambda item: (item.path, item.kind, item.source))
    )


def reset_runtime_state(
    environment: Mapping[str, str] | None = None,
    *,
    workspace: str | os.PathLike[str] | None = None,
    apply: bool = False,
) -> RuntimeStateResetReport:
    """Audit and optionally remove configured CI state targets."""

    values: Mapping[str, str] = os.environ if environment is None else environment
    root = Path(workspace or values.get("GITHUB_WORKSPACE") or os.getcwd()).resolve(strict=False)
    targets = collect_runtime_state_targets(values, workspace=root)
    violations = execution_safety_violations(values)
    authorized = _reset_authorized(values)
    if apply and not authorized:
        violations.append(
            "state reset requires GITHUB_ACTIONS=true or SHARIPOVAI_ALLOW_CI_STATE_RESET=1"
        )

    for target in targets:
        if not _safe_target(Path(target.path), workspace=root):
            violations.append(f"unsafe reset target rejected: {target.path}")

    removed: list[str] = []
    absent: list[str] = []
    if apply and not violations:
        for target in targets:
            path = Path(target.path)
            if not path.exists() and not path.is_symlink():
                absent.append(str(path))
                continue
            if target.kind == "directory":
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(str(path))

    status = "ok" if not violations else "blocked"
    return RuntimeStateResetReport(
        status=status,
        apply=bool(apply),
        authorized=authorized,
        workspace=str(root),
        targets=targets,
        removed=tuple(removed),
        absent=tuple(absent),
        violations=tuple(sorted(set(violations))),
    )


def _sqlite_path(database_url: str) -> Path | None:
    if not database_url:
        return None
    for prefix in _SQLITE_PREFIXES:
        if database_url.startswith(prefix):
            raw = database_url[len(prefix) :]
            if raw == ":memory:":
                return Path(":memory:")
            # sqlite:////tmp/file.db leaves /tmp/file.db after removing sqlite:///.
            return Path(raw).expanduser().resolve(strict=False)
    return None


def _safe_target(path: Path, *, workspace: Path) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    temporary_root = Path("/tmp").resolve(strict=False)
    if resolved in {Path("/"), temporary_root, workspace}:
        return False
    return _is_within(resolved, temporary_root) or _is_within(resolved, workspace)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _reset_authorized(environment: Mapping[str, str]) -> bool:
    return (
        str(environment.get("GITHUB_ACTIONS", "")).strip().lower() in _TRUE_VALUES
        or str(environment.get("SHARIPOVAI_ALLOW_CI_STATE_RESET", "")).strip().lower()
        in _TRUE_VALUES
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="remove safe configured targets")
    parser.add_argument("--report", help="optional JSON report path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = reset_runtime_state(apply=bool(args.apply))
    payload = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
    print(payload)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(payload + "\n", encoding="utf-8")
    return 0 if report.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
