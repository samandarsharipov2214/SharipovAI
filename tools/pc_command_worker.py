"""Execute allow-listed control-plane commands on the local PC node."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HANDLERS = {
    "restart_web": ["scripts/windows/start_pc_node.ps1"],
    "restart_backup": ["scripts/windows/start_backup.ps1"],
    "restart_all": ["scripts/windows/start_pc_node.ps1", "scripts/windows/start_backup.ps1"],
    "run_health_check": ["scripts/windows/check_pc_node.ps1"],
}


def process_pending(project_root: Path) -> list[dict[str, Any]]:
    command_dir = project_root / "runtime" / "commands"
    result_dir = project_root / "runtime" / "command_results"
    result_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for path in sorted(command_dir.glob("*.json")):
        try:
            command = json.loads(path.read_text(encoding="utf-8"))
            action = str(command.get("action", ""))
            if action == "apply_verified_update":
                result = _result(command, "blocked", "Verified update requires a selected signed artifact")
            elif action not in HANDLERS:
                result = _result(command, "rejected", "Command is not allow-listed")
            else:
                result = _execute(project_root, command, HANDLERS[action])
        except Exception as exc:
            result = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        target = result_dir / path.name
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        path.unlink(missing_ok=True)
        results.append(result)
    return results


def _execute(project_root: Path, command: dict[str, Any], scripts: list[str]) -> dict[str, Any]:
    outputs: list[dict[str, Any]] = []
    for relative in scripts:
        script = project_root / relative
        if not script.exists():
            return _result(command, "error", f"Missing script: {relative}")
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-ProjectRoot", str(project_root)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        outputs.append({
            "script": relative,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        })
        if completed.returncode != 0:
            return _result(command, "error", f"Script failed: {relative}", outputs)
    return _result(command, "completed", "Command completed", outputs)


def _result(command: dict[str, Any], status: str, detail: str, outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        **command,
        "status": status,
        "detail": detail,
        "outputs": outputs or [],
        "finished_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    results = process_pending(args.project_root.resolve())
    print(json.dumps({"processed": len(results), "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
