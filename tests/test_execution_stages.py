from __future__ import annotations

import json

import httpx
import pytest

from autonomous_trading.stage_controller import StageController
from exchange_connector.bybit_execution import BybitExecutionClient
from exchange_connector.execution_contract import build_execution_request
from trading_candidate import (
    MarketRegime,
    TradingCandidate,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
    validate_trading_candidate,
)

NOW_MS = 1_800_000_000_000


def _request(*, quantity: float, candidate_id: str = "candidate_phase6"):
    candidate = TradingCandidate(
        candidate_id=candidate_id,
        symbol="BTCUSDT",
        category=TradingCategory.SPOT,
        side=TradingSide.BUY,
        environment=TradingEnvironment.TESTNET,
        market_timestamp_ms=NOW_MS - 100,
        received_timestamp_ms=NOW_MS - 50,
        reference_price=50_000.0,
        data_sources=("bybit_ws", "bybit_rest", "market_cache"),
        market_regime=MarketRegime.TREND,
        signal_evidence=("phase6-signal",),
        news_evidence=(),
        news_assessment_id="news_phase6",
        portfolio_snapshot_id="portfolio_phase6",
        cost_snapshot_id="cost_phase6",
        estimated_fees=0.02,
        estimated_slippage=0.01,
        risk_score=10.0,
        risk_blocks=(),
        confidence=90.0,
        consensus=90.0,
        decision=TradingDecision.ALLOW,
        expires_at_ms=NOW_MS + 5_000,
    )
    validation = validate_trading_candidate(candidate, now_ms=NOW_MS)
    assert validation.valid is True
    return build_execution_request(candidate, validation, quantity=quantity, now_ms=NOW_MS)


def _sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'execution.db'}")
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api-testnet.bybit.com")
    monkeypatch.setenv("EXCHANGE_API_KEY", "key")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "secret")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")


def test_testnet_order_requires_explicit_unlock(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sandbox(monkeypatch, tmp_path)
    monkeypatch.delenv("TESTNET_EXECUTION_ENABLED", raising=False)
    client = BybitExecutionClient()
    with pytest.raises(RuntimeError, match="Testnet execution is locked"):
        client.execute(_request(quantity=0.0002), now_ms=NOW_MS)


def test_live_is_rejected_before_any_order_submission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "live")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api.bybit.com")
    monkeypatch.setenv("EXCHANGE_API_KEY", "key")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "secret")
    with pytest.raises((ValueError, RuntimeError), match="live|Mainnet|approved"):
        BybitExecutionClient()


def test_notional_cap_blocks_large_canonical_request(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sandbox(monkeypatch, tmp_path)
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("EXECUTION_MAX_NOTIONAL_USDT", "25")
    client = BybitExecutionClient()
    with pytest.raises(RuntimeError, match="exceeds safety cap"):
        client.execute(_request(quantity=0.01), now_ms=NOW_MS)


def test_stage_controller_requires_evidence(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"equity": 10020, "trades": [{"side": "SELL", "net_pnl": 1.0}]}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setenv("AUTONOMOUS_TRADING_STAGE", "2")
    assessment = StageController(str(path)).assess()
    assert assessment.eligible_stage == 2
    assert assessment.blockers


def test_signed_testnet_request_returns_order_and_identity(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sandbox(monkeypatch, tmp_path)
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "1")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"retCode": 0, "result": {"orderId": "abc"}})
    )
    canonical = _request(quantity=0.0002, candidate_id="candidate_phase6_accepted")
    with httpx.Client(transport=transport) as http_client:
        result = BybitExecutionClient(client=http_client).execute(canonical, now_ms=NOW_MS)
    assert result.order_id == "abc"
    assert result.mode == "sandbox"
    assert result.candidate_id == canonical.candidate_id
    assert result.order_link_id == canonical.order_link_id
