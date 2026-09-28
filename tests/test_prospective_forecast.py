"""Synthetic fixtures test mathematics/contracts, never production evidence."""
from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from autonomous_trading import forecast_contract as fc
from learning_engine.prospective_validation import fit, metrics, quantile, evaluate
from storage import ProjectDatabase

NOW = 1_800_000_000_000


def passing_artifact(expected=.02):
    group = {"count": 500, "mae": .001, "zero_mae": .002}
    report = {"schema_version": "purged-forecast-validation-v2", "source_coverage": "COMPLETE_CUTOFF",
        "source_sha256": "a" * 64, "asof_safe": True, "globally_purged": True, "holdout_untouched": True,
        "feature_timestamps_verified": True,
        "train_count": 1000, "calibration_count": 300, "test_count": 500,
        "data_span_days": 40, "test_span_days": 8,
        "test": {**group, "coverage": 1., "rmse": .0012, "zero_rmse": .0025,
            "horizon_seconds": fc.HORIZON_SECONDS,
            "mean_baseline_mae": .0015, "directional_accuracy": .6, "interval_coverage": .95,
            "bias": .0001, "actionable_count": 60, "actionable_cost_adjusted_mean": .002,
            "by_symbol": {"ETHUSDT": group}, "by_regime": {"up_24h": group}},
        "folds": [group, group, group]}
    dataset_key = fc.digest(["canonical_paper_opportunities", "test_fixture"])
    start, end = NOW - 1_000_000, NOW - 100_000
    report["holdout_provenance"] = {"schema_version": 2,
        "registry_scope": "canonical_project_database", "dataset_scope": "test_fixture",
        "dataset_manifest_sha256": dataset_key,
        "holdout_identity": hashlib.sha256(f"{dataset_key}:{start}:{end}".encode()).hexdigest(),
        "final_oos_range": [start, end], "status": "started", "claim_id": "synthetic-test-claim",
        "claimed_at_ms": NOW - 95_000, "source_sha256": "a" * 64,
        "producer_version": fc.PRODUCER_VERSION, "validation_version": report["schema_version"]}
    return {"producer_version": fc.PRODUCER_VERSION, "horizon_seconds": fc.HORIZON_SECONDS,
        "model": {"means": [0., 0., 0.], "scales": [1., 1., 1.], "coefficients": [expected, 0., 0., 0.],
                  "baseline_mean": 0.},
        "uncertainty_radius_fraction": .005, "support_count": 1000,
        "training_window": {"start_ms": NOW - 4_000_000, "end_ms": NOW - 3_000_000,
            "labels_available_through_ms": NOW - 2_900_000, "source_sha256": "a" * 64},
        "validation_provenance": {"calibration_start_ms": NOW - 2_800_000,
            "calibration_labels_available_through_ms": NOW - 1_100_000,
            "holdout_start_ms": NOW - 1_000_000, "holdout_end_ms": NOW - 100_000,
            "validated_at_ms": NOW - 90_000, "report_sha256": fc.digest(report)},
        "validation": report, "published_at_ms": NOW - 80_000, "execution_authority": False}


def install_test_holdout(database, artifact):
    """Synthetic receipt confined to the test's isolated ProjectDatabase."""
    proof = artifact["validation"]["holdout_provenance"]
    database.put_json("alpha_holdout_consumption", proof["dataset_manifest_sha256"],
        {"schema_version": 2, "claims": {proof["holdout_identity"]: {**proof, "status": "completed",
            "completed_at_ms": artifact["validation_provenance"]["validated_at_ms"],
            "report_sha256": fc.digest(artifact["validation"])}}})


