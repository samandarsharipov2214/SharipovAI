"""Candidate v1 must not silently run on data for a different hypothesis."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from historical_data.validation import DatasetValidationReport
from trading_core.alpha_dataset_contract import require_regime_breakout_dataset


def _report(*, columns: tuple[str, ...] = ("timestamp_ms", "symbol", "close", "volume")) -> DatasetValidationReport:
    return DatasetValidationReport(
        status="ok",
        dataset_id="fixture",
        row_count=10,
        min_timestamp_ms=1,
        max_timestamp_ms=10,
        symbols=("BTCUSDT",),
        columns=columns,
        duplicate_rows=0,
        invalid_price_rows=0,
        missing_interval_count=0,
        final_oos_eligible=True,
        oos_blockers=(),
    )


class _Loader:
    def __init__(
        self,
        *,
        market_type: str = "spot",
        timestamp_semantics: str = "bar_close",
        funding_included: bool = False,
        columns: tuple[str, ...] = ("timestamp_ms", "symbol", "close", "volume"),
    ) -> None:
        self.manifest = SimpleNamespace(
            market_type=market_type,
            timestamp_semantics=timestamp_semantics,
            funding_included=funding_included,
        )
        self._report = _report(columns=columns)

    def require_final_oos_eligible(self) -> DatasetValidationReport:
        return self._report


def test_spot_bar_close_close_and_volume_dataset_passes_candidate_contract() -> None:
    loader = _Loader()

    report = require_regime_breakout_dataset(loader)  # type: ignore[arg-type]

    assert report.final_oos_eligible is True


@pytest.mark.parametrize(
    ("loader", "blocker"),
    (
        (_Loader(market_type="linear"), "market_type_must_be_spot"),
        (_Loader(timestamp_semantics="point_in_time"), "timestamp_semantics_must_be_bar_close"),
        (_Loader(columns=("timestamp_ms", "symbol", "volume")), "close_column_required"),
        (_Loader(columns=("timestamp_ms", "symbol", "close")), "volume_column_required"),
        (_Loader(funding_included=True), "funding_must_be_absent_for_spot_candidate"),
    ),
)
def test_candidate_contract_rejects_data_that_changes_the_hypothesis(
    loader: _Loader,
    blocker: str,
) -> None:
    with pytest.raises(ValueError, match=blocker):
        require_regime_breakout_dataset(loader)  # type: ignore[arg-type]
