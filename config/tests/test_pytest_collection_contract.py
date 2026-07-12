from pathlib import Path


def test_root_regression_tests_are_part_of_full_suite() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert '"tests",' in text
    assert '"dashboard/tests",' in text
    assert '"exchange_connector/tests",' in text