@pytest.fixture
def forecast(tmp_path, monkeypatch):
    artifact = passing_artifact()
    path = tmp_path / "model.json"
    path.write_text(json.dumps(artifact))
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'canonical.db'}")
    database.initialize()
    install_test_holdout(database, artifact)
    monkeypatch.setattr(fc.time, "time", lambda: NOW / 1000)
    monkeypatch.setattr(fc, "REVIEWED_MODELS", frozenset({fc.digest(artifact)}))
    service = fc.ProspectiveForecastService(database, artifact_path=path)
    q = SimpleNamespace(symbol="ETHUSDT", verified=True, feature_received_at_ms=NOW,
                        bid_price=2499.5, ask_price=2500.5, change_24h_percent=1.,
                        volume_24h=250_000_000., received_at_unix_ms=NOW, source="verified-test-fixture")
    return service.forecast("ETHUSDT", q, as_of_ms=NOW), service, q


def validate(value, service, **changes):
    return fc.validate_forecast(value, **{"symbol": "ETHUSDT", "now_ms": NOW,
        "quote_received_at_ms": NOW, "as_of_ms": NOW,
        "artifact": service.artifact, "database": service.database, **changes})


def resign(value):
    value["forecast_id"] = fc.digest({k: v for k, v in value.items() if k != "forecast_id"})


def test_validated_conservative_return_is_dimensionless_and_cost_comparable(forecast):
    value, service, _ = forecast
    fraction, reason = validate(value, service)
    assert fraction == pytest.approx(.015)
    assert fraction * 10 == pytest.approx(.15)  # 1.5% of 10 USDT, not 1.5 USDT.
    assert reason == "validated_prospective_return"
    assert service.database.get_json("paper_prospective_forecasts", value["forecast_id"])["value"] == value


@pytest.mark.parametrize("field,bad,reason", [
    ("symbol", "BTCUSDT", "symbol_mismatch"), ("horizon_seconds", 900, "horizon_mismatch"),
    ("units", "percent", "units"), ("units", "USDT", "units"),
    ("as_of_ms", NOW + 1, "future_or_asof"), ("feature_cutoff_ms", NOW + 1, "future_or_asof"),
    ("generated_at_ms", NOW + 1, "future_or_asof"), ("expires_at_ms", NOW, "stale"),
    ("expected_return_fraction", float("nan"), "range"), ("conservative_return_fraction", .5, "uncertainty"),
    ("support_count", 0, "provenance"), ("model_sha256", "b" * 64, "provenance"),
    ("producer_version", "unknown", "provenance"), ("training_window", {}, "provenance"),
    ("validation_provenance", {}, "provenance"), ("execution_authority", False, "not_promoted"),
])
def test_invalid_forecasts_fail_closed(forecast, field, bad, reason):
    value, service, _ = forecast
    value[field] = bad
    try:
        resign(value)
    except ValueError:
        pass  # Nonfinite documents are rejected before digest comparison.
    edge, why = validate(value, service)
    assert edge is None
    assert reason in why


@pytest.mark.parametrize("value", [None, [], "0.8", 3.0, {}, {"expected_edge": 1e10}])
def test_missing_and_bare_aliases_never_authorize(forecast, value):
    assert validate(value, forecast[1])[0] is None


def test_stale_quote_mismatch_and_missing_uncertainty(forecast):
    value, service, _ = forecast
    assert validate(value, service, now_ms=NOW + fc.MAX_AGE_MS + 1)[0] is None
    assert validate(value, service, quote_received_at_ms=NOW - 1)[0] is None
    value.pop("uncertainty")
    resign(value)
    assert validate(value, service)[0] is None


@pytest.mark.parametrize("asof", [None, NOW - 1, NOW + 1, True])
def test_quote_identity_and_review_cannot_replace_exact_decision_asof(forecast, asof):
    assert validate(forecast[0], forecast[1], as_of_ms=asof) == (None, "forecast_asof_mismatch")


def test_learning_or_database_cannot_self_promote(forecast, monkeypatch):
    value, service, _ = forecast
    monkeypatch.setattr(fc, "REVIEWED_MODELS", frozenset())
    service.database.put_json("paper_forecast_promotions", value["model_sha256"], {"promoted": True})
    assert validate(value, service) == (None, "forecast_not_promoted")


