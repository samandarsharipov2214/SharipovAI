from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_market_paper_runtime.sh"


def test_deploy_build_uses_ephemeral_private_docker_config_and_fails_before_replacement(
    tmp_path: Path,
) -> None:
    """A read-only /root must not prevent the candidate build from starting.

    The mock rejects the build after recording its environment. This exercises the
    error trap and proves that a build failure happens before production replacement.
    The explicit deploy-root override keeps this hermetic test away from the root-owned
    production checkout while production still defaults to /opt/sharipovai-repo.
    Host free-space must not decide whether this Docker-config contract is exercised,
    so ``df`` is mocked with a deterministic healthy disk observation.
    """

    trace = tmp_path / "docker-build-trace.txt"
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()

    df_mock = mock_bin / "df"
    df_mock.write_text(
        """#!/usr/bin/env bash
cat <<'EOF'
Filesystem 1024-blocks Used Available Capacity Mounted on
/dev/mock 104857600 0 104857600 0% /
EOF
""",
        encoding="utf-8",
    )
    df_mock.chmod(0o755)

    docker_mock = mock_bin / "docker"
    docker_mock.write_text(
        """#!/usr/bin/env bash
if [[ "${1:-}" == "container" && "${2:-}" == "inspect" ]]; then
  exit 1
fi
if [[ "${1:-}" == "compose" && "${2:-}" == "build" ]]; then
  test "${HOME}" = "/root"
  test -n "${DOCKER_CONFIG:-}"
  test -d "${DOCKER_CONFIG}"
  printf '%s\\n' "${DOCKER_CONFIG}" > "${TRACE}"
  stat -c '%a' "${DOCKER_CONFIG}" >> "${TRACE}"
  exit 73
fi
echo "unexpected docker invocation: $*" >&2
exit 74
""",
        encoding="utf-8",
    )
    docker_mock.chmod(0o755)

    environment = os.environ | {
        "HOME": "/root",
        "TRACE": str(trace),
        "PATH": f"{mock_bin}:{os.environ['PATH']}",
        "SHARIPOVAI_DEPLOY_ROOT": str(ROOT),
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert result.returncode == 73
    assert "Candidate verification failed before production replacement" in result.stdout
    assert "DEPLOY_DISK_PREFLIGHT_OK" in result.stdout
    directory, mode = trace.read_text(encoding="utf-8").splitlines()
    assert directory.startswith("/tmp/sharipovai-docker-config-")
    assert mode == "700"
    assert not Path(directory).exists(), "temporary Docker config must be removed on EXIT"


def test_deploy_script_never_uses_root_docker_config() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'mktemp -d /tmp/sharipovai-docker-config-XXXXXX' in source
    assert 'chmod 0700 "$docker_config_tmp"' in source
    assert 'export DOCKER_CONFIG="$docker_config_tmp"' in source
    assert source.index('export DOCKER_CONFIG="$docker_config_tmp"') < source.index(
        'docker compose build "$SERVICE"'
    )
    assert source.index('docker compose build "$SERVICE"') < source.index(
        "production_replaced=1"
    )
    assert 'rm -rf "$docker_config_tmp"' in source
    assert "/root/.docker" not in source


def test_deploy_root_defaults_to_canonical_checkout_and_override_is_explicit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'ROOT="${SHARIPOVAI_DEPLOY_ROOT:-/opt/sharipovai-repo}"' in source
    assert '[[ "$ROOT" == /* ]]' in source
    assert 'git -c safe.directory="$ROOT" -C "$ROOT" rev-parse --is-inside-work-tree' in source
    assert 'git -c safe.directory="$ROOT" -C "$ROOT" "$@"' in source
    assert "git config --global" not in source
