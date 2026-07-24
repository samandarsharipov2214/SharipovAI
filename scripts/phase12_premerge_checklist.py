#!/usr/bin/env python3
"""Read-only Phase 12 pre-merge evidence checklist."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

_REQUIRED = (
    "learning_engine/evidence_policy.py",
    "learning_engine/outcome_attribution.py",
    "learning_engine/research_challengers.py",
    "learning_engine/self_learning_supervisor.py",
    "validation/paper_fill_validation.py",
    "validation/phase12_validation.py",
    "deploy/vps/phase12_release_preflight.sh",
    "deploy/vps/phase12_post_deploy_verify.sh",
    "deploy/vps/phase12_rollback.sh",
    "README.md",
    "CONSTITUTION.md",
    "CONSTITUTION_PHASE12_AMENDMENT.md",
)


def run_checklist(root: Path, *, expected_sha: str = "", allow_no_git: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    if (root / ".git").exists():
        actual_sha = _command(root, "git", "rev-parse", "HEAD").strip()
        checks["full_commit_sha"] = len(actual_sha) == 40
        checks["clean_worktree"] = not _command(root, "git", "status", "--porcelain").strip()
        checks["expected_sha_matches"] = not expected_sha or actual_sha == expected_sha
    else:
        actual_sha = ""
        checks["full_commit_sha"] = allow_no_git
        checks["clean_worktree"] = allow_no_git
        checks["expected_sha_matches"] = allow_no_git and not expected_sha
    details["actual_sha"] = actual_sha
    missing = [name for name in _REQUIRED if not (root / name).is_file()]
    checks["required_files_present"] = not missing
    details["missing_files"] = missing
    docs = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in ("README.md", "CONSTITUTION.md", "CONSTITUTION_PHASE12_AMENDMENT.md")
        if (root / name).is_file()
    ).lower()
    tokens = (
        "phase 12",
        "outcome attribution",
        "paper research champion",
        "automatic execution promotion is forbidden",
        "fill divergence",
        "final report",
        "operator cli",
        "exact sha",
        "rollback",
    )
    missing_tokens = [token for token in tokens if token not in docs]
    checks["documentation_contract"] = not missing_tokens
    details["missing_documentation_tokens"] = missing_tokens
    shell_results: dict[str, bool] = {}
    for name in ("phase12_release_preflight.sh", "phase12_post_deploy_verify.sh", "phase12_rollback.sh"):
        path = root / "deploy" / "vps" / name
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True) if path.exists() else None
        shell_results[name] = bool(result and result.returncode == 0)
    checks["deployment_script_syntax"] = all(shell_results.values())
    details["deployment_script_syntax"] = shell_results
    blockers = sorted(name for name, passed in checks.items() if not passed)
    report = {
        "schema_version": 1,
        "status": "ready_for_merge" if not blockers else "blocked",
        "checks": checks,
        "blockers": blockers,
        "details": details,
        "mainnet_enabled": False,
        "automatic_execution_promotion": False,
        "runtime_flags_changed": False,
    }
    payload = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    report["evidence_sha256"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return report


def _command(root: Path, *command: str) -> str:
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "command failed")
    return result.stdout


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--expected-sha", default="")
    parser.add_argument("--allow-no-git", action="store_true")
    args = parser.parse_args()
    output = run_checklist(Path(args.root), expected_sha=args.expected_sha, allow_no_git=args.allow_no_git)
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if output["status"] == "ready_for_merge" else 2)