def test_future_training_or_validation_rejected_even_if_reviewed(forecast, monkeypatch):
    value, service, _ = forecast
    service.artifact["published_at_ms"] = NOW + 1
    value["model_sha256"] = fc.digest(service.artifact)
    monkeypatch.setattr(fc, "REVIEWED_MODELS", frozenset({value["model_sha256"]}))
    resign(value)
    assert validate(value, service) == (None, "forecast_training_or_validation_leakage")


def test_prediction_cannot_be_changed_without_reproducing_model(forecast):
    value, service, _ = forecast
    value["expected_return_fraction"] += .5
    value["conservative_return_fraction"] += .5
    value["uncertainty"]["upper_fraction"] += .5
    resign(value)
    assert validate(value, service)[0] is None


def test_inner_quote_timestamp_must_match_canonical_lineage(forecast):
    value, service, _ = forecast
    value["input_lineage"]["quote"]["received_at_unix_ms"] -= 1
    value["input_lineage"]["quote_sha256"] = fc.digest(value["input_lineage"]["quote"])
    resign(value)
    assert validate(value, service) == (None, "forecast_input_lineage")


@pytest.mark.parametrize("field,value", [("horizon_seconds", 900), ("train_count", 2000)])
def test_review_does_not_override_validation_horizon_or_support(forecast, monkeypatch, field, value):
    forecast_value, service, quote = forecast
    report = service.artifact["validation"]
    (report["test"] if field == "horizon_seconds" else report)[field] = value
    service.artifact["validation_provenance"]["report_sha256"] = fc.digest(report)
    monkeypatch.setattr(fc, "REVIEWED_MODELS", frozenset({fc.digest(service.artifact)}))
    rebuilt = service.forecast("ETHUSDT", quote, as_of_ms=NOW)
    assert validate(rebuilt, service)[0] is None


def test_shadow_artifact_is_not_promoted(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'db'}")
    db.initialize()
    service = fc.ProspectiveForecastService(db)
    assert service.artifact is not None
    assert service.status()["promotion_status"] == "BLOCKED_VALIDATION_OR_REVIEW"
    assert fc.REVIEWED_MODELS == frozenset()
    assert service.artifact["validation"]["profitability_proven"] is False


def synthetic_rows(count=240):
    rows = []
    start = NOW - count * 600_000
    for i in range(count):
        at = start + i * 600_000
        change = ((i % 13) - 6) * .5
        for label, delta in ((False, 0), (True, 300_000)):
            mid = 100 * (1 + change / 1000) if label else 100.
            identity = f"fixture-{i}-{label}"
            rows.append({"opportunity_id": identity, "scope": "fixture", "symbol": "ETHUSDT",
                "decision_time_ms": at + delta, "recorded_at_ms": at + delta + 1,
                "physical_stored_at_ms": at + delta + 1, "capture_digest": fc.digest(identity),
                "market_verified": True, "cost_model": {"fee_rate": .001, "slippage_bps": 2.},
                "quote": {"bid_price": mid - .001, "ask_price": mid + .001,
                    "received_at_unix_ms": at + delta, "change_24h_percent": change,
                    "feature_received_at_ms": at + delta,
                    "volume_24h": 1e6 + i % 7}})
    return rows


def test_global_purge_and_untouched_holdout_do_not_change_fitted_model():
    rows = synthetic_rows()
    first = evaluate(rows, cutoff_ms=NOW, source_coverage="COMPLETE_CUTOFF", evaluated_at_ms=NOW)
    test_start = first["validation_provenance"]["holdout_start_ms"]
    second_rows = copy.deepcopy(rows)
    for row in second_rows:
        if row["decision_time_ms"] >= test_start and row["opportunity_id"].endswith("True"):
            row["quote"]["bid_price"] *= 1.2
            row["quote"]["ask_price"] *= 1.2
    second = evaluate(second_rows, cutoff_ms=NOW, source_coverage="COMPLETE_CUTOFF", evaluated_at_ms=NOW)
    assert first["model"] == second["model"]
    assert first["uncertainty_radius_fraction"] == second["uncertainty_radius_fraction"]
    assert first["validation"]["test"]["mae"] != second["validation"]["test"]["mae"]
    assert first["training_window"]["labels_available_through_ms"] < first["validation_provenance"]["calibration_start_ms"]
    for fold in first["validation"]["folds"]:
        assert fold["train_labels_available_through_ms"] < fold["validation_start_ms"]


