"""Public Bybit Spot importer produces immutable bar-close research evidence."""
from __future__ import annotations

from pathlib import Path

import pytest

from historical_data import BybitSpotKlineImporter, HistoricalDataLoader


class _FakeBybit:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def __call__(self, _url: str, *, params: dict[str, str]) -> dict:
        self.calls.append(dict(params))
        return {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "category": "spot",
                "symbol": "BTCUSDT",
                # Bybit returns newest candle first and timestamps bar start.
                "list": [
                    ["180000", "102", "104", "101", "103", "12", "1236"],
                    ["120000", "101", "103", "100", "102", "11", "1122"],
                    ["60000", "100", "102", "99", "101", "10", "1010"],
                ],
            },
        }


def test_importer_converts_bar_open_to_bar_close_and_builds_oos_provenance(tmp_path: Path) -> None:
    fake = _FakeBybit()
    importer = BybitSpotKlineImporter(fetch_json=fake)

    result = importer.build_dataset(
        output_dir=tmp_path,
        dataset_id="btc-alpha",
        dataset_version="v1",
        symbols=("BTCUSDT",),
        interval="1",
        start_bar_open_ms=60_000,
        end_bar_open_ms=180_000,
        commit_sha="a" * 40,
        retrieved_at_ms=300_000,
    )

    assert result.manifest.timestamp_semantics == "bar_close"
    assert result.manifest.start_timestamp_ms == 120_000
    assert result.manifest.end_timestamp_ms == 240_000
    assert result.manifest.sha256.keys() == {result.parquet_path.name}
    assert result.validation.valid is True
    assert result.validation.final_oos_eligible is True
    assert fake.calls[0]["category"] == "spot"
    assert fake.calls[0]["limit"] == "1000"

    with HistoricalDataLoader(result.manifest_path) as loader:
        loader.require_final_oos_eligible()
        events = tuple(loader.iter_events())
        raw = loader.rows(columns=("timestamp_ms", "source_start_timestamp_ms"))
    assert [event.timestamp_ms for event in events] == [120_000, 180_000, 240_000]
    assert [row["source_start_timestamp_ms"] for row in raw] == [60_000, 120_000, 180_000]
    assert all(event.metadata["timestamp_semantics"] == "bar_close" for event in events)

    with pytest.raises(FileExistsError, match="immutable"):
        importer.build_dataset(
            output_dir=tmp_path,
            dataset_id="btc-alpha",
            dataset_version="v1",
            symbols=("BTCUSDT",),
            interval="1",
            start_bar_open_ms=60_000,
            end_bar_open_ms=180_000,
            commit_sha="a" * 40,
            retrieved_at_ms=300_000,
        )


def test_importer_excludes_unclosed_candle(tmp_path: Path) -> None:
    fake = _FakeBybit()
    importer = BybitSpotKlineImporter(fetch_json=fake)

    result = importer.build_dataset(
        output_dir=tmp_path,
        dataset_id="btc-closed-only",
        dataset_version="v1",
        symbols=("BTCUSDT",),
        interval="1",
        start_bar_open_ms=60_000,
        end_bar_open_ms=180_000,
        commit_sha="b" * 40,
        # The candle starting at 180000 closes at 240000 and must be excluded.
        retrieved_at_ms=239_999,
    )

    assert result.manifest.row_count == 2
    assert result.manifest.end_timestamp_ms == 180_000
    assert result.validation.final_oos_eligible is True


def test_importer_rejects_response_market_category_mismatch(tmp_path: Path) -> None:
    def wrong_category(_url: str, *, params: dict[str, str]) -> dict:
        assert params["category"] == "spot"
        return {
            "retCode": 0,
            "result": {
                "category": "linear",
                "symbol": "BTCUSDT",
                "list": [["60000", "100", "101", "99", "100", "1", "100"]],
            },
        }

    importer = BybitSpotKlineImporter(fetch_json=wrong_category)
    with pytest.raises(ValueError, match="category does not match"):
        importer.build_dataset(
            output_dir=tmp_path,
            dataset_id="wrong-market",
            dataset_version="v1",
            symbols=("BTCUSDT",),
            interval="1",
            start_bar_open_ms=60_000,
            end_bar_open_ms=60_000,
            commit_sha="c" * 40,
            retrieved_at_ms=180_000,
        )


def test_importer_rejects_response_symbol_mismatch(tmp_path: Path) -> None:
    def wrong_symbol(_url: str, *, params: dict[str, str]) -> dict:
        assert params["symbol"] == "BTCUSDT"
        return {
            "retCode": 0,
            "result": {
                "category": "spot",
                "symbol": "ETHUSDT",
                "list": [["60000", "100", "101", "99", "100", "1", "100"]],
            },
        }

    importer = BybitSpotKlineImporter(fetch_json=wrong_symbol)
    with pytest.raises(ValueError, match="symbol does not match"):
        importer.build_dataset(
            output_dir=tmp_path,
            dataset_id="wrong-symbol",
            dataset_version="v1",
            symbols=("BTCUSDT",),
            interval="1",
            start_bar_open_ms=60_000,
            end_bar_open_ms=60_000,
            commit_sha="d" * 40,
            retrieved_at_ms=180_000,
        )
