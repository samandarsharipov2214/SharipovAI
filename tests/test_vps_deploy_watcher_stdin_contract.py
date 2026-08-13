from pathlib import Path


def test_deploy_watcher_keeps_stdin_attached_for_python_heredocs() -> None:
    source = Path("deploy/vps/sharipovai-deploy-watcher").read_text(encoding="utf-8")

    assert 'docker exec -i "$SERVICE" python - <<\'PY\'' in source
    assert 'docker exec -i \\\n    -e DEPLOY_STATE="$state"' in source
    assert 'docker exec "$SERVICE" python - <<\'PY\'' not in source


def test_deploy_watcher_remains_main_only_and_owner_requested() -> None:
    source = Path("deploy/vps/sharipovai-deploy-watcher").read_text(encoding="utf-8")

    assert 'if [[ "$action" != "deploy_main" ]]' in source
    assert 'git fetch --no-tags "${FETCH_REMOTE}" main' in source
    assert 'git checkout -q main' in source
    assert 'SHARIPOVAI_DEPLOY_WATCHER_ACTIVE=1' in source


def test_installed_watcher_source_and_installer_keep_heredoc_stdin() -> None:
    for path in (Path("scripts/sharipovai_deploy_watcher.sh"),):
        source = path.read_text(encoding="utf-8")
        assert 'docker exec -i "$SERVICE" python - <<\'PY\'' in source, path
        assert 'docker exec -i \\\n    -e DEPLOY_STATE="$state"' in source, path
        assert 'docker exec "$SERVICE" python - <<\'PY\'' not in source, path
        assert 'docker exec \\\n    -e DEPLOY_STATE="$state"' not in source, path

    installer = Path("scripts/install_telegram_deploy_watcher.sh").read_text(encoding="utf-8")
    assert 'WATCHER_SOURCE="$ROOT/scripts/sharipovai_deploy_watcher.sh"' in installer