def test_future_capture_and_features_excluded_without_replacing_anchors():
    from learning_engine.prospective_validation import dataset
    rows = synthetic_rows(40)
    rows[0]["quote"]["received_at_unix_ms"] += 1
    rows[2]["physical_stored_at_ms"] += 1
    samples, source = dataset(rows, cutoff_ms=NOW)
    assert samples[0]["features"] is None
    assert samples[1]["status"].startswith("INVALID_ASOF_FEATURES")
    assert len(samples) == 40


def test_report_cannot_claim_promotion_with_inadequate_support():
    artifact = passing_artifact()
    assert fc.promotion_failures(artifact["validation"]) == []
    artifact["validation"]["test_count"] = 10
    artifact["validation"]["test"]["count"] = 10
    artifact["validation"]["test"]["actionable_count"] = 0
    artifact["validation"]["asof_safe"] = False
    failures = fc.promotion_failures(artifact["validation"])
    assert "test_count<200" in failures and "asof_or_split_provenance" in failures


@pytest.mark.parametrize("report", [None, [], {"test": []}, {"test_count": float("nan")},
                                   {"test_count": "500"}, {"folds": [None]}])
def test_malformed_validation_cannot_crash_or_promote(report):
    assert fc.promotion_failures(report)


@pytest.mark.parametrize("offset", [1, -5001])
def test_rest_features_have_independent_asof_and_freshness(forecast, offset):
    value, service, quote = forecast
    quote.feature_received_at_ms = NOW + offset
    with pytest.raises(ValueError, match="feature_future_or_stale"):
        service.forecast("ETHUSDT", quote, as_of_ms=NOW)


def test_forecast_cannot_relabel_unverified_or_other_symbol_input(forecast):
    _, service, quote = forecast
    with pytest.raises(ValueError, match="unverified_or_mismatched"):
        service.forecast("BTCUSDT", quote, as_of_ms=NOW)
    quote.verified = False
    with pytest.raises(ValueError, match="unverified_or_mismatched"):
        service.forecast("ETHUSDT", quote, as_of_ms=NOW)


def test_evaluator_does_not_self_attest_untouched_holdout():
    artifact = evaluate(synthetic_rows(), cutoff_ms=NOW, source_coverage="COMPLETE_CUTOFF", evaluated_at_ms=NOW)
    assert artifact["validation"]["holdout_untouched"] is False
    assert "holdout_not_untouched" in artifact["validation"]["promotion_failures"]
    with pytest.raises(TypeError, match="holdout_sealed"):
        evaluate(synthetic_rows(), cutoff_ms=NOW, source_coverage="COMPLETE_CUTOFF", holdout_sealed=True)


def test_evaluator_claims_and_completes_once_in_canonical_database(tmp_path, monkeypatch):
    from trading_core.alpha_consumption import FinalOOSAlreadyConsumed
    monkeypatch.setattr(fc.time, "time", lambda: NOW / 1000)
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'db'}")
    rows = synthetic_rows()
    artifact = evaluate(rows, cutoff_ms=NOW, source_coverage="COMPLETE_CUTOFF", database=db)
    assert artifact["validation"]["holdout_untouched"] is True
    assert fc.verified_holdout_receipt(artifact, db) is True
    with pytest.raises(FinalOOSAlreadyConsumed):
        evaluate(rows, cutoff_ms=NOW, source_coverage="COMPLETE_CUTOFF", database=db)


