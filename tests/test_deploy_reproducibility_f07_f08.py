from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RETENTION = ROOT / "deploy" / "vps" / "rollback_image_retention.py"

spec = importlib.util.spec_from_file_location("rollback_image_retention", RETENTION)
assert spec is not None and spec.loader is not None
retention = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = retention
spec.loader.exec_module(retention)


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_requirements_are_exact_pins_for_deploy_path() -> None:
    lines = [
        line.strip()
        for line in _text("requirements.txt").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines, "requirements.txt must not be empty"
    for line in lines:
        assert "==" in line, f"deploy requirement must be exact pin: {line}"
        assert ">=" not in line and "~=" not in line and "<" not in line, line


def test_dockerfile_installs_locked_requirements_without_upgrading_pip() -> None:
    dockerfile = _text("Dockerfile")
    assert "COPY requirements.txt" in dockerfile
    assert "python -m pip install --no-cache-dir -r requirements.txt" in dockerfile
    # Disallow an unbound pip self-upgrade on the deploy image path.
    assert "python -m pip install --upgrade pip" not in dockerfile
    assert "pip install --upgrade pip" not in dockerfile


def test_backend_dockerfile_avoids_unbound_pip_upgrade() -> None:
    dockerfile = _text("deploy/docker/backend.Dockerfile")
    assert "pip install --upgrade pip" not in dockerfile
    assert "pip install --no-cache-dir -r requirements.txt" in dockerfile


def test_production_python_and_caddy_bases_are_digest_pinned() -> None:
    dockerfile = _text("Dockerfile")
    backend = _text("deploy/docker/backend.Dockerfile")
    compose = _text("deploy/vps/docker-compose.yml")
    assert "FROM python:3.12-slim@sha256:" in dockerfile
    assert "FROM python:3.12-slim@sha256:" in backend
    assert "image: caddy:2-alpine@sha256:" in compose
    # Floating tag alone must not remain on the production path.
    assert "FROM python:3.12-slim\n" not in dockerfile
    assert "FROM python:3.12-slim\n" not in backend
    assert "image: caddy:2-alpine\n" not in compose
    docs = _text("docs/deploy-reproducibility.md")
    assert "Safe base-image / digest update mechanism" in docs
    assert "intentional" in docs.lower()


def test_update_and_phase11_rollback_refuse_rebuild_without_retained_image() -> None:
    update = _text("deploy/vps/update_from_main.sh")
    phase11 = _text("deploy/vps/phase11_rollback.sh")
    for script in (update, phase11):
        assert "retain_running_image_for_rollback" in script
        assert "assert_retained_rollback_image" in script
        assert "redeploy_retained_release" in script
        assert "org.opencontainers.image.revision" in script
        assert "--no-build" in script
        assert "refusing unreproducible rebuild" in script
        assert "running container image ID" in script
    assert "docker compose build" not in phase11


def test_differently_named_current_image_can_be_retained_deterministically() -> None:
    sha = "a" * 40
    image_id = "sha256:" + ("b" * 64)
    deploy_tag = f"sharipovai:deploy-{sha[:12]}-1750000000-12345"
    plan = retention.plan_retain_running_image(
        expected_sha=sha,
        running_image_id=image_id,
        oci_revision=sha,
        current_tags=[deploy_tag],
    )
    assert plan.rollback_ref == f"sharipovai:{sha[:12]}"
    assert plan.running_image_id == image_id
    assert plan.uses_non_deterministic_tag is True
    assert deploy_tag != plan.rollback_ref


def test_wrong_oci_revision_is_rejected() -> None:
    sha = "c" * 40
    image_id = "sha256:" + ("d" * 64)
    with pytest.raises(retention.RollbackRetentionError, match="OCI revision mismatch"):
        retention.plan_retain_running_image(
            expected_sha=sha,
            running_image_id=image_id,
            oci_revision="e" * 40,
            current_tags=[f"sharipovai:deploy-{sha[:12]}-1-1"],
        )
    with pytest.raises(retention.RollbackRetentionError, match="OCI revision mismatch"):
        retention.reject_tag_only_trust(
            expected_sha=sha,
            tagged_ref=f"sharipovai:{sha[:12]}",
            oci_revision="f" * 40,
        )


def test_missing_retained_artifact_fails_closed() -> None:
    sha = "1" * 40
    with pytest.raises(retention.RollbackRetentionError, match="missing"):
        retention.assert_retained_artifact(
            expected_sha=sha,
            artifact_present=False,
            artifact_revision=None,
        )


def test_rollback_scripts_never_invoke_docker_build_on_rollback_path() -> None:
    update = _text("deploy/vps/update_from_main.sh")
    phase11 = _text("deploy/vps/phase11_rollback.sh")
    assert "docker compose build" not in phase11

    rollback_start = update.index("rollback() {")
    rollback_end = update.index(
        'if [[ "${FETCH_REMOTE}" == https://github.com/* ]]; then',
        rollback_start,
    )
    rollback = update[rollback_start:rollback_end]
    assert "docker compose build" not in rollback
    assert "redeploy_retained_release" in rollback or "redeploy_pinned_release" in rollback
    assert "--no-build" in rollback

    # Forward deploy may build only after retention proves the previous image.
    assert update.index("retain_running_image_for_rollback") < update.index(
        "docker compose build --pull"
    )
    assert update.index("assert_retained_rollback_image") < update.index(
        "docker compose build --pull"
    )


def test_bash_contracts_require_revision_verification_not_tag_alone() -> None:
    for rel in ("deploy/vps/update_from_main.sh", "deploy/vps/phase11_rollback.sh"):
        script = _text(rel)
        assert "image_oci_revision" in script
        assert 'index .Config.Labels "org.opencontainers.image.revision"' in script or \
               "org.opencontainers.image.revision" in script
        # Tag move from running image ID, not blind trust of existing sha12 tag.
        assert "docker tag" in script
        assert "running_container_image_id" in script
