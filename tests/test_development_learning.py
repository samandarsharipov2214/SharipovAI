from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from learning_engine import DevelopmentLearningService
from learning_engine.self_learning_supervisor import SelfLearningSupervisor
from storage import ProjectDatabase

_BASE_SHA = "1" * 40


def _service(tmp_path) -> tuple[DevelopmentLearningService, ProjectDatabase]:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'development-learning.sqlite3'}")
    service = DevelopmentLearningService(database, feature_dimensions=256, memory_limit=100)
    return service, database


def _record(
    service: DevelopmentLearningService,
    database: ProjectDatabase,
    *,
    fix_id: str,
    decision_id: str,
    signature: str,
    normalized_error: str,
    changed_files: list[str],
    success: bool = True,
    result_sha: str | None = None,
    completed_at_ms: int | None = None,
    error_type: str = "",
    module: str = "",
    checks: dict[str, bool] | None = None,
):
    applied_sha = result_sha if result_sha is not None else ("a" * 40 if success else "")
    patch = (
        f"diff --git a/{changed_files[0]} b/{changed_files[0]}\n"
        f"--- a/{changed_files[0]}\n"
        f"+++ b/{changed_files[0]}\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    timestamp = completed_at_ms or 1_700_000_000_000
    database.record_agent_fix(
        fix_id=fix_id,
        error_signature=signature,
        failure_class=error_type or None,
        patch=patch,
        success=success,
        source="unit_test",
        base_sha=_BASE_SHA,
        applied_sha=applied_sha or None,
        test_evidence={"checks": checks or {"targeted_tests": success}},
        metadata={
            "normalized_error": normalized_error,
            "changed_files": changed_files,
            "module": module,
        },
        created_at_ms=timestamp,
    )
    database.record_agent_decision(
        decision_id=decision_id,
        fix_id=fix_id,
        kind="verify",
        status="applied" if success else "failed",
        base_sha=_BASE_SHA,
        target_branch="main",
        patch_sha256=patch_sha256,
        security_verdict="allow",
        actor="unit_test",
        rationale="Deterministic development-learning fixture.",
        metadata={"validation_required": True},
        created_at_ms=timestamp,
    )
    validation = {
        "error_signature": signature,
        "normalized_error": normalized_error,
        "changed_files": changed_files,
        "checks": checks or {"targeted_tests": success},
        "completed_at_ms": timestamp,
    }
    if error_type:
        validation["error_type"] = error_type
    if module:
        validation["module"] = module
    return service.record_fix_outcome(
        fix_id,
        decision_id,
        success,
        applied_sha,
        validation,
    )


def test_record_fix_outcome_is_idempotent_and_redacts_secrets(tmp_path) -> None:
    service, database = _service(tmp_path)
    patch = "diff --git a/dashboard/app.py b/dashboard/app.py\n--- a/dashboard/app.py\n+++ b/dashboard/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    database.record_agent_fix(
        fix_id="fix-1",
        error_signature="import-dashboard-001",
        failure_class="ImportError",
        patch=patch,
        success=True,
        source="unit_test",
        base_sha=_BASE_SHA,
        applied_sha="b" * 40,
        test_evidence={"pytest": "passed"},
        metadata={"changed_files": ["dashboard/app.py", "tests/test_dashboard.py"]},
        created_at_ms=1_700_000_000_000,
    )
    database.record_agent_decision(
        decision_id="decision-1",
        fix_id="fix-1",
        kind="verify",
        status="applied",
        base_sha=_BASE_SHA,
        target_branch="main",
        patch_sha256=patch_sha256,
        security_verdict="allow",
        actor="unit_test",
        rationale="Validated fixture.",
        created_at_ms=1_700_000_000_000,
    )
    validation = {
        "error_signature": "import-dashboard-001",
        "normalized_error": "ImportError: cannot import dashboard.app",
        "changed_files": ["dashboard/app.py", "tests/test_dashboard.py"],
        "api_key": "must-not-be-stored",
        "checks": {"targeted_tests": True, "security_guard": True},
        "completed_at_ms": 1_700_000_000_000,
    }

    first = service.record_fix_outcome("fix-1", "decision-1", True, "b" * 40, validation)
    second = service.record_fix_outcome("fix-1", "decision-1", True, "b" * 40, validation)
    events = database.list_agent_decision_events("decision-1")

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert first["validation"]["api_key"] == "<redacted>"
    assert first["error_type"] == "ImportError"
    assert first["module"] == "dashboard"
    assert first["execution_authority"] is False
    assert [event["event_type"] for event in events] == ["fix_outcome_recorded"]
    assert events[0]["payload"]["validation"]["api_key"] == "<redacted>"


