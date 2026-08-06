from __future__ import annotations

from pathlib import Path

from risk_engine import CanonicalRiskService


def test_p0_canonical_risk_never_allows_live_execution():
    result = CanonicalRiskService().evaluate(
        {"market_data_verified": True, "exchange_ok": True, "turnover_usdt": 10_000_000},
        profile="council",
    )
    assert result.allowed_live is False
    assert result.to_dict()["profile"] == "council"


def test_p0_runtime_truth_and_backup_contracts_remain_present():
    root = Path(__file__).resolve().parents[1]
    loop = (root / "autonomous_trading" / "loop.py").read_text(encoding="utf-8")
    health = (root / "dashboard" / "system_health_api.py").read_text(encoding="utf-8")
    timer = (root / "deploy" / "vps" / "install_backup_timer.sh").read_text(encoding="utf-8")

    assert 'state["source_of_truth"] = "autonomous_paper"' in loop
    assert "suppressed_wait_events" in loop
    assert "timer_scope=host_systemd" in health
    assert "OnUnitActiveSec" in timer or "OnCalendar" in timer
