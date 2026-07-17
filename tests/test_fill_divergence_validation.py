from __future__ import annotations

from validation import (
    DivergenceThresholds,
    FillDivergenceAnalyzer,
    FillValidationRepository,
)
from storage import ProjectDatabase


def _fill(match_id: str, *, source: str, latency_ms: int, price: float, filled: float = 1.0):
    submitted = 1_000_000
    return {
        "match_id": match_id,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "submitted_at_ms": submitted,
        "first_fill_at_ms": submitted + latency_ms,
        "completed_at_ms": submitted + latency_ms + 10,
        "requested_quantity": 1.0,
        "filled_quantity": filled,
        "reference_price": 100.0,
        "average_fill_price": price,
        "fee": price * filled * 0.001,
        "status": "Filled" if filled >= 1.0 else "PartiallyFilled",
        "source": source,
    }


def test_low_divergence_is_promotion_eligible_and_persistent(tmp_path) -> None:
    analyzer = FillDivergenceAnalyzer(
        DivergenceThresholds(minimum_matches=2)
    )
    report = analyzer.analyze(
        [
            _fill("sai_1", source="paper", latency_ms=20, price=100.02),
            _fill("sai_2", source="paper", latency_ms=30, price=100.03),
        ],
        [
            _fill("sai_1", source="testnet", latency_ms=100, price=100.05),
            _fill("sai_2", source="testnet", latency_ms=120, price=100.06),
        ],
        report_id="validation-1",
        created_at_ms=2_000_000,
    )

    assert report.matched_count == 2
    assert report.promotion_eligible is True
    assert report.unmatched_paper_count == 0
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    saved = FillValidationRepository(database).save(
        report,
        experiment_id="exp-1",
        actor="validator",
    )
    assert saved["promotion_eligible"] is True
    assert FillValidationRepository(database).get("validation-1")["matched_count"] == 2


def test_unmatched_and_partial_testnet_fills_block_promotion() -> None:
    analyzer = FillDivergenceAnalyzer(
        DivergenceThresholds(
            minimum_matches=1,
            maximum_partial_fill_rate_percent=10.0,
        )
    )
    report = analyzer.analyze(
        [
            _fill("sai_1", source="paper", latency_ms=20, price=100.0),
            _fill("sai_missing", source="paper", latency_ms=20, price=100.0),
        ],
        [
            _fill(
                "sai_1",
                source="testnet",
                latency_ms=5_000,
                price=101.0,
                filled=0.5,
            )
        ],
    )

    assert report.promotion_eligible is False
    assert "unmatched_paper_fills" in report.failed_gates
    assert "partial_fill_rate_exceeded" in report.failed_gates
    assert "latency_divergence_exceeded" in report.failed_gates
    assert "slippage_divergence_exceeded" in report.failed_gates
