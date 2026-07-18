from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase9_post_deploy_verifier_is_fail_closed():
    script = (ROOT/'deploy/vps/phase9_post_deploy_verify.sh').read_text(encoding='utf-8')
    assert 'set -Eeuo pipefail' in script
    assert 'docker compose' in script
    assert 'PRAGMA quick_check' in script
    assert 'compileall' in script
    assert 'mainnet_enabled' in script
