"""Preregistration artifacts are immutable and content-verifiable."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from trading_core.alpha_experiment import AlphaExperiment


def _experiment() -> AlphaExperiment:
    return AlphaExperiment(
        experiment_id="alpha-001",
        git_sha="a" * 40,
        dataset_manifest_sha256="b" * 64,
        strategy="regime_filtered_breakout_v1",
        parameters={"window": 24},
        cost_config={"fee_rate": 0.001},
        risk_config={"initial_cash": 10_000.0},
        execution_timing="auto",
        train_range=(100, 199),
        validation_ranges=((200, 299), (300, 399)),
        final_oos_range=(400, 499),
        benchmarks=("buy_and_hold",),
        acceptance_metrics=("minimum_organic_closed_trades=30",),
    )


def test_artifact_round_trip_and_immutable_save(tmp_path: Path) -> None:
    experiment = _experiment()
    path = tmp_path / "alpha-001.json"

    experiment.save(path)
    loaded = AlphaExperiment.load(path)

    assert loaded == experiment
    assert loaded.fingerprint() == experiment.fingerprint()
    with pytest.raises(FileExistsError, match="immutable"):
        experiment.save(path)


def test_artifact_tampering_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "alpha-001.json"
    _experiment().save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["experiment"]["parameters"]["window"] = 999
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="fingerprint mismatch"):
        AlphaExperiment.load(path)


def test_same_event_and_overlapping_ranges_are_rejected() -> None:
    experiment = _experiment()
    with pytest.raises(ValueError, match="same_event"):
        replace(experiment, execution_timing="same_event")
    with pytest.raises(ValueError, match="must not overlap"):
        replace(experiment, validation_ranges=((190, 299),))


def test_git_and_manifest_hashes_must_be_canonical_lowercase_hex() -> None:
    experiment = _experiment()
    with pytest.raises(ValueError, match="git_sha"):
        replace(experiment, git_sha="A" * 40)
    with pytest.raises(ValueError, match="dataset_manifest_sha256"):
        replace(experiment, dataset_manifest_sha256="z" * 64)
