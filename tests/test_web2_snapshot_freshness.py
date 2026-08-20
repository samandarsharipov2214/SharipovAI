from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "web2" / "app" / "page.tsx"


def test_web2_preserves_last_good_snapshot_on_partial_refresh_failure():
    source = PAGE.read_text(encoding="utf-8")

    assert "if (results[0].status === 'fulfilled') setHealth" in source
    assert "if (results[1].status === 'fulfilled') setAccount" in source
    assert "if (results[2].status === 'fulfilled') setBots" in source
    assert "if (results[3].status === 'fulfilled') setNews" in source
    assert "? results[0].value as Json : null" not in source
    assert "? results[1].value as Json : null" not in source
    assert "? results[2].value as Json : null" not in source
    assert "? results[3].value as Json : null" not in source


def test_web2_marks_failed_sources_stale_and_uses_one_bounded_polling_loop():
    source = PAGE.read_text(encoding="utf-8")

    assert "lastSuccessAt" in source
    assert "stale:true" in source
    assert "Последнее подтверждённое значение сохранено, но обновление не удалось" in source
    assert "window.setInterval(() => { void load(); }, 30_000)" in source
    assert "window.clearInterval(timer)" in source
    assert "if (loadInFlight.current) return" in source
