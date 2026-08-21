from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web2" / "app" / "page.tsx"


def _source() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_chat_submit_is_guarded_against_parallel_requests() -> None:
    source = _source()
    assert "const chatInFlight = useRef(false);" in source
    assert "if (!text || chatInFlight.current) return;" in source
    assert "chatInFlight.current = true;" in source
    assert "chatInFlight.current = false;" in source


def test_chat_controls_expose_pending_state() -> None:
    source = _source()
    assert "const [chatPending, setChatPending] = useState(false);" in source
    assert "pending={chatPending}" in source
    assert "disabled={pending}" in source
    assert 'aria-busy={pending}' in source
