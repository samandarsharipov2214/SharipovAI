from __future__ import annotations

from dashboard.security_guard import LoginAttemptGuard


def test_login_attempt_guard_locks_after_failed_attempts(tmp_path) -> None:
    guard = LoginAttemptGuard(tmp_path / "login_attempts.json", max_failed_attempts=3, lock_seconds=60)

    first = guard.record_failure("Pilot", now=100)
    second = guard.record_failure("pilot", now=101)
    third = guard.record_failure("pilot", now=102)

    assert first["status"] == "failed"
    assert second["status"] == "failed"
    assert third["status"] == "locked"
    assert guard.is_locked("PILOT", now=103) is True
    assert guard.seconds_left("pilot", now=120) == 42


def test_login_attempt_guard_unlocks_after_time(tmp_path) -> None:
    guard = LoginAttemptGuard(tmp_path / "login_attempts.json", max_failed_attempts=2, lock_seconds=30)

    guard.record_failure("pilot", now=200)
    guard.record_failure("pilot", now=201)

    assert guard.is_locked("pilot", now=220) is True
    assert guard.is_locked("pilot", now=232) is False


def test_login_attempt_guard_success_resets_failures(tmp_path) -> None:
    guard = LoginAttemptGuard(tmp_path / "login_attempts.json", max_failed_attempts=3, lock_seconds=60)

    guard.record_failure("pilot", now=300)
    guard.record_failure("pilot", now=301)
    guard.record_success("pilot")
    result = guard.record_failure("pilot", now=302)

    assert result["status"] == "failed"
    assert result["failed_attempts"] == 1
    assert guard.is_locked("pilot", now=303) is False
