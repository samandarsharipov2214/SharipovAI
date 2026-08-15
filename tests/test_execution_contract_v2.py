from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from autonomous_trading.execution_contract_v2 import (
    AdapterPreview,
    CanonicalExecutionIntent,
    ExecutionEnvironment,
    InstrumentConstraints,
    OrderType,
    PreTradeCostSnapshot,
    TimeInForce,
)
from autonomous_trading.general_controller_v2 import TradingIntent


def _constraints() -> InstrumentConstraints:
    return InstrumentConstraints(
        tick_size=Decimal("0.10"),
        qty_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("5"),
        evidence_id="instrument:BTCUSDT:1723680000",
    )


def _costs() -> PreTradeCostSnapshot:
    return PreTradeCostSnapshot(
        fee_rate=Decimal("0.001"),
        expected_slippage_rate=Decimal("0.0004"),
        worst_case_slippage_rate=Decimal("0.0012"),
        evidence_id="cost:btc:001",
    )


def _intent(**overrides: object) -> CanonicalExecutionIntent:
    values: dict[str, object] = {
        "candidate_id": "candidate-001",
        "symbol": "BTCUSDT",
        "category": "linear",
        "intent": TradingIntent.BUY,
        "environment": ExecutionEnvironment.PAPER,
        "quantity": Decimal("0.010"),
        "reference_price": Decimal("65000.00"),
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.IOC,
        "constraints": _constraints(),
        "costs": _costs(),
        "portfolio_snapshot_id": "portfolio:001",
        "risk_evidence_id": "risk:001",
        "security_evidence_id": "security:001",
        "decision_evidence_id": "decision:001",
        "expires_at_ms": 1_723_680_060_000,
    }
    values.update(overrides)
    return CanonicalExecutionIntent(**values)


def test_paper_and_future_exchange_targets_share_one_schema_without_write_authority() -> None:
    paper = _intent(environment=ExecutionEnvironment.PAPER)
    testnet = _intent(environment=ExecutionEnvironment.TESTNET)
    mainnet = _intent(environment=ExecutionEnvironment.MAINNET)

    for row in (paper, testnet, mainnet):
        assert row.paper_authoritative is True
        assert row.execution_authority is False
        assert row.to_dict()["execution_authority"] is False
        assert row.order_link_id.startswith("v2-")
        assert len(row.order_link_id) == 35

    assert paper.to_dict().keys() == testnet.to_dict().keys() == mainnet.to_dict().keys()


def test_idempotency_key_is_deterministic_and_environment_scoped() -> None:
    first = _intent()
    duplicate = _intent()
    testnet = _intent(environment=ExecutionEnvironment.TESTNET)

    assert first.idempotency_key == duplicate.idempotency_key
    assert first.order_link_id == duplicate.order_link_id
    assert first.idempotency_key != testnet.idempotency_key


def test_wait_cannot_become_execution_intent() -> None:
    with pytest.raises(ValueError, match="WAIT cannot produce"):
        _intent(intent=TradingIntent.WAIT)


def test_execution_authority_cannot_be_enabled_in_this_phase() -> None:
    with pytest.raises(ValueError, match="execution_authority must remain false"):
        _intent(execution_authority=True)

    with pytest.raises(ValueError, match="paper_authoritative must remain true"):
        _intent(paper_authoritative=False)


def test_quantity_price_and_minimum_constraints_fail_closed() -> None:
    with pytest.raises(ValueError, match="qty_step"):
        _intent(quantity=Decimal("0.0105"))

    minimum_constraints = replace(_constraints(), min_qty=Decimal("0.002"))
    with pytest.raises(ValueError, match="min_qty"):
        _intent(constraints=minimum_constraints, quantity=Decimal("0.001"))

    expensive_minimum = replace(_constraints(), min_notional=Decimal("1000"))
    with pytest.raises(ValueError, match="min_notional"):
        _intent(constraints=expensive_minimum, quantity=Decimal("0.010"), reference_price=Decimal("50000"))


def test_limit_orders_require_tick_aligned_price_and_market_orders_forbid_one() -> None:
    with pytest.raises(ValueError, match="require limit_price"):
        _intent(order_type=OrderType.LIMIT, limit_price=None)

    with pytest.raises(ValueError, match="tick_size"):
        _intent(order_type=OrderType.LIMIT, limit_price=Decimal("65000.05"))

    with pytest.raises(ValueError, match="market orders must not define"):
        _intent(order_type=OrderType.MARKET, limit_price=Decimal("65000.00"))

    row = _intent(order_type=OrderType.LIMIT, limit_price=Decimal("65000.10"))
    assert row.limit_price == Decimal("65000.10")


def test_every_governance_and_cost_snapshot_requires_evidence() -> None:
    for field in (
        "portfolio_snapshot_id",
        "risk_evidence_id",
        "security_evidence_id",
        "decision_evidence_id",
    ):
        with pytest.raises(ValueError, match=field):
            _intent(**{field: ""})

    with pytest.raises(ValueError, match="constraints evidence_id"):
        replace(_constraints(), evidence_id="")

    with pytest.raises(ValueError, match="cost evidence_id"):
        replace(_costs(), evidence_id="")


def test_worst_case_slippage_cannot_understate_expected_slippage() -> None:
    with pytest.raises(ValueError, match="worst_case_slippage_rate"):
        PreTradeCostSnapshot(
            fee_rate=Decimal("0.001"),
            expected_slippage_rate=Decimal("0.002"),
            worst_case_slippage_rate=Decimal("0.001"),
            evidence_id="cost:bad",
        )


def test_adapter_preview_is_structurally_write_blocked() -> None:
    intent = _intent()
    preview = AdapterPreview(
        adapter_id="paper-preview",
        environment=ExecutionEnvironment.PAPER,
        normalized_symbol=intent.symbol,
        normalized_quantity=intent.quantity,
        normalized_price=None,
        idempotency_key=intent.idempotency_key,
    )
    assert preview.write_permitted is False

    with pytest.raises(ValueError, match="cannot permit writes"):
        AdapterPreview(
            adapter_id="unsafe",
            environment=ExecutionEnvironment.MAINNET,
            normalized_symbol=intent.symbol,
            normalized_quantity=intent.quantity,
            normalized_price=None,
            idempotency_key=intent.idempotency_key,
            write_permitted=True,
        )
