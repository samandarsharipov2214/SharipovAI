from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from exchange_connector.live_execution_guard import LiveExecutionGuard


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_guard_allows_fresh_stream_and_consensus(tmp_path, monkeypatch) -> None:
    stream = tmp_path / "stream.json"
    consensus = tmp_path / "consensus.json"
    now = time.time()
    _write(stream, {
        "verified": True,
        "quotes": {"BTCUSDT": {"price": 60000.0, "received_at_unix_ms": int(now * 1000)}},
    })
    _write(consensus, {
        "checked_at": datetime.now(UTC).isoformat(),
        "symbols": {"BTCUSDT": {"online_count": 5, "consensus": {"price": 60010.0, "deviation_percent": 0.05}}},
    })
    monkeypatch.setenv("MARKET_STREAM_STATE_FILE", str(stream))
    monkeypatch.setenv("MULTI_EXCHANGE_STATE_FILE", str(consensus))
    result = LiveExecutionGuard().assess(symbol="BTCUSDT", reference_price=60005.0)
    assert result.allowed is True
    assert result.online_exchanges == 5
    assert result.blockers == ()


def test_guard_blocks_stale_stream(tmp_path, monkeypatch) -> None:
    stream = tmp_path / "stream.json"
    consensus = tmp_path / "consensus.json"
    _write(stream, {
        "verified": True,
        "quotes": {"BTCUSDT": {"price": 60000.0, "received_at_unix_ms": int((time.time() - 10) * 1000)}},
    })
    _write(consensus, {
        "checked_at": datetime.now(UTC).isoformat(),
        "symbols": {"BTCUSDT": {"online_count": 5, "consensus": {"price": 60000.0, "deviation_percent": 0.05}}},
    })
    monkeypatch.setenv("MARKET_STREAM_STATE_FILE", str(stream))
    monkeypatch.setenv("MULTI_EXCHANGE_STATE_FILE", str(consensus))
    result = LiveExecutionGuard().assess(symbol="BTCUSDT", reference_price=60000.0)
    assert result.allowed is False
    assert any("stale" in blocker for blocker in result.blockers)


def test_guard_blocks_divergent_or_insufficient_exchanges(tmp_path, monkeypatch) -> None:
    stream = tmp_path / "stream.json"
    consensus = tmp_path / "consensus.json"
    now = time.time()
    _write(stream, {
        "verified": True,
        "quotes": {"BTCUSDT": {"price": 60000.0, "received_at_unix_ms": int(now * 1000)}},
    })
    _write(consensus, {
        "checked_at": datetime.now(UTC).isoformat(),
        "symbols": {"BTCUSDT": {"online_count": 2, "consensus": {"price": 61000.0, "deviation_percent": 1.5}}},
    })
    monkeypatch.setenv("MARKET_STREAM_STATE_FILE", str(stream))
    monkeypatch.setenv("MULTI_EXCHANGE_STATE_FILE", str(consensus))
    result = LiveExecutionGuard().assess(symbol="BTCUSDT", reference_price=60000.0)
    assert result.allowed is False
    assert any("minimum" in blocker for blocker in result.blockers)
    assert any("deviation" in blocker for blocker in result.blockers)


def test_guard_blocks_reference_slippage(tmp_path, monkeypatch) -> None:
    stream = tmp_path / "stream.json"
    consensus = tmp_path / "consensus.json"
    now = time.time()
    _write(stream, {
        "verified": True,
        "quotes": {"BTCUSDT": {"price": 60000.0, "received_at_unix_ms": int(now * 1000)}},
    })
    _write(consensus, {
        "checked_at": datetime.now(UTC).isoformat(),
        "symbols": {"BTCUSDT": {"online_count": 5, "consensus": {"price": 60000.0, "deviation_percent": 0.05}}},
    })
    monkeypatch.setenv("MARKET_STREAM_STATE_FILE", str(stream))
    monkeypatch.setenv("MULTI_EXCHANGE_STATE_FILE", str(consensus))
    result = LiveExecutionGuard().assess(symbol="BTCUSDT", reference_price=61000.0)
    assert result.allowed is False
    assert any("slippage" in blocker for blocker in result.blockers)