def test_failed_evaluation_cannot_reopen_its_holdout(tmp_path, monkeypatch):
    from trading_core.alpha_consumption import FinalOOSAlreadyConsumed
    monkeypatch.setattr(fc.time, "time", lambda: NOW / 1000)
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'db'}")
    rows = synthetic_rows(10)
    with pytest.raises(ValueError, match="training_labels"):
        evaluate(rows, cutoff_ms=NOW, source_coverage="COMPLETE_CUTOFF", database=db)
    with pytest.raises(FinalOOSAlreadyConsumed):
        evaluate(rows, cutoff_ms=NOW, source_coverage="COMPLETE_CUTOFF", database=db)


@pytest.mark.parametrize("corruption", ["missing", "uncompleted", "different_report", "different_claim", "different_range"])
def test_model_review_cannot_override_broken_holdout_receipt(forecast, corruption):
    value, service, quote = forecast
    proof = service.artifact["validation"]["holdout_provenance"]
    registry = service.database.get_json("alpha_holdout_consumption", proof["dataset_manifest_sha256"])["value"]
    receipt = registry["claims"][proof["holdout_identity"]]
    if corruption == "missing":
        registry["claims"] = {}
    elif corruption == "uncompleted":
        receipt["status"] = "started"
    elif corruption == "different_report":
        receipt["report_sha256"] = "b" * 64
    elif corruption == "different_claim":
        receipt["claim_id"] = "unrelated"
    else:
        receipt["final_oos_range"][0] += 1
    service.database.put_json("alpha_holdout_consumption", proof["dataset_manifest_sha256"], registry)
    assert validate(value, service) == (None, "forecast_holdout_receipt_unverified")
    assert service.forecast("ETHUSDT", quote, as_of_ms=NOW)["status"] == "SHADOW"


@pytest.mark.parametrize("field,value", [("coverage", 1.1), ("directional_accuracy", 2.),
    ("interval_coverage", 1.01), ("mae", -.1), ("rmse", -.01), ("actionable_count", 501),
    ("actionable_count", 50.5)])
def test_impossible_validation_metrics_fail_closed(field, value):
    report = passing_artifact()["validation"]
    report["test"][field] = value
    assert fc.promotion_failures(report) == ["validation_malformed"]


@pytest.mark.parametrize("offset", [1, -300_001])
def test_future_label_has_independent_rest_timestamp(offset):
    from learning_engine.prospective_validation import dataset
    rows = synthetic_rows(40)
    rows[1]["quote"]["feature_received_at_ms"] += offset
    samples, _ = dataset(rows, cutoff_ms=NOW)
    assert samples[0]["status"].startswith("INVALID_ASOF_FEATURES")
    assert len(samples) == 40


def test_renamed_exports_cannot_reopen_consumed_holdout(tmp_path):
    from learning_engine.prospective_validation import claim_holdout
    from trading_core.alpha_consumption import FinalOOSAlreadyConsumed
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'db'}")
    first = claim_holdout(db, scope="fixture", start_ms=1000, end_ms=2000, source_sha256="a" * 64)
    assert first["registry_scope"] == "canonical_project_database"
    with pytest.raises(FinalOOSAlreadyConsumed):
        claim_holdout(db, scope="fixture", start_ms=1500, end_ms=2500, source_sha256="b" * 64)
    assert claim_holdout(db, scope="fixture", start_ms=2001, end_ms=3000, source_sha256="b" * 64)


def test_previous_session_holdout_remains_consumed(tmp_path):
    from learning_engine.prospective_validation import claim_holdout
    from trading_core.alpha_consumption import FinalOOSAlreadyConsumed
    artifact = json.loads(fc.ARTIFACT_PATH.read_text())
    provenance = artifact["validation_provenance"]
    with pytest.raises(FinalOOSAlreadyConsumed):
        claim_holdout(ProjectDatabase(f"sqlite:///{tmp_path / 'db'}"),
            scope=artifact["export_provenance"]["scope"], start_ms=provenance["holdout_start_ms"],
            end_ms=provenance["holdout_end_ms"], source_sha256="c" * 64)
