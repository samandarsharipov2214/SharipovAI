from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "deploy" / "vps" / "resolve_public_base_url.py"
VERIFIER = ROOT / "deploy" / "vps" / "verify_production.sh"

spec = importlib.util.spec_from_file_location("resolve_public_base_url", RESOLVER)
assert spec is not None and spec.loader is not None
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)


def test_caddyfile_is_canonical_public_target_when_no_override(tmp_path: Path) -> None:
    caddy = tmp_path / "Caddyfile"
    caddy.write_text(
        "85-137-88-17.sslip.io {\n    reverse_proxy sharipovai:8000\n}\n",
        encoding="utf-8",
    )

    assert resolver.resolve_public_base_url("", caddy) == "https://85-137-88-17.sslip.io"


def test_explicit_https_override_is_allowed(tmp_path: Path) -> None:
    caddy = tmp_path / "Caddyfile"
    caddy.write_text("ignored.example.net {\n}\n", encoding="utf-8")

    assert (
        resolver.resolve_public_base_url("https://status.example.net", caddy)
        == "https://status.example.net"
    )


@pytest.mark.parametrize(
    "target",
    [
        "localhost",
        "https://localhost",
        "127.0.0.1",
        "https://127.0.0.1",
        "http://85-137-88-17.sslip.io",
        "sharipovai.example.com",
    ],
)
def test_non_public_or_non_https_targets_are_rejected(target: str) -> None:
    with pytest.raises(ValueError):
        resolver.normalize_https_target(target)


def test_verifier_uses_caddy_or_safe_override_not_env_domain() -> None:
    source = VERIFIER.read_text(encoding="utf-8")

    assert 'CADDYFILE="${CADDYFILE:-${COMPOSE_DIR}/Caddyfile}"' in source
    assert 'PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}"' in source
    assert 'python3 "${PUBLIC_URL_RESOLVER}" "${PUBLIC_BASE_URL}" "${CADDYFILE}"' in source
    assert 'line.startswith("DOMAIN=")' not in source
    assert 'https://${public_domain}/health' not in source
    assert 'record FAIL public_https_target' in source
    assert 'record WARN "${name}" "endpoint is reachable but requires an authenticated session' in source
