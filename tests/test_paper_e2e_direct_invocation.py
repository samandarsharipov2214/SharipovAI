from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "tools" / "paper_e2e_verifier.py"


def test_verifier_direct_script_invocation_resolves_repo_modules(tmp_path: Path) -> None:
    """Match production: `python /app/tools/paper_e2e_verifier.py --help` from any cwd."""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, str(VERIFIER), "--help"],
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
