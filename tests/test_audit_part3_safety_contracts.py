"""Regression contracts for confirmed findings from the Part 3 external audit."""
from __future__ import annotations

from pathlib import Path

from exchange_connector.bybit_execution import (
    _ABSOLUTE_TESTNET_NOTIONAL_CEILING_USDT,
    _bounded_positive_env,
)


ROOT = Path(__file__).resolve().parents[1]


def test_execution_env_cannot_raise_absolute_testnet_ceiling(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTION_MAX_NOTIONAL_USDT", "1000")

    configured = _bounded_positive_env(
        "EXECUTION_MAX_NOTIONAL_USDT",
        default=25.0,
        maximum=_ABSOLUTE_TESTNET_NOTIONAL_CEILING_USDT,
    )

    assert _ABSOLUTE_TESTNET_NOTIONAL_CEILING_USDT == 50.0
    assert configured == 50.0


def test_execution_client_uses_absolute_testnet_ceiling() -> None:
    source = (ROOT / "exchange_connector" / "bybit_execution.py").read_text(encoding="utf-8")

    assert "maximum=_ABSOLUTE_TESTNET_NOTIONAL_CEILING_USDT" in source
    assert "maximum=1000.0" not in source


def test_virtual_account_renderer_never_parses_trade_html() -> None:
    source = (ROOT / "dashboard" / "static" / "virtual-account-live.js").read_text(encoding="utf-8")

    assert ".innerHTML" not in source
    assert ".outerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "textContent" in source
    assert "replaceChildren" in source
