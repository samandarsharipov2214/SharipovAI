from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.pc_node_agent import backup_fresh, load_env


def test_load_env_reads_utf8_bom_and_ignores_comments(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"
    path.write_text("\ufeff# local config\nSHARIPOVAI_PORT=8000\nEMPTY=\n", encoding="utf-8")

    values = load_env(path)

    assert values["SHARIPOVAI_PORT"] == "8000"
    assert values["EMPTY"] == ""
    assert "# local config" not in values


def test_backup_fresh_accepts_recent_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"created_at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )

    assert backup_fresh(manifest, 45) is True


def test_backup_fresh_rejects_old_or_invalid_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    old = datetime.now(UTC) - timedelta(minutes=5)
    manifest.write_text(json.dumps({"created_at": old.isoformat()}), encoding="utf-8")
    assert backup_fresh(manifest, 45) is False

    manifest.write_text("not-json", encoding="utf-8")
    assert backup_fresh(manifest, 45) is False


def test_backup_fresh_rejects_missing_manifest(tmp_path: Path) -> None:
    assert backup_fresh(tmp_path / "missing.json", 45) is False
