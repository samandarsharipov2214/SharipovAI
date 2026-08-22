from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "web2" / "app" / "page.tsx"


def test_web2_numeric_evidence_parser_rejects_null_boolean_and_empty_values():
    source = PAGE.read_text(encoding="utf-8")

    assert "if (typeof value === 'number') return Number.isFinite(value) ? value : null;" in source
    assert "if (typeof value !== 'string') return null;" in source
    assert "const text = value.trim();" in source
    assert "if (!text) return null;" in source
    assert "const number = Number(text);" in source
    assert "const number = Number(value);" not in source


def test_web2_numeric_evidence_parser_keeps_finite_numbers_and_numeric_strings_only():
    source = PAGE.read_text(encoding="utf-8")

    assert "return Number.isFinite(number) ? number : null;" in source
    assert "finiteNumber(account?.total_equity)" in source
    assert "finiteNumber(account?.total_available_balance)" in source
    assert "finiteNumber(summary.active)" in source
    assert "finiteNumber(summary.total_bots)" in source
