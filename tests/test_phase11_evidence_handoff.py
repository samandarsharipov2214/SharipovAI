from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_post_deploy_evidence_is_atomically_handed_to_container_volume():
    script = (ROOT / "deploy/vps/phase11_post_deploy_verify.sh").read_text(
        encoding="utf-8"
    )
    required = (
        "PHASE11_CONTAINER_NAME",
        "docker inspect",
        "REMOTE_DIR=\"/var/lib/sharipovai/audit\"",
        "docker cp",
        "chown 10001:10001",
        "chmod 0640",
        "mv -f \"$REMOTE_TMP\" \"$REMOTE_OUT\"",
        "docker exec \"$CONTAINER_NAME\" test -r \"$REMOTE_OUT\"",
    )
    assert all(token in script for token in required)
    assert script.index("raise SystemExit(0 if status") < script.index("docker cp")


def test_launch_runbook_reads_the_container_volume_copy():
    runbook = (ROOT / "docs/phase11-production-launch.md").read_text(
        encoding="utf-8"
    )
    checklist = (ROOT / "scripts/phase11_first_campaign_checklist.py").read_text(
        encoding="utf-8"
    )
    path = "/var/lib/sharipovai/audit/phase11-post-deploy.json"
    assert path in runbook
    assert path in checklist
    assert "docker exec" in runbook
