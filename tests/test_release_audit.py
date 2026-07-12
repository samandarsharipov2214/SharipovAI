from __future__ import annotations

from pathlib import Path

from scripts.release_audit import (
    _audit_blueprint,
    _audit_runtime_environment,
    _audit_test_collection,
    _audit_vps_boundary,
    audit_repository,
)


def configure_safe_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUTH_SECRET", "ci-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password-long-enough")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'shared.db'}")
    monkeypatch.setenv("SHARIPOVAI_DATABASE_REQUIRED", "1")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "0")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "0")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("FEATURE_BYBIT_PRIVATE_ORDER_WS", "0")
    monkeypatch.setenv("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS", "0")
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("AUTONOMOUS_TRADING_STAGE", "2")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api-testnet.bybit.com")
    monkeypatch.setenv("EXECUTION_JOURNAL_FILE", str(tmp_path / "execution-journal.json"))
    for name in (
        "BYBIT_MAINNET_API_KEY",
        "BYBIT_MAINNET_API_SECRET",
        "BYBIT_READONLY_API_KEY",
        "BYBIT_READONLY_API_SECRET",
        "BYBIT_TESTNET_API_KEY",
        "BYBIT_TESTNET_API_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def test_current_repository_release_audit_passes(monkeypatch, tmp_path: Path) -> None:
    configure_safe_runtime(monkeypatch, tmp_path)
    report = audit_repository(Path("."), runtime=True)
    assert report.status == "ok", report.errors
    required_passes = {
        "canonical_ai_organs",
        "execution_journal_database",
        "pytest_all_regressions_covered",
        "single_public_market_worker",
        "market_adapter_no_second_socket",
        "vps_https_boundary",
        "vps_secure_cookie_preserved",
        "production_secure_session_cookie",
    }
    passed = {item.name for item in report.checks if item.status == "pass"}
    assert required_passes <= passed


def test_unsafe_render_testnet_value_is_detected(tmp_path: Path) -> None:
    source = Path("render.yaml").read_text(encoding="utf-8")
    unsafe = source.replace(
        '- key: TESTNET_EXECUTION_ENABLED\n        value: "0"',
        '- key: TESTNET_EXECUTION_ENABLED\n        value: "1"',
        1,
    )
    (tmp_path / "render.yaml").write_text(unsafe, encoding="utf-8")
    seen = {}

    def record(name, passed, detail, **kwargs):
        seen[name] = (passed, detail)

    _audit_blueprint(tmp_path, record)
    assert seen["render_testnet_locked"][0] is False


def test_enabled_render_bridge_is_detected(tmp_path: Path) -> None:
    source = Path("render.yaml").read_text(encoding="utf-8")
    unsafe = source.replace(
        '- key: AUTONOMOUS_TESTNET_BRIDGE_ENABLED\n        value: "0"',
        '- key: AUTONOMOUS_TESTNET_BRIDGE_ENABLED\n        value: "1"',
        1,
    )
    (tmp_path / "render.yaml").write_text(unsafe, encoding="utf-8")
    seen = {}

    def record(name, passed, detail, **kwargs):
        seen[name] = passed

    _audit_blueprint(tmp_path, record)
    assert seen["render_testnet_locked"] is False


def test_missing_runtime_auth_kill_switch_and_enabled_live_are_blocked(monkeypatch) -> None:
    for name in ("AUTH_SECRET", "ADMIN_USERNAME", "ADMIN_PASSWORD", "DATABASE_URL", "EXECUTION_KILL_SWITCH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "1")
    monkeypatch.setenv("EXCHANGE_MODE", "live")
    monkeypatch.setenv("AUTONOMOUS_TRADING_STAGE", "4")
    seen = {}

    def record(name, passed, detail, **kwargs):
        seen[name] = passed

    _audit_runtime_environment(record)
    assert seen["runtime_required_configuration"] is False
    assert seen["runtime_auth_enabled"] is False
    assert seen["runtime_kill_switch"] is False
    assert seen["runtime_live_locked"] is False
    assert seen["runtime_exchange_sandbox"] is False
    assert seen["runtime_stage_safe"] is False


def test_partial_credentials_and_mainnet_credentials_are_blocked(monkeypatch) -> None:
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "only-key")
    monkeypatch.delenv("BYBIT_TESTNET_API_SECRET", raising=False)
    monkeypatch.setenv("BYBIT_MAINNET_API_KEY", "live-key")
    monkeypatch.setenv("BYBIT_MAINNET_API_SECRET", "live-secret")
    monkeypatch.delenv("RELEASE_AUDIT_ALLOW_MAINNET_CREDENTIALS", raising=False)
    seen = {}

    def record(name, passed, detail, **kwargs):
        seen[name] = passed

    _audit_runtime_environment(record)
    assert seen["runtime_bybit_testnet_pair"] is False
    assert seen["runtime_mainnet_credentials_absent"] is False


def test_uncovered_regression_directory_is_blocked(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_visible.py").write_text("def test_visible(): pass\n", encoding="utf-8")
    hidden = tmp_path / "hidden/tests"
    hidden.mkdir(parents=True)
    (hidden / "test_hidden.py").write_text("def test_hidden(): pass\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        encoding="utf-8",
    )
    seen = {}

    def record(name, passed, detail, **kwargs):
        seen[name] = (passed, detail)

    _audit_test_collection(tmp_path, record)
    assert seen["pytest_root_regressions"][0] is True
    assert seen["pytest_all_regressions_covered"][0] is False
    assert "hidden/tests/test_hidden.py" in seen["pytest_all_regressions_covered"][1]


def test_vps_proxy_cannot_strip_secure_cookie(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy/vps"
    deploy.mkdir(parents=True)
    (deploy / "docker-compose.yml").write_text(
        'ports:\n  - "127.0.0.1:8000:8000"\n  - "80:80"\n  - "443:443"\n',
        encoding="utf-8",
    )
    (deploy / "Caddyfile").write_text(
        '{$DOMAIN} {\n'
        '  header { Strict-Transport-Security "max-age=31536000; includeSubDomains" }\n'
        '  reverse_proxy sharipovai:8000 {\n'
        '    header_down Set-Cookie "{http.reverse_proxy.header.Set-Cookie}; nosecure"\n'
        '  }\n'
        '}\n',
        encoding="utf-8",
    )
    (deploy / ".env.vps.example").write_text(
        "DOMAIN=example.com\nTELEGRAM_WEBAPP_URL=https://example.com\n",
        encoding="utf-8",
    )
    seen = {}

    def record(name, passed, detail, **kwargs):
        seen[name] = passed

    _audit_vps_boundary(tmp_path, record)
    assert seen["vps_backend_private"] is True
    assert seen["vps_https_boundary"] is True
    assert seen["vps_secure_cookie_preserved"] is False
