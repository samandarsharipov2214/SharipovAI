"""Regression contracts for the one-shot Final OOS handoff."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import trading_core.alpha_final_oos as alpha_final_oos
from trading_core.alpha_final_oos import PreFinalValidationSnapshot


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_canonical_runner_never_replays_pre_final_after_claim() -> None:
    runner = Path("tools/run_preregistered_alpha_experiment.py")
    module = ast.parse(runner.read_text(encoding="utf-8"))
    main = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    named_calls = [
        call
        for call in ast.walk(main)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    ]
    names = [call.func.id for call in named_calls]

    assert "run_preregistered_alpha_validation" not in names
    assert names.count("run_preregistered_pre_final_validation") == 1
    assert names.count("claim_final_oos") == 1
    assert names.count("run_prepared_final_oos_validation") == 1

    lines = {
        call.func.id: call.lineno
        for call in named_calls
        if call.func.id in {
            "run_preregistered_pre_final_validation",
            "claim_final_oos",
            "run_prepared_final_oos_validation",
        }
    }
    assert lines["run_preregistered_pre_final_validation"] < lines["claim_final_oos"]
    assert lines["claim_final_oos"] < lines["run_prepared_final_oos_validation"]


def test_prepare_freezes_the_manifest_digest_validated_before_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"dataset":"v1"}', encoding="utf-8")
    expected = _digest(manifest_path)
    loader = SimpleNamespace(manifest_path=manifest_path)
    experiment = SimpleNamespace(dataset_manifest_sha256=expected)
    calls = 0

    def fake_pre_final(*args, **kwargs):
        nonlocal calls
        calls += 1
        return 17, ()

    monkeypatch.setattr(
        alpha_final_oos,
        "run_preregistered_pre_final_validation",
        fake_pre_final,
    )

    prepared = alpha_final_oos.prepare_preregistered_final_oos(
        loader,  # type: ignore[arg-type]
        experiment,  # type: ignore[arg-type]
        lambda: object(),  # type: ignore[return-value]
        candidate_name="candidate",
        current_git_sha="a" * 40,
        backtest_config=object(),  # type: ignore[arg-type]
        criteria=object(),  # type: ignore[arg-type]
    )

    assert calls == 1
    assert prepared.train_event_count == 17
    assert prepared.validation_windows == ()
    assert prepared.validated_manifest_sha256 == expected


def test_prepare_fails_if_manifest_changes_during_pre_final_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"dataset":"v1"}', encoding="utf-8")
    expected = _digest(manifest_path)
    loader = SimpleNamespace(manifest_path=manifest_path)
    experiment = SimpleNamespace(dataset_manifest_sha256=expected)

    def mutate_manifest(*args, **kwargs):
        manifest_path.write_text('{"dataset":"tampered"}', encoding="utf-8")
        return 1, ()

    monkeypatch.setattr(
        alpha_final_oos,
        "run_preregistered_pre_final_validation",
        mutate_manifest,
    )

    with pytest.raises(RuntimeError, match="manifest changed during pre-final"):
        alpha_final_oos.prepare_preregistered_final_oos(
            loader,  # type: ignore[arg-type]
            experiment,  # type: ignore[arg-type]
            lambda: object(),  # type: ignore[return-value]
            candidate_name="candidate",
            current_git_sha="a" * 40,
            backtest_config=object(),  # type: ignore[arg-type]
            criteria=object(),  # type: ignore[arg-type]
        )


def test_final_oos_fails_closed_if_manifest_changed_after_claim(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"dataset":"v1"}', encoding="utf-8")
    expected = _digest(manifest_path)
    prepared = PreFinalValidationSnapshot(
        train_event_count=1,
        validation_windows=(),
        validated_manifest_sha256=expected,
    )
    experiment = SimpleNamespace(dataset_manifest_sha256=expected)
    loader = SimpleNamespace(manifest_path=manifest_path)

    manifest_path.write_text('{"dataset":"tampered"}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="manifest changed after pre-final"):
        alpha_final_oos.run_prepared_final_oos_validation(
            loader,  # type: ignore[arg-type]
            experiment,  # type: ignore[arg-type]
            lambda: object(),  # type: ignore[return-value]
            prepared,
            candidate_name="candidate",
            current_git_sha="a" * 40,
            backtest_config=object(),  # type: ignore[arg-type]
            criteria=object(),  # type: ignore[arg-type]
        )