def test_record_fix_outcome_requires_linked_immutable_evidence(tmp_path) -> None:
    service, database = _service(tmp_path)

    with pytest.raises(KeyError, match="unknown fix_id"):
        service.record_fix_outcome("missing", "missing", False, "", {})

    _record(
        service,
        database,
        fix_id="fix-linked",
        decision_id="decision-linked",
        signature="linked-signature",
        normalized_error="RuntimeError: linked evidence",
        changed_files=["learning_engine/service.py"],
    )
    with pytest.raises(ValueError, match="already recorded"):
        service.record_fix_outcome(
            "fix-linked",
            "decision-linked",
            True,
            "a" * 40,
            {
                "error_signature": "linked-signature",
                "normalized_error": "RuntimeError: different validation",
                "changed_files": ["learning_engine/service.py"],
            },
        )


def test_few_shot_search_uses_exact_then_typed_module_then_cosine(tmp_path) -> None:
    service, database = _service(tmp_path)
    _record(
        service,
        database,
        fix_id="fix-exact",
        decision_id="decision-exact",
        signature="sig-exact",
        normalized_error="TypeError: invalid dashboard response payload",
        changed_files=["dashboard/routes.py"],
        error_type="TypeError",
        module="dashboard",
    )
    _record(
        service,
        database,
        fix_id="fix-typed",
        decision_id="decision-typed",
        signature="sig-typed",
        normalized_error="ImportError: dashboard widget import failed",
        changed_files=["dashboard/widgets.py"],
        error_type="ImportError",
        module="dashboard",
        result_sha="c" * 40,
    )
    _record(
        service,
        database,
        fix_id="fix-cosine",
        decision_id="decision-cosine",
        signature="sig-stream",
        normalized_error="ConnectionError websocket private order stream timeout reconnect failed",
        changed_files=["market_data/private_stream.py"],
        error_type="ConnectionError",
        module="market_data",
        result_sha="d" * 40,
    )
    _record(
        service,
        database,
        fix_id="fix-failed",
        decision_id="decision-failed",
        signature="sig-failed",
        normalized_error="TimeoutError websocket private order stream timeout reconnect failed",
        changed_files=["exchange_connector/private_stream.py"],
        success=False,
    )

    exact = service.build_few_shot_pack(
        "sig-exact",
        "TypeError: invalid dashboard response payload",
        ["dashboard/routes.py"],
        limit=1,
    )
    typed = service.build_few_shot_pack(
        "new-signature",
        "ImportError: another dashboard widget import failed",
        ["dashboard/another_widget.py"],
        limit=1,
    )
    cosine = service.build_few_shot_pack(
        "unseen-stream-signature",
        "TimeoutError websocket private order stream timeout reconnect failed",
        ["exchange_connector/private_stream.py"],
        limit=1,
    )

    assert exact["examples"][0]["fix_id"] == "fix-exact"
    assert exact["examples"][0]["match_strategy"] == "exact_signature"
    assert exact["examples"][0]["output"]["patch"]
    assert typed["examples"][0]["fix_id"] == "fix-typed"
    assert typed["examples"][0]["match_strategy"] == "error_type_module"
    assert cosine["examples"][0]["fix_id"] == "fix-cosine"
    assert cosine["examples"][0]["match_strategy"] == "cosine_similarity"
    assert all(example["fix_id"] != "fix-failed" for example in cosine["examples"])


