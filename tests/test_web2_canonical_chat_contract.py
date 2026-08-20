from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "web2" / "app" / "page.tsx"
GEMINI_API = Path(__file__).resolve().parents[1] / "dashboard" / "gemini_chat_api.py"


def test_web2_uses_the_canonical_authenticated_chat_route():
    page = PAGE.read_text(encoding="utf-8")
    backend = GEMINI_API.read_text(encoding="utf-8")

    assert "apiUrl('/api/ai/chat')" in page
    assert "'/api/chat/message'" not in page
    assert '@app.post("/api/ai/chat"' in backend


def test_web2_matches_the_canonical_chat_request_and_response_contract():
    page = PAGE.read_text(encoding="utf-8")
    backend = GEMINI_API.read_text(encoding="utf-8")

    assert "body:JSON.stringify({message:text, history})" in page
    assert "chat.slice(-20)" in page
    assert "role: item.from === 'ai' ? 'assistant' : 'user'" in page
    assert "String(out.text ?? '').trim()" in page
    assert "if (!r.ok)" in page
    assert "class GeminiChatRequest" in backend
    assert "history: list[ChatHistoryMessage]" in backend
    assert "class GeminiChatResponse" in backend
    assert "text: str" in backend


def test_web2_does_not_seed_fake_assistant_history():
    page = PAGE.read_text(encoding="utf-8")

    assert "useState<ChatMessage[]>([])" in page
    assert "Я онлайн. Могу объяснить" not in page
    assert "История этого сеанса пока пуста" in page
