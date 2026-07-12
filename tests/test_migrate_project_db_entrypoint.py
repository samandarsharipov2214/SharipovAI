from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_migration_script_runs_directly_from_repository_root(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "shared-data"
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("SHARIPOVAI_DATABASE_REQUIRED", None)
    env["SHARIPOVAI_DATA_DIR"] = str(data_dir)

    result = subprocess.run(
        [sys.executable, "scripts/migrate_project_db.py"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    status = json.loads(result.stdout.strip())
    assert status == {
        "backend": "sqlite",
        "required": False,
        "schema_version": 1,
        "status": "ok",
    }
    assert (data_dir / "sharipovai_shared.db").is_file()
