"""Untouched final OOS can be claimed only once per dataset holdout range."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from trading_core.alpha_consumption import (
    FinalOOSAlreadyConsumed,
    claim_final_oos,
    complete_final_oos,
    final_oos_identity,
)
from trading_core.alpha_experiment import AlphaExperiment


@pytest.fixture(autouse=True)
def isolated_canonical_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'canonical.sqlite3'}")


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


@pytest.mark.parametrize("window", [(301, 399), (300, 400), (350, 450), (399, 499)])
def test_any_overlap_is_consumed_even_when_endpoints_change(tmp_path, window):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    original = _experiment()
    claim_final_oos(manifest_path=manifest, experiment=original, experiment_artifact_sha256="c" * 64)
    with pytest.raises(FinalOOSAlreadyConsumed):
        claim_final_oos(manifest_path=manifest, experiment=replace(original, final_oos_range=window),
                        experiment_artifact_sha256="d" * 64)


def test_identical_manifest_in_another_directory_cannot_reopen_holdout(tmp_path):
    for name in ("first", "copy"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "manifest.json").write_text("{}")
    claim_final_oos(manifest_path=tmp_path / "first/manifest.json", experiment=_experiment(),
                    experiment_artifact_sha256="c" * 64)
    with pytest.raises(FinalOOSAlreadyConsumed):
        claim_final_oos(manifest_path=tmp_path / "copy/manifest.json", experiment=_experiment(),
                        experiment_artifact_sha256="d" * 64)


def test_concurrent_overlapping_claims_have_one_winner(tmp_path):
    barrier = Barrier(2)
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "manifest.json").write_text("{}")

    def claim(name, window):
        barrier.wait(timeout=10)
        try:
            claim_final_oos(manifest_path=tmp_path / name / "manifest.json",
                            experiment=replace(_experiment(), final_oos_range=window),
                            experiment_artifact_sha256="c" * 64)
            return "claimed"
        except FinalOOSAlreadyConsumed:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, "first", (300, 399)), pool.submit(claim, "second", (350, 450))]
        assert sorted(f.result(timeout=20) for f in futures) == ["blocked", "claimed"]


def test_legacy_receipt_is_imported_on_rejection_and_survives_relocation(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    registry = tmp_path / ".alpha_consumed"
    registry.mkdir()
    experiment = _experiment()
    payload = {"schema_version": 1, "status": "started",
               "dataset_manifest_sha256": experiment.dataset_manifest_sha256,
               "holdout_identity": final_oos_identity(experiment),
               "final_oos_range": list(experiment.final_oos_range)}
    receipt = registry / (final_oos_identity(experiment) + ".json")
    receipt.write_text(json.dumps(payload))
    original = receipt.read_bytes()
    with pytest.raises(FinalOOSAlreadyConsumed):
        claim_final_oos(manifest_path=manifest, experiment=experiment, experiment_artifact_sha256="c" * 64)
    assert receipt.read_bytes() == original
    copied = tmp_path / "copy/manifest.json"
    copied.parent.mkdir()
    copied.write_text("{}")
    with pytest.raises(FinalOOSAlreadyConsumed):
        claim_final_oos(manifest_path=copied, experiment=experiment, experiment_artifact_sha256="c" * 64)


def test_receipt_export_failure_still_consumes_canonical_claim(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    original_open = Path.open

    def fail_export(path, mode="r", *args, **kwargs):
        if mode == "x" and path.parent.name == ".alpha_consumed":
            raise OSError("synthetic receipt export failure")
        return original_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(Path, "open", fail_export)
        with pytest.raises(OSError, match="synthetic receipt export failure"):
            claim_final_oos(manifest_path=manifest, experiment=_experiment(), experiment_artifact_sha256="c" * 64)
    with pytest.raises(FinalOOSAlreadyConsumed):
        claim_final_oos(manifest_path=manifest, experiment=_experiment(), experiment_artifact_sha256="c" * 64)


def test_unavailable_database_does_not_export_a_local_claim(tmp_path):
    from storage import DatabaseUnavailable

    class Unavailable:
        def initialize(self):
            raise DatabaseUnavailable("synthetic database outage")

    with pytest.raises(DatabaseUnavailable, match="synthetic database outage"):
        claim_final_oos(manifest_path=tmp_path / "manifest.json", experiment=_experiment(),
                        experiment_artifact_sha256="c" * 64, database=Unavailable())
    assert not list((tmp_path / ".alpha_consumed").glob("*.json"))


def test_different_manifest_digest_can_claim_the_same_dates(tmp_path):
    original = _experiment()
    for item in (original, replace(original, dataset_manifest_sha256="d" * 64)):
        claim_final_oos(manifest_path=tmp_path / "manifest.json", experiment=item,
                        experiment_artifact_sha256="c" * 64)
    assert len(list((tmp_path / ".alpha_consumed").glob("*.json"))) == 2


def test_stale_receipt_cannot_complete_canonical_claim_twice(tmp_path):
    receipt = claim_final_oos(manifest_path=tmp_path / "manifest.json", experiment=_experiment(),
                              experiment_artifact_sha256="c" * 64)
    started = receipt.read_bytes()
    complete_final_oos(receipt, verdict="INSUFFICIENT_SAMPLE", report_path=tmp_path / "report.json",
                       report_sha256="d" * 64)
    # A stale copy is merely an artifact; it cannot roll back canonical completion.
    copied = tmp_path / "copy/receipt.json"
    copied.parent.mkdir()
    copied.write_bytes(started)
    with pytest.raises(ValueError, match="canonical final OOS claim is not in started state"):
        complete_final_oos(copied, verdict="ACCEPT_FOR_LONGER_PAPER", report_path=tmp_path / "another.json",
                           report_sha256="e" * 64)


def test_malformed_legacy_receipt_fails_closed(tmp_path):
    registry = tmp_path / ".alpha_consumed"
    registry.mkdir()
    receipt = registry / "unreadable.json"
    receipt.write_text('{"schema_version":1,"status":"started"}')
    with pytest.raises(ValueError, match="invalid final OOS claim provenance"):
        claim_final_oos(manifest_path=tmp_path / "manifest.json", experiment=_experiment(),
                        experiment_artifact_sha256="c" * 64)
    assert len(list(registry.glob("*.json"))) == 1
