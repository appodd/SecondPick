"""Compatibility tests for upstream policy with portable state persistence."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from shopping_agent.goofish_failure_guard import FailureGuard


def test_threshold_daily_notification_and_expiry(tmp_path):
    guard = FailureGuard(path=str(tmp_path / "guard.json"))
    now = datetime(2026, 10, 20, 12)
    assert guard.record_failure("task", "one", now=now)["should_notify"] is False
    assert guard.record_failure("task", "two", now=now)["should_notify"] is False
    opened = guard.record_failure("task", "three", now=now)
    assert opened["consecutive_failures"] == 3 and opened["opened_circuit"]
    assert opened["paused_until"] == now + timedelta(hours=24)
    assert guard.should_skip_start("task", now=now).skip
    assert not guard.should_skip_start("task", now=now).should_notify
    next_day = now + timedelta(hours=13)
    assert guard.should_skip_start("task", now=next_day).should_notify
    assert not guard.should_skip_start("task", now=next_day).should_notify
    assert not guard.should_skip_start("task", now=now + timedelta(hours=25)).skip


def test_cookie_update_resets_failure_history_and_task_scopes(tmp_path):
    state = tmp_path / "state.json"
    state.write_text("{}")
    guard = FailureGuard(path=str(tmp_path / "guard.json"), threshold=1)
    now = datetime(2026, 10, 20, 12)
    guard.record_failure("one", "login", cookie_path=str(state), now=now)
    assert guard.should_skip_start("one", cookie_path=str(state), now=now).skip
    assert not guard.should_skip_start("two", cookie_path=str(state), now=now).skip
    previous = state.stat().st_mtime
    os.utime(state, (previous + 2, previous + 2))
    decision = guard.should_skip_start("one", cookie_path=str(state), now=now)
    assert not decision.skip and decision.reason == "cookie_updated"
    assert decision.consecutive_failures == 0


def test_immediate_configuration_failure_and_success_reset(tmp_path):
    guard = FailureGuard(path=str(tmp_path / "guard.json"))
    result = guard.record_failure("task", "missing state", min_failures_to_pause=1)
    assert result["opened_circuit"]
    guard.record_success("task")
    assert not guard.should_skip_start("task").skip
    assert guard.record_failure("task", "again")["consecutive_failures"] == 1


def test_data_file_is_closed_before_atomic_replace_and_errors_propagate(tmp_path, monkeypatch):
    path = tmp_path / "guard.json"
    guard = FailureGuard(path=str(path))
    guard.record_failure("task", "first")
    original = os.replace

    def denied(*args):
        raise PermissionError("synthetic denied")

    monkeypatch.setattr(os, "replace", denied)
    with pytest.raises(PermissionError):
        guard.record_failure("task", "not saved")
    assert json.loads(path.read_text())["tasks"]["task"]["consecutive_failures"] == 1
    monkeypatch.setattr(os, "replace", original)
    assert guard.record_failure("task", "second")["consecutive_failures"] == 2


def test_multiple_real_processes_do_not_lose_failure_updates(tmp_path):
    path = tmp_path / "guard.json"
    code = "from shopping_agent.goofish_failure_guard import FailureGuard; import sys; g=FailureGuard(path=sys.argv[1],threshold=1000); [g.record_failure('same-task','network') for _ in range(20)]"
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    processes = [subprocess.Popen([sys.executable, "-c", code, str(path)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs) for _ in range(4)]
    try:
        assert [p.wait(timeout=20) for p in processes] == [0, 0, 0, 0]
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
            p.wait(timeout=5)
    assert json.loads(path.read_text())["tasks"]["same-task"]["consecutive_failures"] == 80


def test_corrupt_state_is_preserved_and_reinitialized(tmp_path):
    path = tmp_path / "guard.json"
    path.write_text("broken")
    guard = FailureGuard(path=str(path))
    assert guard.record_failure("task", "network")["consecutive_failures"] == 1
    assert len(list(tmp_path.glob("guard.json.corrupt.*"))) == 1


def test_lock_failure_does_not_silently_write_unlocked(tmp_path, monkeypatch):
    import shopping_agent.goofish_failure_guard as module
    primitive = __import__("msvcrt" if os.name == "nt" else "fcntl")

    def unavailable(*args):
        raise OSError("synthetic busy lock")

    monkeypatch.setattr(primitive, "locking" if os.name == "nt" else "flock", unavailable)
    monkeypatch.setattr(module, "_LOCK_TIMEOUT_SECONDS", .02)
    path = tmp_path / "guard.json"
    with pytest.raises((OSError, TimeoutError)):
        FailureGuard(path=str(path)).record_failure("task", "network")
    assert not path.exists()
