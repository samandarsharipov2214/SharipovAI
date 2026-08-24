from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORAGE_GUARD = ROOT / "scripts" / "deploy_storage_guard.sh"
RUNTIME_DEPLOY = ROOT / "scripts" / "deploy_market_paper_runtime.sh"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_storage_preflight_is_read_only_and_emits_fresh_disk_evidence():
    script = _text(STORAGE_GUARD)

    assert "docker builder prune" not in script
    assert "docker buildx prune" not in script
    assert "docker system prune" not in script
    assert "docker image prune" not in script
    assert "docker volume prune" not in script

    assert "date -u" in script
    assert "df -h" in script
    assert "docker system df" in script
    assert "STORAGE_GUARD_PRESSURE" in script
    assert "exit 70" in script


def test_candidate_build_has_fresh_disk_evidence_before_build():
    script = _text(RUNTIME_DEPLOY)

    build = script.index('docker compose build "$SERVICE"')
    before_build = script[:build]
    assert "date -u" in before_build
    assert "df -h" in before_build
    assert "docker system df" in before_build


def test_canonical_backup_runs_after_candidate_checks_and_before_production_mutation():
    script = _text(RUNTIME_DEPLOY)

    candidate_health = script.index("CANDIDATE_HEALTH_OK")
    backup = script.index("deploy/vps/export_backup.sh")
    production_stop = script.index('docker stop "$SERVICE"')

    assert candidate_health < backup < production_stop

    before_backup = script[:backup]
    assert "date -u" in before_backup
    assert "df -h" in before_backup
    assert "docker system df" in before_backup


def test_backup_is_not_allowed_to_fail_open():
    script = _text(RUNTIME_DEPLOY)

    backup_line = next(
        line.strip()
        for line in script.splitlines()
        if "deploy/vps/export_backup.sh" in line
    )
    assert "|| true" not in backup_line
    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
