from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tools" / "run_paper_e2e_verifier.sh"


def test_verifier_launcher_resolves_repo_modules_from_any_cwd(tmp_path: Path) -> None:
    """Match production launcher use from a host/container working directory."""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        ["bash", str(LAUNCHER), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Paper E2E" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr
