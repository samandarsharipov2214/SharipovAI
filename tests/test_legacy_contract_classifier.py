from __future__ import annotations

from pathlib import Path

from scripts.legacy_contract_classifier import build_report, classify, parse_junit


def test_unknown_failure_fails_closed_as_regression() -> None:
    category, reason = classify("tests.test_new_contract::test_unknown", "AssertionError: 1 != 2")
    assert category == "regression"
    assert "fail closed" in reason


def test_exact_web2_version_contract_is_stale_test() -> None:
    category, _ = classify(
        "tests.test_web2_system_status_v11::test_assets",
        "assert 'system_status_v11.css?v=11' in index",
    )
    assert category == "stale_test"


def test_shared_immutable_state_is_environment_contamination() -> None:
    category, _ = classify(
        "config.tests.test_council_authorized_paper_loop::test_position",
        "storage.project_database.VersionConflict: expected 0, current 1",
    )
    assert category == "environment_contamination"


def test_junit_report_preserves_all_failures(tmp_path: Path) -> None:
    junit = tmp_path / "pytest.xml"
    junit.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<testsuites><testsuite failures='3' tests='3'>
  <testcase classname='tests.test_web2_static_shell' name='test_asset'>
    <failure message="assert '?v=5' in index">trace</failure>
  </testcase>
  <testcase classname='tests.test_state' name='test_isolation'>
    <failure message='VersionConflict: expected 0, current 1'>trace</failure>
  </testcase>
  <testcase classname='tests.test_runtime' name='test_regression'>
    <failure message='AssertionError: unsafe state'>trace</failure>
  </testcase>
</testsuite></testsuites>""",
        encoding="utf-8",
    )
    records = parse_junit(junit)
    report = build_report(records, source=str(junit))
    assert report["total_failures"] == 3
    assert report["truthful_gate_required"] is True
    assert report["counts"] == {
        "regression": 1,
        "stale_test": 1,
        "environment_contamination": 1,
    }
