from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "deploy" / "vps" / "self-healing-run.sh"
WATCHER = ROOT / "deploy" / "vps" / "sharipovai-deploy-watcher"


def test_self_healing_claims_the_canonical_deploy_lock_before_runtime_checks() -> None:
    wrapper = WRAPPER.read_text(encoding="utf-8")
    watcher = WATCHER.read_text(encoding="utf-8")

    assert 'DEPLOY_LOCK_FILE="${SELF_HEALING_DEPLOY_LOCK_FILE:-/run/sharipovai-telegram-deploy.lock}"' in wrapper
    assert 'LOCK_FILE="/run/sharipovai-telegram-deploy.lock"' in watcher
    main = wrapper[wrapper.index("main() {") :]
    assert main.index("claim_deploy_coordination") < main.index("ensure_stack ||")
    assert 'SELF_HEALING_RUN_LIBRARY:-0' in wrapper


def test_active_deploy_lock_makes_self_healing_skip_fail_closed(tmp_path: Path) -> None:
    lock = tmp_path / "deploy.lock"
    holder = subprocess.Popen(
        [
            "bash",
            "-c",
            'exec 9>"$1"; flock 9; printf "ready\\n"; read -r _',
            "holder",
            str(lock),
        ],
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "ready"
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; claim_deploy_coordination',
                "probe",
                str(WRAPPER),
            ],
            env=os.environ
            | {
                "SELF_HEALING_RUN_LIBRARY": "1",
                "SELF_HEALING_DEPLOY_LOCK_FILE": str(lock),
            },
            check=False,
        )
        assert result.returncode != 0
    finally:
        if holder.stdin is not None:
            holder.stdin.write("done\n")
            holder.stdin.flush()
        holder.wait(timeout=5)


def test_claim_is_held_for_the_self_healing_process_lifetime(tmp_path: Path) -> None:
    lock = tmp_path / "deploy.lock"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; claim_deploy_coordination; ! flock -n "$2" -c true',
            "probe",
            str(WRAPPER),
            str(lock),
        ],
        env=os.environ
        | {
            "SELF_HEALING_RUN_LIBRARY": "1",
            "SELF_HEALING_DEPLOY_LOCK_FILE": str(lock),
        },
        check=False,
    )
    assert result.returncode == 0
