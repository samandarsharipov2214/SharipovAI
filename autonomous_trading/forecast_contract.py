"""Prospective return evidence for PAPER; never a source of trade direction.

Market Intelligence owns inference. Learning owns the immutable fitted artifact
and chronological validation. Only a code-reviewed artifact in REVIEWED_MODELS
can supply an actionable return to the existing GC/Risk/Security/PAPER chain.
Database flags, Council confidence and LLM output cannot grant this authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from storage import VersionConflict

CONTRACT_VERSION = "paper-return-forecast-v1"
PRODUCER_VERSION = "quote-ridge-300s-v1"
HORIZON_SECONDS = 300
MAX_AGE_MS = 8_000
QUOTE_MAX_AGE_MS = 2_000
UNITS = "gross_midpoint_return_fraction"
ARTIFACT_PATH = Path(__file__).with_name("forecast_artifact.json")
# Deliberately empty. Promotion requires a separate reviewed code change binding
# the complete artifact hash, not a mutable database status or a model score.
REVIEWED_MODELS: frozenset[str] = frozenset()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite numerical value required")
    return float(value)


def timestamp(value: Any) -> int:
    value = number(value)
    if value <= 0 or not value.is_integer():
        raise ValueError("positive integral UTC milliseconds required")
    return int(value)


def quote_features(quote: Mapping[str, Any], *, as_of_ms: int, require_timestamps: bool = False) -> list[float]:
    """Only frozen, as-of quote fields; no outcome, confidence or later news."""
    received = timestamp(quote.get("received_at_unix_ms"))
    if not 0 <= timestamp(as_of_ms) - received <= QUOTE_MAX_AGE_MS:
        raise ValueError("quote_future_or_stale")
    feature_time = quote.get("feature_received_at_ms")
    if require_timestamps or feature_time is not None:
        if not 0 <= as_of_ms - timestamp(feature_time) <= 5_000:
            raise ValueError("feature_future_or_stale")
    bid, ask = number(quote.get("bid_price")), number(quote.get("ask_price"))
    change, turnover = number(quote.get("change_24h_percent")), number(quote.get("volume_24h"))
    if not 0 < bid <= ask or turnover <= 0 or abs(change) > 100:
        raise ValueError("invalid_quote_features")
    return [change / 100.0, (ask - bid) / ((ask + bid) / 2), math.log1p(turnover)]


def predict(model: Mapping[str, Any], features: list[float]) -> float:
    means, scales, coefficients = (model[k] for k in ("means", "scales", "coefficients"))
    if len(means) != 3 or len(scales) != 3 or len(coefficients) != 4 or len(features) != 3:
        raise ValueError("model_shape")
    values = []
    for x, mean, scale in zip(features, means, scales):
        if number(scale) <= 0:
            raise ValueError("model_scale")
        values.append((number(x) - number(mean)) / number(scale))
    return number(number(coefficients[0]) + math.fsum(number(c) * x for c, x in zip(coefficients[1:], values)))


def feature_regime(features: list[float]) -> str:
    return "up_24h" if features[0] >= .008 else "down_24h" if features[0] <= -.008 else "range_24h"


def promotion_failures(report: Mapping[str, Any]) -> list[str]:
    """Fixed gates; forecast validation never establishes PAPER profitability."""
    try:
        # Refuse malformed/NaN reports even in non-gating diagnostic fields.
        digest(report)
        return _promotion_failures(report)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return ["validation_malformed"]


def _promotion_failures(report: Mapping[str, Any]) -> list[str]:
    failures = []
    if report.get("schema_version") != "purged-forecast-validation-v2":
        failures.append("validation_contract")
    if report.get("source_coverage") != "COMPLETE_CUTOFF":
        failures.append("source_coverage")
    if report.get("asof_safe") is not True or report.get("globally_purged") is not True:
        failures.append("asof_or_split_provenance")
    if report.get("feature_timestamps_verified") is not True:
        failures.append("feature_timestamp_provenance")
    if report.get("holdout_untouched") is not True:
        failures.append("holdout_not_untouched")
    for name, minimum in (("train_count", 500), ("calibration_count", 200), ("test_count", 200)):
        if type(report.get(name)) is not int:
            raise ValueError("integral support required")
        if number(report.get(name, 0)) < minimum:
            failures.append(f"{name}<{minimum}")
    if number(report.get("data_span_days", 0)) < 28:
        failures.append("data_span_days<28")
    if number(report.get("test_span_days", 0)) < 7:
        failures.append("test_span_days<7")
    test = report.get("test") or {}
    if test:
        for key in ("coverage", "directional_accuracy", "interval_coverage"):
            if not 0 <= number(test[key]) <= 1:
                raise ValueError("probability outside unit interval")
        for key in ("mae", "rmse", "zero_mae", "zero_rmse", "mean_baseline_mae"):
            if number(test[key]) < 0:
                raise ValueError("negative forecast loss")
        if (type(test.get("actionable_count")) is not int
                or not 0 <= test["actionable_count"] <= report["test_count"]):
            raise ValueError("invalid actionable support")
    if (test.get("count") != report.get("test_count")
            or not isinstance(report.get("source_sha256"), str) or len(report["source_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in report["source_sha256"])):
        failures.append("validation_support_provenance")
    if not test or number(test.get("coverage", 0)) < .8:
        failures.append("test_coverage<0.8")
    if (not test or number(test.get("mae", 1)) >= number(test.get("zero_mae", 0)) * .98
            or number(test.get("rmse", 1)) >= number(test.get("zero_rmse", 0))):
        failures.append("no_loss_improvement_over_zero")
    if not test or number(test.get("mae", 1)) >= number(test.get("mean_baseline_mae", 0)):
        failures.append("no_loss_improvement_over_training_mean")
    if not test or number(test.get("directional_accuracy", 0)) < .52:
        failures.append("directional_accuracy<0.52")
    if not test or number(test.get("interval_coverage", 0)) < .90:
        failures.append("uncertainty_coverage<0.90")
    if not test or abs(number(test.get("bias", 1))) > number(test.get("mae", 0)) * .25:
        failures.append("return_calibration_bias")
    if (number(test.get("actionable_count", 0)) < 50
            or number(test.get("actionable_cost_adjusted_mean", 0) or 0) <= 0):
        failures.append("insufficient_cost_adjusted_actionable_support")
    folds = report.get("folds") or []
    if len(folds) < 3 or any(type(f.get("count")) is not int or f["count"] < 50
            or not 0 <= number(f.get("mae", 1)) < number(f.get("zero_mae", 0)) for f in folds):
        failures.append("unstable_chronological_folds")
    for dimension in ("by_symbol", "by_regime"):
        groups = test.get(dimension) or {}
        if (not groups or any(type(g.get("count")) is not int or g["count"] < 50
                or not 0 <= number(g.get("mae", 1)) < number(g.get("zero_mae", 0))
                for g in groups.values())
                or sum(g["count"] for g in groups.values()) != report["test_count"]):
            failures.append(f"insufficient_or_unstable_{dimension}")
    return failures


def validate_forecast(value: Any, *, symbol: str, now_ms: int,
                      quote_received_at_ms: int, horizon_seconds: int = HORIZON_SECONDS,
                      artifact: Mapping[str, Any] | None = None,
                      reviewed_models: frozenset[str] | None = None) -> tuple[float | None, str]:
    """Return a conservative dimensionless return, never an untyped USD alias."""
    if value is None:
        return None, "forecast_missing"
    try:
        if not isinstance(value, Mapping):
            raise ValueError("forecast_malformed")
        if value.get("contract_version") != CONTRACT_VERSION or value.get("units") != UNITS:
            raise ValueError("forecast_contract_or_units")
        if value.get("symbol") != symbol:
            raise ValueError("forecast_symbol_mismatch")
        if type(value.get("horizon_seconds")) is not int or value["horizon_seconds"] != horizon_seconds:
            raise ValueError("forecast_horizon_mismatch")
        asof, cutoff, created, expires = (timestamp(value.get(k)) for k in
            ("as_of_ms", "feature_cutoff_ms", "generated_at_ms", "expires_at_ms"))
        if not cutoff <= asof <= created <= now_ms or asof - cutoff > QUOTE_MAX_AGE_MS:
            raise ValueError("forecast_future_or_asof_leakage")
        if not 0 <= now_ms - asof <= MAX_AGE_MS or not now_ms < expires <= asof + MAX_AGE_MS:
            raise ValueError("forecast_stale")
        lineage = value["input_lineage"]
        if (lineage["quote_received_at_ms"] != quote_received_at_ms
                or timestamp(lineage["quote"]["received_at_unix_ms"]) != quote_received_at_ms
                or cutoff != max(quote_received_at_ms, timestamp(lineage["quote"]["feature_received_at_ms"]))
                or lineage["quote"]["symbol"] != symbol or lineage["quote"]["verified"] is not True
                or not lineage["source"]
                or lineage["quote_sha256"] != digest(lineage["quote"])):
            raise ValueError("forecast_input_lineage")
        features = quote_features(lineage["quote"], as_of_ms=asof, require_timestamps=True)
        if value["forecast_id"] != digest({k: v for k, v in value.items() if k != "forecast_id"}):
            raise ValueError("forecast_digest")
        if value["status"] == "UNAVAILABLE":
            raise ValueError("forecast_unavailable:" + str(value.get("reason")))
        expected, lower = number(value["expected_return_fraction"]), number(value["conservative_return_fraction"])
        u = value["uncertainty"]
        radius = number(u["radius_fraction"])
        if (u["method"] != "chronological_calibration_absolute_residual"
                or u["nominal_coverage"] != .95 or radius <= 0
                or not math.isclose(lower, expected - radius, abs_tol=1e-12)
                or not math.isclose(number(u["upper_fraction"]), expected + radius, abs_tol=1e-12)):
            raise ValueError("forecast_uncertainty")
        if not artifact or value["model_sha256"] != digest(artifact):
            raise ValueError("forecast_model_provenance")
        if (value["producer_version"] != PRODUCER_VERSION or artifact["producer_version"] != PRODUCER_VERSION
                or artifact["horizon_seconds"] != horizon_seconds
                or value["training_window"] != artifact["training_window"]
                or value["validation_provenance"] != artifact["validation_provenance"]
                or value["support_count"] != artifact["support_count"]
                or value["support_count"] != artifact["validation"]["train_count"]
                or artifact["validation"]["test"]["horizon_seconds"] != horizon_seconds
                or type(value["support_count"]) is not int or value["support_count"] < 1
                or not math.isclose(expected, predict(artifact["model"], features), abs_tol=1e-12)
                or radius != artifact["uncertainty_radius_fraction"]):
            raise ValueError("forecast_provenance_or_prediction")
        train, validation = value["training_window"], value["validation_provenance"]
        if not (0 < timestamp(train["start_ms"]) < timestamp(train["end_ms"])
                < timestamp(validation["calibration_start_ms"])
                < timestamp(validation["holdout_start_ms"]) < timestamp(validation["holdout_end_ms"])
                <= timestamp(validation["validated_at_ms"]) <= timestamp(artifact["published_at_ms"]) < asof
                and timestamp(train["labels_available_through_ms"]) < validation["calibration_start_ms"]):
            raise ValueError("forecast_training_or_validation_leakage")
        if (value["validation_provenance"]["report_sha256"] != digest(artifact["validation"])
                or value["training_window"]["source_sha256"] != artifact["validation"]["source_sha256"]):
            raise ValueError("forecast_validation_digest")
        approved = REVIEWED_MODELS if reviewed_models is None else reviewed_models
        if (value["model_sha256"] not in approved or promotion_failures(artifact["validation"])
                or value["status"] != "PROMOTED" or value["execution_authority"] is not True):
            raise ValueError("forecast_not_promoted")
        if symbol not in artifact["validation"]["test"]["by_symbol"]:
            raise ValueError("forecast_symbol_unsupported")
        if (value["market_regime"] != feature_regime(features)
                or value["market_regime"] not in artifact["validation"]["test"]["by_regime"]):
            raise ValueError("forecast_regime_unsupported")
        if not (timestamp(train["labels_available_through_ms"]) >= timestamp(train["end_ms"])
                and timestamp(validation["calibration_labels_available_through_ms"]) < timestamp(validation["holdout_start_ms"])
                and timestamp(validation["calibration_labels_available_through_ms"]) >= timestamp(validation["calibration_start_ms"])):
            raise ValueError("forecast_calibration_leakage")
        return lower, "validated_prospective_return"
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as error:
        return None, str(error) if isinstance(error, ValueError) else "forecast_malformed:" + type(error).__name__


class ProspectiveForecastService:
    """Small deterministic inference; no training, orders, network or auto-promotion."""
    def __init__(self, database, *, artifact_path: Path = ARTIFACT_PATH):
        self.database = database
        self.artifact = None
        self.error = None
        self.attempted = self.generated = self.available = self.rejected = 0
        self.last_at_ms = None
        try:
            artifact = json.loads(artifact_path.read_text())
            if artifact["producer_version"] != PRODUCER_VERSION:
                raise ValueError("artifact_producer_version")
            predict(artifact["model"], [0., 0., 0.])
            number(artifact["uncertainty_radius_fraction"])
            promotion_failures(artifact["validation"])
            if artifact["validation_provenance"]["report_sha256"] != digest(artifact["validation"]):
                raise ValueError("artifact_validation_digest")
            self.artifact = artifact
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as error:
            self.error = "artifact_unavailable:" + type(error).__name__

    def forecast(self, symbol: str, quote: Any, *, as_of_ms: int) -> dict:
        self.attempted += 1
        frozen = {key: getattr(quote, key, None) for key in
                  ("symbol", "verified", "bid_price", "ask_price", "received_at_unix_ms",
                   "feature_received_at_ms", "change_24h_percent", "volume_24h")}
        if frozen["symbol"] != symbol or frozen["verified"] is not True or not getattr(quote, "source", None):
            raise ValueError("forecast_unverified_or_mismatched_quote")
        features = quote_features(frozen, as_of_ms=as_of_ms, require_timestamps=True)
        a = self.artifact
        promoted = bool(a and digest(a) in REVIEWED_MODELS and not promotion_failures(a["validation"]))
        expected = predict(a["model"], features) if a and a.get("model") else None
        radius = a.get("uncertainty_radius_fraction") if a else None
        if radius is not None:
            radius = number(radius)
        available = expected is not None and radius is not None and radius > 0
        value = {
            "contract_version": CONTRACT_VERSION, "producer_version": PRODUCER_VERSION,
            "symbol": symbol, "as_of_ms": as_of_ms,
            "feature_cutoff_ms": max(int(frozen["received_at_unix_ms"]), int(frozen["feature_received_at_ms"])),
            "generated_at_ms": int(time.time() * 1000), "expires_at_ms": as_of_ms + MAX_AGE_MS,
            "horizon_seconds": HORIZON_SECONDS, "units": UNITS,
            "market_regime": feature_regime(features),
            "expected_return_fraction": expected if available else None,
            "conservative_return_fraction": expected - radius if available else None,
            "uncertainty": {"method": "chronological_calibration_absolute_residual", "nominal_coverage": .95,
                "radius_fraction": radius, "upper_fraction": expected + radius if available else None},
            "status": "PROMOTED" if promoted and available else "SHADOW" if available else "UNAVAILABLE",
            "reason": None if promoted else "unreviewed_or_validation_failed" if available else self.error or "insufficient_training_support",
            "execution_authority": promoted and available,
            "support_count": a["support_count"] if a else 0,
            "model_sha256": digest(a) if a else None,
            "training_window": a["training_window"] if a else None,
            "validation_provenance": a["validation_provenance"] if a else None,
            "input_lineage": {"source": quote.source,
                "quote_received_at_ms": int(frozen["received_at_unix_ms"]), "quote_sha256": digest(frozen), "quote": frozen},
        }
        value["forecast_id"] = digest(value)
        try:
            self.database.put_json("paper_prospective_forecasts", value["forecast_id"], value, expected_version=0)
            self.generated += 1
        except VersionConflict:
            existing = self.database.get_json("paper_prospective_forecasts", value["forecast_id"])
            if not existing or existing["value"] != value:
                raise ValueError("conflicting_immutable_forecast")
        self.available += int(available)
        self.last_at_ms = as_of_ms
        self.error = None if available else value["reason"]
        return value

    def status(self) -> dict:
        a = self.artifact
        promoted = bool(a and digest(a) in REVIEWED_MODELS and not promotion_failures(a["validation"]))
        return {"prospective_edge_producer": PRODUCER_VERSION, "contract_version": CONTRACT_VERSION,
            "status": "DEGRADED" if self.error else "PROMOTED" if promoted else "SHADOW" if a else "UNAVAILABLE",
            "promotion_status": "PROMOTED" if promoted else "BLOCKED_VALIDATION_OR_REVIEW",
            "validation_failures": promotion_failures(a["validation"]) if a else ["artifact_unavailable"],
            "attempted": self.attempted, "generated": self.generated, "available": self.available,
            "rejected_evaluations": self.rejected,
            "forecast_coverage": self.available / self.attempted if self.attempted else None,
            "coverage_denominator": "proposals_reaching_forecast_inference_this_process",
            "last_generated_at_ms": self.last_at_ms, "error": self.error,
            "execution_authority": False, "profitability_proven": False}
