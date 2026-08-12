"""Untouched final OOS can be claimed only once per dataset holdout range."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from trading_core.alpha_consumption import (
    FinalOOSAlreadyConsumed,
    claim_final_oos,
    complete_final_oos,
    final_oos_identity,
)
from trading_core.alpha_experiment import AlphaExperiment


def _experiment() -> AlphaExperiment:
    return AlphaExperiment(
        experiment_id="alpha-once",
        git_sha="a" * 40,
        dataset_manifest_sha256="b" * 64,
        strategy="regime_filtered_breakout_v1",
        hypothesis="candidate hypothesis",
        falsification_rule="candidate falsification rule",
        parameters={"window": 24},
        cost_config={"fee_rate": 0.001},
        risk_config={"initial_cash": 10_000.0},
        execution_timing="auto",
        train_range=(100, 199),
        validation_ranges=((200, 299),),
        final_oos_range=(300, 399),
        benchmarks=("buy_and_hold",),
        acceptance_metrics=("minimum_organic_closed_trades=30",),
    )


def test_claim_is_atomic_and_bound_to_dataset_holdout_not_experiment_name(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    experiment = _experiment()
    holdout_id = final_oos_identity(experiment)

    receipt = claim_final_oos(
        manifest_path=manifest,
        experiment=experiment,
        experiment_artifact_sha256="c" * 64,
    )

    assert receipt.parent == tmp_path / ".alpha_consumed"
    assert receipt.name == f"{holdout_id}.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["status"] == "started"
    assert payload["holdout_identity"] == holdout_id
    assert payload["experiment_fingerprint"] == experiment.fingerprint()
    assert payload["final_oos_range"] == [300, 399]

    # Merely changing experiment identity or parameters cannot create a second
    # legitimate look at the same dataset+holdout range.
    renamed = replace(experiment, experiment_id="alpha-renamed", parameters={"window": 99})
    assert renamed.fingerprint() != experiment.fingerprint()
    assert final_oos_identity(renamed) == holdout_id
    with pytest.raises(FinalOOSAlreadyConsumed, match="already consumed"):
        claim_final_oos(
            manifest_path=manifest,
            experiment=renamed,
            experiment_artifact_sha256="d" * 64,
        )


def test_different_untouched_range_has_different_holdout_identity(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    first = _experiment()
    second = replace(first, experiment_id="alpha-new-holdout", final_oos_range=(400, 499))

    first_receipt = claim_final_oos(
        manifest_path=manifest,
        experiment=first,
        experiment_artifact_sha256="c" * 64,
    )
    second_receipt = claim_final_oos(
        manifest_path=manifest,
        experiment=second,
        experiment_artifact_sha256="d" * 64,
    )

    assert first_receipt != second_receipt
    assert final_oos_identity(first) != final_oos_identity(second)


def test_completed_receipt_preserves_one_shot_identity(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    experiment = _experiment()
    receipt = claim_final_oos(
        manifest_path=manifest,
        experiment=experiment,
        experiment_artifact_sha256="c" * 64,
    )
    report = tmp_path / "result.json"
    report.write_text("{}", encoding="utf-8")

    complete_final_oos(
        receipt,
        verdict="REJECT_HYPOTHESIS",
        report_path=report,
        report_sha256="d" * 64,
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))

    assert payload["status"] == "completed"
    assert payload["verdict"] == "REJECT_HYPOTHESIS"
    assert payload["report_sha256"] == "d" * 64
    with pytest.raises(FinalOOSAlreadyConsumed):
        claim_final_oos(
            manifest_path=manifest,
            experiment=experiment,
            experiment_artifact_sha256="c" * 64,
        )


def test_receipt_cannot_be_completed_twice(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    experiment = _experiment()
    receipt = claim_final_oos(
        manifest_path=manifest,
        experiment=experiment,
        experiment_artifact_sha256="c" * 64,
    )
    report = tmp_path / "result.json"
    report.write_text("{}", encoding="utf-8")
    complete_final_oos(
        receipt,
        verdict="INSUFFICIENT_SAMPLE",
        report_path=report,
        report_sha256="d" * 64,
    )

    with pytest.raises(ValueError, match="not in started state"):
        complete_final_oos(
            receipt,
            verdict="ACCEPT_FOR_LONGER_PAPER",
            report_path=report,
            report_sha256="e" * 64,
        )
