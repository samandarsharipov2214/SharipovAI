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


def test_backup_is_bound_to_proven_live_compose_project_and_volume():
    script = _text(RUNTIME_DEPLOY)

    inspect_volume = "docker inspect -f '{{range .Mounts}}{{if eq .Destination \"/var/lib/sharipovai\"}}{{.Name}}{{end}}{{end}}' \"$SERVICE\""
    inspect_project = "docker inspect -f '{{index .Config.Labels \"com.docker.compose.project\"}}' \"$SERVICE\""
    backup = script.index("deploy/vps/export_backup.sh")

    assert inspect_volume in script
    assert inspect_project in script
    assert '[[ "$data_volume" =~ ^[A-Za-z0-9_.-]+$ ]]' in script
    assert '[[ "$production_compose_project" =~ ^[A-Za-z0-9_.-]+$ ]]' in script
    assert 'name: ${data_volume}' in script
    assert 'COMPOSE_PROJECT_NAME="$production_compose_project"' in script[:backup]
    assert 'COMPOSE_FILE="$DEPLOY/docker-compose.yml:$runtime_override"' in script[:backup]
    assert script.index('name: ${data_volume}') < backup


def test_backup_is_not_allowed_to_fail_open():
    script = _text(RUNTIME_DEPLOY)

    backup_line = next(
        line.strip()
        for line in script.splitlines()
        if "deploy/vps/export_backup.sh" in line
    )
    assert "|| true" not in backup_line
    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
