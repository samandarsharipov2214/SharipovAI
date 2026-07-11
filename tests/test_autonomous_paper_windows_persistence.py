from __future__ import annotations

import json
import os

from autonomous_trading.loop import AutonomousPaperLoop


class DummyStream:
    symbols: tuple[str, ...] = ()

    def snapshot(self) -> dict[str, object]:
        return {"verified": False, "quotes": {}}


def test_persist_retries_windows_permission_error(tmp_path, monkeypatch) -> None:
    state_file = tmp_path / "autonomous_paper.json"
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(state_file))
    loop = AutonomousPaperLoop(DummyStream())

    real_replace = os.replace
    calls = 0

    def flaky_replace(source, target):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError(5, "simulated Windows sharing violation")
        return real_replace(source, target)

    monkeypatch.setattr("autonomous_trading.loop.os.replace", flaky_replace)
    monkeypatch.setattr("autonomous_trading.loop.time.sleep", lambda _seconds: None)

    loop._persist()

    assert calls == 3
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["mode"] == "autonomous_paper"
    assert not list(tmp_path.glob("*.tmp"))
