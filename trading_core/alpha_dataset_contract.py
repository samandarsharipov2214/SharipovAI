"""Dataset contract for the first SharipovAI non-benchmark candidate."""
from __future__ import annotations

from historical_data import HistoricalDataLoader
from historical_data.validation import DatasetValidationReport


def require_regime_breakout_dataset(
    loader: HistoricalDataLoader,
) -> DatasetValidationReport:
    """Fail closed unless data matches Candidate v1's economic hypothesis.

    Generic final-OOS eligibility is intentionally broader. Candidate v1 is the
    first Bybit Spot close-bar/volume experiment, so a different venue/source,
    native quote execution data, derivatives, missing volume, non-bar-close
    timestamps or funding-bearing data must not silently become evidence for a
    different hypothesis.
    """

    report = loader.require_final_oos_eligible()
    manifest = loader.manifest
    blockers: list[str] = []
    if manifest.venue != "bybit":
        blockers.append("venue_must_be_bybit")
    if manifest.source != "bybit_v5_market_kline":
        blockers.append("source_must_be_canonical_bybit_kline_importer")
    if manifest.market_type != "spot":
        blockers.append("market_type_must_be_spot")
    if manifest.timestamp_semantics != "bar_close":
        blockers.append("timestamp_semantics_must_be_bar_close")
    columns = set(report.columns)
    if "close" not in columns:
        blockers.append("close_column_required")
    if "volume" not in columns:
        blockers.append("volume_column_required")
    if {"bid", "ask"}.issubset(columns):
        blockers.append("native_bid_ask_not_allowed_for_close_bar_candidate")
    if manifest.funding_included:
        blockers.append("funding_must_be_absent_for_spot_candidate")
    if blockers:
        raise ValueError(
            "regime_filtered_breakout_v1 dataset contract failed: "
            + "; ".join(blockers)
        )
    return report


__all__ = ["require_regime_breakout_dataset"]