def test_rebuild_memory_projection_tracks_successful_records(tmp_path) -> None:
    service, database = _service(tmp_path)

    empty = service.rebuild_memory_projection()
    same = service.rebuild_memory_projection()
    _record(
        service,
        database,
        fix_id="fix-projection",
        decision_id="decision-projection",
        signature="projection-signature",
        normalized_error="RuntimeError: projection failed",
        changed_files=["learning_engine/development_learning.py"],
    )
    changed = service.rebuild_memory_projection()

    assert empty["successful_fix_count"] == 0
    assert empty["idempotent"] is False
    assert same["idempotent"] is True
    assert changed["successful_fix_count"] == 1
    assert changed["idempotent"] is False
    assert changed["source_sha256"] != empty["source_sha256"]


def test_weekly_process_review_creates_manual_process_proposal(tmp_path) -> None:
    service, database = _service(tmp_path)
    completed_at_ms = int(datetime(2026, 8, 5, 12, tzinfo=timezone.utc).timestamp() * 1000)
    now_ms = int(datetime(2026, 8, 10, 12, tzinfo=timezone.utc).timestamp() * 1000)
    _record(
        service,
        database,
        fix_id="fix-week-1",
        decision_id="decision-week-1",
        signature="repeated-signature",
        normalized_error="ImportError: module alpha missing",
        changed_files=["alpha/service.py"],
        completed_at_ms=completed_at_ms,
        checks={"targeted_tests": True, "security_guard": True},
    )
    _record(
        service,
        database,
        fix_id="fix-week-2",
        decision_id="decision-week-2",
        signature="repeated-signature",
        normalized_error="ImportError: module alpha still missing",
        changed_files=["alpha/service.py"],
        completed_at_ms=completed_at_ms + 1,
        checks={"targeted_tests": True, "security_guard": True},
        result_sha="e" * 40,
    )
    _record(
        service,
        database,
        fix_id="fix-week-3",
        decision_id="decision-week-3",
        signature="failed-signature",
        normalized_error="AssertionError: alpha regression",
        changed_files=["alpha/service.py"],
        completed_at_ms=completed_at_ms + 2,
        success=False,
        checks={"targeted_tests": False, "security_guard": True},
    )

    proposal = service.run_weekly_process_review(now_ms)
    repeated = service.run_weekly_process_review(now_ms + 60_000)

    assert proposal["proposal_type"] == "process_optimization"
    assert proposal["status"] == "proposed"
    assert proposal["metrics"]["total_fixes"] == 3
    assert proposal["metrics"]["successful_fixes"] == 2
    assert proposal["metrics"]["failed_fixes"] == 1
    assert proposal["metrics"]["repeated_error_signature_count"] == 1
    assert proposal["metrics"]["failed_validation_checks"] == {"targeted_tests": 1}
    assert proposal["requires_manual_approval"] is True
    assert proposal["execution_authority"] is False
    assert proposal["automatic_code_application"] is False
    assert proposal["runtime_flags_changed"] is False
    assert repeated["idempotent"] is True
    assert repeated["proposal_id"] == proposal["proposal_id"]


def test_self_learning_supervisor_runs_development_review(tmp_path, monkeypatch) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'supervisor.sqlite3'}")

    class DevelopmentStub:
        def __init__(self) -> None:
            self.called_with = 0

        def run_weekly_process_review(self, now_ms: int):
            self.called_with = now_ms
            return {
                "status": "proposed",
                "proposal_type": "process_optimization",
                "proposal_id": "process_optimization_20260803",
                "requires_manual_approval": True,
                "execution_authority": False,
                "automatic_code_application": False,
                "runtime_flags_changed": False,
            }

    development = DevelopmentStub()
    monkeypatch.delenv("SELF_LEARNING_SOURCE_EXPERIMENT_ID", raising=False)
    supervisor = SelfLearningSupervisor(database, development_learning=development)
    now_ms = int(datetime(2026, 8, 10, 12, tzinfo=timezone.utc).timestamp() * 1000)

    state = supervisor.run_once(now_ms=now_ms)

    assert development.called_with == now_ms
    assert state["status"] == "ok"
    assert state["development_learning"]["proposal_type"] == "process_optimization"
    assert state["development_learning"]["requires_manual_approval"] is True
    assert state["execution_authority"] is False
