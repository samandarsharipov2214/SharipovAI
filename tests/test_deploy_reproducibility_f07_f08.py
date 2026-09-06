from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


def test_update_and_phase11_rollback_refuse_rebuild_without_pinned_image() -> None:
    update = _text("deploy/vps/update_from_main.sh")
    phase11 = _text("deploy/vps/phase11_rollback.sh")
    for script in (update, phase11):
        assert "pinned_image_ref" in script
        assert "assert_pinned_image_present" in script
        assert "redeploy_pinned_release" in script
        assert "--no-build" in script
        assert "refusing unreproducible rebuild" in script
    assert "docker compose build" not in phase11
