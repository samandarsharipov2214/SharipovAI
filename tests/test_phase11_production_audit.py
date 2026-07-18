from audit.phase11_production_audit import ProductionAudit


def test_audit_is_fail_closed_and_mainnet_false(tmp_path, monkeypatch):
    for path in ("CONSTITUTION.md", "README.md"):
        (tmp_path / path).write_text("ok", encoding="utf-8")
    (tmp_path / "dashboard/static/web2").mkdir(parents=True)
    (tmp_path / "dashboard/static/web2/index.html").write_text("viewport data-phase11-production phase11_production_v43.js theme-color", encoding="utf-8")
    (tmp_path / "deploy/vps").mkdir(parents=True)
    (tmp_path / "deploy/vps/phase11_release_preflight.sh").write_text("", encoding="utf-8")
    (tmp_path / "deploy/vps/phase11_post_deploy_verify.sh").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("FEATURE_BYBIT_LIVE_EXECUTION", "0")
    report = ProductionAudit(tmp_path).run()
    assert report["status"] == "ready_for_bounded_testnet_preflight"
    assert report["mainnet_enabled"] is False
    assert len(report["audit_sha256"]) == 64


def test_audit_blocks_live_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "1")
    report = ProductionAudit(tmp_path).run()
    assert report["status"] == "blocked"
    assert "mainnet_compiled_and_configured_off" in report["blockers"]
