from pathlib import Path


WEB2_PAGE = Path(__file__).resolve().parents[1] / "web2" / "app" / "page.tsx"


def test_web2_does_not_claim_a_specific_user_without_canonical_identity() -> None:
    source = WEB2_PAGE.read_text(encoding="utf-8")

    assert "Привет, Самандар" not in source
    assert "?'SharipoAI':'Самандар'" not in source
    assert "Привет! 👋" in source
    assert "?'SharipoAI':'Пользователь'" in source
