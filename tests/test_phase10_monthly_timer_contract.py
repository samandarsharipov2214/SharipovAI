from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_monthly_timer_is_persistent_and_bounded():
    timer = (ROOT / "deploy/vps/systemd/sharipovai-monthly-performance.timer").read_text(encoding="utf-8")
    service = (ROOT / "deploy/vps/systemd/sharipovai-monthly-performance.service").read_text(encoding="utf-8")
    installer = (ROOT / "deploy/vps/install_phase10_monthly_monitor.sh").read_text(encoding="utf-8")
    assert "OnCalendar=monthly" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=900" in timer
    assert "phase10_monthly_report.py" in service
    assert "NoNewPrivileges=true" in service
    assert "ProtectSystem=strict" in service
    assert "enable --now sharipovai-monthly-performance.timer" in installer
