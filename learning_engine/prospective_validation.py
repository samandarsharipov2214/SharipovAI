"""Leakage-safe, fixed-specification quote forecast research owned by Learning.

Uses the existing economic observer's fixed-horizon labels. No order, fabricated
fill, policy mutation, automated search or promotion occurs here. Chronological
uncertainty calibration is empirical; serial dependence precludes an IID coverage
guarantee. Final holdout results are diagnostics, never future profit evidence.
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from autonomous_trading.forecast_contract import (
    ARTIFACT_PATH, HORIZON_SECONDS, PRODUCER_VERSION, digest, number, predict, promotion_failures,
    quote_features, timestamp, feature_regime,
)
from learning_engine.opportunity_markouts import fixed_horizon_markouts
from trading_core.costs import ExecutionCostModel
from trading_core.models import MarketEvent, Side
from trading_core.alpha_consumption import FinalOOSAlreadyConsumed, _locked_claims

VALIDATION_VERSION = "purged-forecast-validation-v2"
RIDGE = .001


def claim_holdout(database, *, scope: str, start_ms: int, end_ms: int, source_sha256: str) -> dict:
    """Use the existing canonical one-shot registry across exports/directories.

    Its dataset key is the opportunity scope, so a new export hash or filename
    cannot reopen overlapping observations. Preserve the already inspected v1
    artifact's range too. External research/renamed scopes still require review.
    A failed experiment remains consumed; there is no delete/retry escape hatch.
    """
    start, end = timestamp(start_ms), timestamp(end_ms)
    if not scope or start > end or len(source_sha256) != 64:
        raise ValueError("invalid holdout identity")
    dataset_key = digest(["canonical_paper_opportunities", scope])

    def claim(lo, hi, source, status):
        import hashlib
        return {"schema_version": 2, "registry_scope": "canonical_project_database",
            "dataset_manifest_sha256": dataset_key, "dataset_scope": scope,
            "holdout_identity": hashlib.sha256(f"{dataset_key}:{lo}:{hi}".encode()).hexdigest(),
            "final_oos_range": [lo, hi], "source_sha256": source,
            "status": status, "producer_version": PRODUCER_VERSION,
            "validation_version": VALIDATION_VERSION, "claimed_at_ms": int(time.time() * 1000)}

    payload = claim(start, end, source_sha256, "started")
    legacy = json.loads(ARTIFACT_PATH.read_text())
    with _locked_claims(database, dataset_key) as claims:
        if legacy.get("export_provenance", {}).get("scope") == scope:
            provenance = legacy["validation_provenance"]
            previous = claim(provenance["holdout_start_ms"], provenance["holdout_end_ms"],
                             legacy["export_provenance"]["sha256"], "completed")
            previous.update(validation_version=legacy["validation"]["schema_version"],
                            report_sha256=provenance["report_sha256"], imported_sealed_artifact=digest(legacy))
            claims.setdefault(previous["holdout_identity"], previous)
        consumed = any(start <= item["final_oos_range"][1] and end >= item["final_oos_range"][0]
                       for item in claims.values())
        if not consumed:
            claims[payload["holdout_identity"]] = payload
    if consumed:
        raise FinalOOSAlreadyConsumed("forecast holdout overlaps previously inspected opportunity scope")
    return payload


def dataset(rows: Sequence[Mapping[str, Any]], *, cutoff_ms: int) -> tuple[list[dict], dict]:
    """Reserve anchors before label checks; retain every missing/invalid anchor.

    These fields were captured synchronously before economic assessment and are
    the ONLY predictors. Retrospective cohort means, outcomes, confidence, result
    fields, later news and Learning annotations are excluded by construction.
    Physical persistence is checked in addition to claimed decision timestamps.
    """
    report = fixed_horizon_markouts(rows, cutoff_ms=cutoff_ms,
        horizons_seconds=(HORIZON_SECONDS,), anchor_population="all_opportunities")
    by_id = {r["opportunity_id"]: r for r in rows}
    result = []
    for label in report["records"]:
        entry = by_id[label["opportunity_id"]]
        item = {**label, "features": None}
        result.append(item)
        if label["status"] != "OBSERVED":
            continue
        future = by_id[label["label_opportunity_id"]]
        try:
            for raw in (entry, future):
                if (timestamp(raw["physical_stored_at_ms"]) != timestamp(raw["recorded_at_ms"])
                        or len(raw.get("capture_digest") or "") != 64):
                    raise ValueError("physical_capture_provenance")
            item["features"] = quote_features(entry["quote"], as_of_ms=entry["decision_time_ms"])
            item["feature_timestamps_verified"] = all(raw["quote"].get("feature_received_at_ms") is not None
                                                       for raw in (entry, future))
            if future["quote"].get("feature_received_at_ms") is not None:
                quote_features(future["quote"], as_of_ms=future["decision_time_ms"], require_timestamps=True)
                target = entry["decision_time_ms"] + HORIZON_SECONDS * 1000
                if not target <= timestamp(future["quote"]["feature_received_at_ms"]) <= target + 10_000:
                    raise ValueError("label_bbo_outside_horizon")
            if entry["physical_stored_at_ms"] >= entry["decision_time_ms"] + HORIZON_SECONDS * 1000:
                raise ValueError("capture_after_horizon")
            item["target"] = number(label["midpoint_change_percent"]) / 100.0
            item["regime"] = feature_regime(item["features"])
            q = entry["quote"]
            midpoint = (q["ask_price"] + q["bid_price"]) / 2
            # Frozen 10 USDT research size; not a fill, order or portfolio replay.
            quantity = 10 / midpoint
            cost = ExecutionCostModel(**entry["cost_model"])
            event = MarketEvent(timestamp_ms=int(q["received_at_unix_ms"]), symbol=entry["symbol"],
                bid=q["bid_price"], ask=q["ask_price"], source="captured_verified_quote",
                volume=q["volume_24h"] / midpoint)
            estimate = cost.estimate_round_trip(event, quantity=quantity)
            item["estimated_cost_fraction"] = estimate.all_in / 10
            # Keep return and cost denominators identical (entry midpoint *
            # quantity), and use the canonical SELL slippage formula too.
            fq = future["quote"]
            exit_event = MarketEvent(timestamp_ms=int(fq["received_at_unix_ms"]), symbol=entry["symbol"],
                bid=fq["bid_price"], ask=fq["ask_price"], source="captured_verified_quote", volume=event.volume)
            buy = cost.estimate(event, side=Side.BUY, quantity=quantity)
            sell = cost.estimate(exit_event, side=Side.SELL, quantity=quantity)
            item["cost_adjusted_proxy"] = ((sell.execution_price - buy.execution_price) * quantity
                                             - buy.fee - sell.fee) / 10
            item["source_sha256"] = digest({"entry": entry["capture_digest"], "label": future["capture_digest"],
                "entry_stored": entry["physical_stored_at_ms"], "label_stored": future["physical_stored_at_ms"]})
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            item.update(status="INVALID_ASOF_FEATURES:" + str(error), features=None)
    return result, {"source_rows": len(rows), "source_sha256": report["source_sha256"],
                    "anchor_count": len(result), "coverage": dict(Counter(r["status"] for r in result))}


def fit(rows: Sequence[Mapping[str, Any]]) -> dict:
    if len(rows) < 20:
        raise ValueError("at_least_20_training_labels_required")
    means = [math.fsum(r["features"][i] for r in rows) / len(rows) for i in range(3)]
    scales = [max(math.sqrt(math.fsum((r["features"][i] - means[i]) ** 2 for r in rows) / len(rows)), 1e-12)
              for i in range(3)]
    xs = [[1.] + [(r["features"][i] - means[i]) / scales[i] for i in range(3)] for r in rows]
    matrix = [[math.fsum(x[i] * x[j] for x in xs) / len(xs) + (RIDGE if i == j and i else 0)
               for j in range(4)] + [math.fsum(x[i] * r["target"] for x, r in zip(xs, rows)) / len(xs)]
              for i in range(4)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda i: abs(matrix[i][col]))
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        divisor = matrix[col][col]
        if abs(divisor) < 1e-15:
            raise ValueError("singular_training_features")
        matrix[col] = [v / divisor for v in matrix[col]]
        for i in range(4):
            if i != col:
                factor = matrix[i][col]
                matrix[i] = [v - factor * p for v, p in zip(matrix[i], matrix[col])]
    return {"means": means, "scales": scales, "coefficients": [row[-1] for row in matrix],
            "ridge": RIDGE, "baseline_mean": math.fsum(r["target"] for r in rows) / len(rows)}


def quantile(values: list[float], coverage: float = .95) -> float:
    if len(values) < 20:
        raise ValueError("at_least_20_calibration_labels_required")
    rank = min(len(values), math.ceil((len(values) + 1) * coverage))
    return sorted(values)[rank - 1]


def metrics(rows: Sequence[Mapping[str, Any]], model: Mapping[str, Any], *,
            radius: float | None = None, total: int | None = None, groups: bool = True) -> dict:
    if not rows:
        return {"count": 0, "coverage": 0}
    predictions = [predict(model, r["features"]) for r in rows]
    ys = [r["target"] for r in rows]
    errors = [p - y for p, y in zip(predictions, ys)]
    mean = lambda values: math.fsum(values) / len(values) if values else None
    calls = [(p, y) for p, y in zip(predictions, ys) if p != 0 and y != 0]
    actionable = [r for p, r in zip(predictions, rows)
                  if radius is not None and p - radius > 1.5 * r["estimated_cost_fraction"]]
    out = {"count": len(rows), "coverage": len(rows) / (len(rows) if total is None else total),
        "mae": mean([abs(e) for e in errors]), "rmse": math.sqrt(mean([e * e for e in errors])),
        "zero_mae": mean([abs(y) for y in ys]), "zero_rmse": math.sqrt(mean([y * y for y in ys])),
        "mean_baseline_mae": mean([abs(y - model["baseline_mean"]) for y in ys]),
        "directional_accuracy": mean([float(p * y > 0) for p, y in calls]) or 0.,
        "directional_count": len(calls), "bias": mean(errors),
        "expected_mean": mean(predictions), "realized_mean": mean(ys),
        "interval_coverage": mean([float(abs(e) <= radius) for e in errors]) if radius is not None else None,
        "interval_width": 2 * radius if radius is not None else None,
        "actionable_count": len(actionable),
        "actionable_cost_adjusted_mean": mean([r["cost_adjusted_proxy"] for r in actionable]),
        "cost_adjusted_mean": mean([r["cost_adjusted_proxy"] for r in rows]),
        "horizon_seconds": HORIZON_SECONDS}
    if groups:
        for field in ("symbol", "regime"):
            out["by_" + field] = {v: metrics([r for r in rows if r[field] == v], model, radius=radius, groups=False)
                                    for v in sorted({r[field] for r in rows})}
        ordered = sorted(zip(predictions, ys))
        out["calibration_bins"] = []
        for i in range(5):
            bucket = ordered[len(ordered) * i // 5:len(ordered) * (i + 1) // 5]
            out["calibration_bins"].append({"count": len(bucket), "expected_mean": mean([p for p, y in bucket]),
                                            "realized_mean": mean([y for p, y in bucket])})
    return out


def evaluate(rows: Sequence[Mapping[str, Any]], *, cutoff_ms: int, source_coverage: str,
             evaluated_at_ms: int | None = None, holdout_sealed: bool = False) -> dict:
    """One fixed chronological experiment. Caller must seal its untouched source.

    Every symbol shares time boundaries. A training/calibration label must be
    physically available strictly before the next period starts. Thus overlapping
    labels cannot cross any split even across symbols. No final-test refitting.
    """
    samples, source = dataset(rows, cutoff_ms=cutoff_ms)
    if not samples:
        raise ValueError("no_captured_anchors")
    first = min(r["decision_time_ms"] for r in samples)
    span = cutoff_ms - first
    cal_start, test_start = first + int(span * .6), first + int(span * .8)
    valid = [r for r in samples if r["status"] == "OBSERVED" and r["features"] is not None]
    train = [r for r in valid if r["decision_time_ms"] < cal_start and r["label_available_at_ms"] < cal_start]
    calibration = [r for r in valid if cal_start <= r["decision_time_ms"] < test_start
                   and r["label_available_at_ms"] < test_start]
    test = [r for r in valid if test_start <= r["decision_time_ms"] and r["label_available_at_ms"] <= cutoff_ms]
    model = fit(train)
    radius = quantile([abs(predict(model, r["features"]) - r["target"]) for r in calibration])
    folds = []
    for train_fraction, end_fraction in ((.30, .40), (.40, .50), (.50, .60)):
        boundary, end = first + int(span * train_fraction), first + int(span * end_fraction)
        ft = [r for r in valid if r["decision_time_ms"] < boundary and r["label_available_at_ms"] < boundary]
        fv = [r for r in valid if boundary <= r["decision_time_ms"] < end and r["label_available_at_ms"] < end]
        if len(ft) >= 20 and fv:
            folds.append({**metrics(fv, fit(ft), groups=False), "training_count": len(ft),
                "train_labels_available_through_ms": max(r["label_available_at_ms"] for r in ft),
                "validation_start_ms": boundary, "validation_end_ms": end})
    evaluated = evaluated_at_ms or int(time.time() * 1000)
    if evaluated < cutoff_ms:
        raise ValueError("evaluation_before_source_cutoff")
    report = {"schema_version": VALIDATION_VERSION, **source, "source_coverage": source_coverage,
        "asof_safe": True, "globally_purged": True, "holdout_untouched": holdout_sealed is True,
        "feature_timestamps_verified": all(r.get("feature_timestamps_verified") is True for r in valid),
        "split_policy": "fixed_60_20_20_global_time; purge_labels_not_physically_available_before_boundary",
        "data_span_days": span / 86400000, "test_span_days": (cutoff_ms - test_start) / 86400000,
        "train_count": len(train), "calibration_count": len(calibration), "test_count": len(test),
        "train_ids_sha256": digest([r["source_sha256"] for r in train]),
        "calibration_ids_sha256": digest([r["source_sha256"] for r in calibration]),
        "test_ids_sha256": digest([r["source_sha256"] for r in test]), "folds": folds,
        "calibration": metrics(calibration, model, radius=radius),
        "test": metrics(test, model, radius=radius, total=sum(r["decision_time_ms"] >= test_start for r in samples)),
        "execution_authority": False, "profitability_proven": False,
        "limitations": ["Cross-symbol and serial dependence; counts are not IID effective sample sizes.",
            "No economic field or historical outcome is used as a predictor.",
            "Costs are a frozen 10 USDT research proxy using the existing cost model, not actual PnL.",
            "24h turnover is an impact proxy, not executable depth.",
            "Final holdout evaluated once for this artifact; a new specification needs a new untouched holdout.",
            "A passing forecast report still requires reviewed promotion and new prospective PAPER profitability evidence."]}
    report["promotion_failures"] = promotion_failures(report)
    report["status"] = "PASS" if not report["promotion_failures"] else "INSUFFICIENT_OR_FAILED_VALIDATION"
    return {"producer_version": PRODUCER_VERSION, "horizon_seconds": HORIZON_SECONDS,
        "model": model, "uncertainty_radius_fraction": radius, "support_count": len(train),
        "training_window": {"start_ms": min(r["decision_time_ms"] for r in train),
            "end_ms": max(r["decision_time_ms"] for r in train),
            "labels_available_through_ms": max(r["label_available_at_ms"] for r in train),
            "source_sha256": source["source_sha256"]},
        "validation_provenance": {"calibration_start_ms": cal_start, "holdout_start_ms": test_start,
            "calibration_labels_available_through_ms": max(r["label_available_at_ms"] for r in calibration),
            "holdout_end_ms": cutoff_ms, "validated_at_ms": evaluated, "report_sha256": digest(report)},
        "validation": report, "published_at_ms": evaluated, "execution_authority": False}
