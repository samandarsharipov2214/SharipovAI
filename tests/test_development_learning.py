from __future__ import annotations

from datetime import datetime, timezone

from learning_engine import DevelopmentLearningService
from learning_engine.self_learning_supervisor import SelfLearningSupervisor
from storage import ProjectDatabase


def _service(tmp_path) -> DevelopmentLearningService:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'development-learning.sqlite3'}")
    return DevelopmentLearningService(database, feature_dimensions=64, memory_limit=100)


def _record(
    service: DevelopmentLearningService,
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
    validation = {
        "error_signature": signature,
        "normalized_error": normalized_error,
        "changed_files": changed_files,
        "checks": checks or {"targeted_tests": success},
    }
    if error_type:
        validation["error_type"] = error_type
    if module:
        validation["module"] = module
    if completed_at_ms is not None:
        validation["completed_at_ms"] = completed_at_ms
    return service.record_fix_outcome(
        fix_id,
        decision_id,
        success,
        result_sha if result_sha is not None else ("a" * 40 if success else ""),
        validation,
    )


def test_record_fix_outcome_is_idempotent_and_redacts_secrets(tmp_path) -> None:
    service = _service(tmp_path)
    validation = {
        "error_signature": "import-dashboard-001",
        "normalized_error": "ImportError: cannot import dashboard.app",
        "changed_files": ["dashboard/app.py", "tests/test_dashboard.py"],
        "api_key": "must-not-be-stored",
        "checks": {"targeted_tests": True, "security_guard": True},
    }

    first = service.record_fix_outcome("fix-1", "decision-1", True, "b" * 40, validation)
    second = service.record_fix_outcome("fix-1", "decision-1", True, "b" * 40, validation)

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert first["validation"]["api_key"] == "<redacted>"
    assert first["error_type"] == "ImportError"
    assert first["module"] == "dashboard"
    assert first["execution_authority"] is False


def test_few_shot_search_uses_exact_then_typed_module_then_cosine(tmp_path) -> None:
    service = _service(tmp_path)
    _record(
        service,
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
        fix_id="fix-cosine",
        decision_id="decision-cosine",
        signature="sig-stream",
        normalized_error="ConnectionError websocket order stream timeout reconnect failed",
        changed_files=["market_data/private_stream.py"],
        error_type="ConnectionError",
        module="market_data",
        result_sha="d" * 40,
    )
    _record(
        service,
        fix_id="fix-failed",
        decision_id="decision-failed",
        signature="sig-failed",
        normalized_error="TimeoutError websocket order stream timeout",
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
        "TimeoutError websocket order stream timeout reconnect failed",
        ["exchange_connector/private_stream.py"],
        limit=1,
    )

    assert exact["examples"][0]["fix_id"] == "fix-exact"
    assert exact["examples"][0]["match_strategy"] == "exact_signature"
    assert typed["examples"][0]["fix_id"] == "fix-typed"
    assert typed["examples"][0]["match_strategy"] == "error_type_module"
    assert cosine["examples"][0]["fix_id"] == "fix-cosine"
    assert cosine["examples"][0]["match_strategy"] == "cosine_similarity"
    assert all(example["fix_id"] != "fix-failed" for example in cosine["examples"])


def test_rebuild_memory_projection_tracks_successful_records(tmp_path) -> None:
    service = _service(tmp_path)

    empty = service.rebuild_memory_projection()
    same = service.rebuild_memory_projection()
    _record(
        service,
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
    service = _service(tmp_path)
    completed_at_ms = int(datetime(2026, 8, 5, 12, tzinfo=timezone.utc).timestamp() * 1000)
    now_ms = int(datetime(2026, 8, 10, 12, tzinfo=timezone.utc).timestamp() * 1000)
    _record(
        service,
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
