from __future__ import annotations

from typing import Any

import pytest

from tools import paper_e2e_verifier as verifier


class _FakeDatabase:
    def __init__(self, values: dict[tuple[str, str], dict[str, Any]] | None = None) -> None:
        self.values = values or {}

    def get_json(self, namespace: str, key: str):
        value = self.values.get((namespace, key))
        return {"value": value} if value is not None else None


def _trades(decision_id: str = "paper-BTCUSDT-v2") -> list[dict[str, Any]]:
    return [
        {
            "trade_id": "buy-1",
            "decision_id": decision_id,
            "candidate_id": decision_id,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "created_at_ms": 120,
            "canonical_entry_authorized": True,
            "verified_market_data": True,
            "decision_quality_confidence": 0.81,
            "decision_quality_agreement": 0.78,
            "general_controller_decision": "ALLOW",
        },
        {
            "trade_id": "sell-1",
            "decision_id": decision_id,
            "candidate_id": decision_id,
            "symbol": "BTCUSDT",
            "side": "SELL",
            "created_at_ms": 200,
            "verified_market_data": True,
            "net_pnl": 7.5,
        },
    ]


def _v2_rows(
    decision_id: str = "paper-BTCUSDT-v2",
    *,
    owner: str = verifier.V2_DECISION_OWNER,
    authorized: bool = True,
    include_consumption: bool = True,
) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {
        (verifier.V2_DECISION_NAMESPACE, decision_id): {
            "decision_id": decision_id,
            "decided_at_ms": 100,
            "paper_decision_owner": owner,
            "authorized": authorized,
            "controller": {"final_intent": "BUY"},
        },
        ("paper_decision_settlements", decision_id): {
            "decision_id": decision_id,
            "selected_action": "BUY",
            "realized_outcome": "PROFIT",
            "learning_mode": verifier.V2_LEARNING_MODE,
            "legacy_direction_labeling_disabled": True,
            "verified_market_data": True,
            "net_pnl": 7.5,
        },
    }
    if include_consumption:
        rows[(verifier.AUTHORIZATION_NAMESPACE, decision_id)] = {
            "decision_id": decision_id,
            "paper_decision_owner": verifier.V2_DECISION_OWNER,
            "decision": "ALLOW",
            "consumed_at_ms": 110,
        }
    return rows


def _install_trades(monkeypatch: pytest.MonkeyPatch, trades: list[dict[str, Any]]) -> None:
    def fake_values(_database, namespace: str):
        if namespace.startswith("paper_trades:"):
            return list(trades)
        return []

    monkeypatch.setattr(verifier, "_values", fake_values)


def test_legacy_round_trip_is_not_v2_release_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    decision_id = "paper-XRPUSDT-legacy"
    _install_trades(monkeypatch, _trades(decision_id))
    database = _FakeDatabase(
        {
            ("paper_decision_settlements", decision_id): {
                "decision_id": decision_id,
                "reputation_recorded": True,
                "verified_market_data": True,
                "net_pnl": 3.0,
            },
            (verifier.AUTHORIZATION_NAMESPACE, decision_id): {
                "decision_id": decision_id,
                "decision": "ALLOW",
                "consumed_at_ms": 110,
            },
        }
    )

    assert verifier._completed_round_trip(database, "scope") is None


def test_complete_v2_round_trip_requires_owner_and_consumed_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision_id = "paper-BTCUSDT-v2"
    _install_trades(monkeypatch, _trades(decision_id))
    database = _FakeDatabase(_v2_rows(decision_id))

    result = verifier._completed_round_trip(database, "scope")

    assert result is not None
    assert result["paper_decision_owner"] == verifier.V2_DECISION_OWNER
    assert result["controller_final_intent"] == "BUY"
    assert result["v2_decided_at_ms"] == 100
    assert result["authorization_consumed_at_ms"] == 110
    assert result["chain"]["v2_decision_owned"] is True
    assert result["chain"]["v2_decision_authorized"] is True
    assert result["chain"]["v2_authorization_consumed"] is True
    assert result["chain"]["learning_settled"] is True
    assert all(result["chain"].values())


@pytest.mark.parametrize(
    ("owner", "authorized", "include_consumption"),
    [
        ("legacy_controller", True, True),
        (verifier.V2_DECISION_OWNER, False, True),
        (verifier.V2_DECISION_OWNER, True, False),
    ],
)
def test_v2_round_trip_fails_closed_when_linkage_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    owner: str,
    authorized: bool,
    include_consumption: bool,
) -> None:
    decision_id = "paper-BTCUSDT-v2"
    _install_trades(monkeypatch, _trades(decision_id))
    database = _FakeDatabase(
        _v2_rows(
            decision_id,
            owner=owner,
            authorized=authorized,
            include_consumption=include_consumption,
        )
    )

    assert verifier._completed_round_trip(database, "scope") is None


def test_since_ms_excludes_pre_deploy_v2_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    decision_id = "paper-BTCUSDT-v2"
    _install_trades(monkeypatch, _trades(decision_id))
    database = _FakeDatabase(_v2_rows(decision_id))

    assert verifier._completed_round_trip(database, "scope", since_ms=121) is None
    assert verifier._completed_round_trip(database, "scope", since_ms=100) is not None


def test_v2_learning_requires_side_preserving_pending_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    decision_id = "paper-BTCUSDT-v2"
    _install_trades(monkeypatch, _trades(decision_id))
    rows = _v2_rows(decision_id)
    rows[("paper_decision_settlements", decision_id)]["learning_mode"] = "legacy_reputation"
    database = _FakeDatabase(rows)

    assert verifier._completed_round_trip(database, "scope") is None


def test_negative_since_ms_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_trades(monkeypatch, [])
    with pytest.raises(ValueError, match="since_ms must be non-negative"):
        verifier._completed_round_trip(_FakeDatabase(), "scope", since_ms=-1)
