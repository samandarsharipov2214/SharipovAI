from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autonomous_trading.council_provider import AutonomousCouncilProposalProvider as BaseCouncilProvider
from autonomous_trading.decision_trace import persist_decision_trace, read_decision_trace, read_decision_traces
from autonomous_trading.traced_council_provider import AutonomousCouncilProposalProvider as TracedCouncilProvider
from storage import ProjectDatabase


@dataclass
class Quote:
    price: float = 100.0
    change_24h_percent: float = 1.2
    volume_24h: float = 10_000_000.0
    received_at_unix_ms: int = 1


class FakeStream:
    symbols = ("BTCUSDT",)

    def __init__(self, evidence: dict):
        self._evidence = evidence

    def evidence(self, symbol: str) -> dict:
        assert symbol == "BTCUSDT"
        return dict(self._evidence)


def database(tmp_path: Path, name: str) -> ProjectDatabase:
    db = ProjectDatabase(f"sqlite:///{tmp_path / name}")
    db.initialize()
    return db


def test_trace_store_is_bounded_to_latest_row_per_symbol(tmp_path: Path) -> None:
    db = database(tmp_path, "trace.db")
    first = persist_decision_trace(db, "BTCUSDT", {"status": "WAIT", "reason": "first"}, now_ms=1000)
    second = persist_decision_trace(db, "BTCUSDT", {"status": "BLOCK", "reason": "second"}, now_ms=2000)

    assert first["status"] == "WAIT"
    assert second["status"] == "BLOCK"
    assert read_decision_trace(db, "BTCUSDT")["reason"] == "second"
    rows = read_decision_traces(db, ["BTCUSDT", "BTCUSDT"])
    assert len(rows) == 1
    assert rows[0]["trace_contract"] == "canonical_decision_trace_v1"


def test_traced_provider_preserves_fail_closed_market_gate_and_records_reason(tmp_path: Path) -> None:
    evidence = {
        "verified": False,
        "synthetic_fallback_used": False,
        "consensus_sources": ["a", "b", "c"],
    }
    base_db = database(tmp_path, "base.db")
    traced_db = database(tmp_path, "traced.db")
    base = BaseCouncilProvider(base_db, FakeStream(evidence), news_reader=lambda *_args, **_kwargs: {})
    traced = TracedCouncilProvider(traced_db, FakeStream(evidence), news_reader=lambda *_args, **_kwargs: {})
    quote = Quote()
    state = {"cash": 1000.0, "equity": 1000.0, "peak_equity": 1000.0, "open_symbols": ()}

    assert base("BTCUSDT", quote, state) is None
    assert traced("BTCUSDT", quote, state) is None
    trace = read_decision_trace(traced_db, "BTCUSDT")
    assert trace is not None
    assert trace["status"] == "BLOCK"
    assert trace["phase"] == "market_verification"
    assert trace["market_verified"] is False
    assert "verified non-synthetic market evidence" in trace["reason"]


def test_traced_provider_explains_insufficient_cross_exchange_consensus(tmp_path: Path) -> None:
    evidence = {
        "verified": True,
        "synthetic_fallback_used": False,
        "consensus_sources": ["bybit", "binance"],
    }
    db = database(tmp_path, "consensus.db")
    provider = TracedCouncilProvider(db, FakeStream(evidence), news_reader=lambda *_args, **_kwargs: {})
    quote = Quote()
    state = {"cash": 1000.0, "equity": 1000.0, "peak_equity": 1000.0, "open_symbols": ()}

    assert provider("BTCUSDT", quote, state) is None
    trace = read_decision_trace(db, "BTCUSDT")
    assert trace is not None
    assert trace["status"] == "WAIT"
    assert trace["consensus_source_count"] == 2
    assert trace["required_consensus_source_count"] == 3
    assert "requires 3 sources" in trace["reason"]


def test_operator_ui_loads_canonical_runtime_trace_panel() -> None:
    root = Path(__file__).resolve().parents[1]
    index = (root / "dashboard/static/web2/index.html").read_text(encoding="utf-8")
    script = (root / "dashboard/static/web2/runtime_trace_v46.js").read_text(encoding="utf-8")
    loop = (root / "autonomous_trading/council_loop.py").read_text(encoding="utf-8")

    assert "runtime_trace_v46.js?v=46" in index
    assert "decision_traces" in loop
    assert "latest_decision_trace" in loop
    assert "overview', 'bots', 'trades" in script
    assert "Почему ИИ сейчас BUY / SELL / WAIT / BLOCK" in script
    assert "no fresh canonical council proposal" not in script
