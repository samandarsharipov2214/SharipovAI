from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_weekly_code_review_shell_scripts_are_valid() -> None:
    for relative in (
        "deploy/vps/weekly-code-review-run.sh",
        "deploy/vps/install_weekly_code_reviewer.sh",
    ):
        subprocess.run(["bash", "-n", str(ROOT / relative)], check=True)


def test_weekly_timer_runs_once_per_iso_week_window() -> None:
    timer = (ROOT / "deploy/vps/systemd/sharipovai-weekly-code-review.timer").read_text(
        encoding="utf-8"
    )
    assert "OnCalendar=Mon *-*-* 04:30:00 UTC" in timer
    assert "Persistent=true" in timer
    assert "Unit=sharipovai-weekly-code-review.service" in timer


def test_runner_uses_read_only_repo_and_never_applies_patch() -> None:
    runner = (ROOT / "deploy/vps/weekly-code-review-run.sh").read_text(encoding="utf-8")
    reviewer = (ROOT / "tools/weekly_code_reviewer.py").read_text(encoding="utf-8")

    assert "WEEKLY_CODE_REVIEW_REPO_DIR=/workspace" in runner
    assert "WEEKLY_CODE_REVIEW_FIXES_DIR=/var/lib/sharipovai/agent_fixes" in runner
    assert "python /workspace/tools/weekly_code_reviewer.py" in runner
    assert "git apply" not in runner
    assert "subprocess.run([\"git\", \"apply\"" not in reviewer
    assert '"auto_apply": False' in reviewer
    assert '"owner_approval_required": True' in reviewer
