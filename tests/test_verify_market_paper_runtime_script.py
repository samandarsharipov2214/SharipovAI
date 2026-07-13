from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_verifier_imports_project_modules_when_executed_by_absolute_path(tmp_path) -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "verify_market_paper_runtime.py"
    env = dict(os.environ)
    env["SHARIPOVAI_VERIFY_IMPORT_ONLY"] = "1"

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "MARKET_PAPER_VERIFIER_IMPORT_OK" in result.stdout
