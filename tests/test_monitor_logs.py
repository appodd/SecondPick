import io
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from shopping_agent.config import AppConfig
from shopping_agent.db import connect, create_research_task
from shopping_agent.monitor_engine import run_process, EngineError
from shopping_agent.monitor_logs import ConsoleLog, monitor_directory, read_console, scrub, MAX_ROUNDS, MAX_LINE
from shopping_agent.monitoring import MonitorStore


@pytest.fixture
def env(tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite")
    config.monitor_engine.work_dir = tmp_path / "engine"
    store = MonitorStore(config)
    with connect(config.database_path) as conn:
        task = create_research_task(conn, "task", "task", "city")
        other = create_research_task(conn, "other", "other", "city")
    monitor = store.create(task, keyword="probe", confirmed=True)
    directory = monitor_directory(config, monitor["id"]) / "logs"
    return config, task, other, monitor["id"], directory


def test_credentials_queries_and_terminal_controls_are_removed():
    assert "sensitive" not in scrub("Cookie: sensitive")
    assert "sensitive" not in scrub('  "access_token": "sensitive"')
    assert "sensitive" not in scrub("Bearer sensitive")
    text = scrub("\x1b[31mitem https://user:pass@example.test/item?id=123&token=sensitive\x1b[0m")
    assert "user:pass" not in text and "sensitive" not in text and "\x1b" not in text
    # Sensitive field marker omits the complete line, not just one guessed value.
    assert scrub(text) == text
    assert scrub("debug known-session-value", ["known-session-value"]) == "debug [REDACTED]"
    assert "13800138000" not in scrub("phone 13800138000")
    url = scrub("https://example.test/item?id=123")
    assert scrub(url) == url and "123" not in url


def test_tail_pages_are_stable_and_task_scoped(env):
    config, task, other, monitor, directory = env
    log = ConsoleLog(directory, "a" * 32)
    for i in range(7): log.write(f"line-{i}")
    log.close()
    page = read_console(config, task, monitor, limit=3)
    assert [r["text"] for r in page["items"]] == ["line-4", "line-5", "line-6"]
    assert page["has_more"] and page["round_id"] == "a" * 32
    older = read_console(config, task, monitor, round_id=page["round_id"], before=page["next_before"], limit=3)
    assert [r["text"] for r in older["items"]] == ["line-1", "line-2", "line-3"]
    with pytest.raises(ValueError): read_console(config, other, monitor)
    with pytest.raises(ValueError): read_console(config, task, monitor, round_id="../../credentials")


def test_retention_removes_only_generated_log_files(env):
    config, task, _, monitor, directory = env
    directory.mkdir(parents=True)
    (directory / "keep.txt").write_text("not a generated log")
    evidence = directory.parent / "products.jsonl"
    evidence.write_text("preserved evidence")
    for number in range(MAX_ROUNDS + 2):
        log = ConsoleLog(directory, f"{number:032x}")
        log.write(str(number)); log.close()
        os.utime(directory / f"{number:032x}.jsonl", (100 + number, 100 + number))
    assert len(list(directory.glob("*.jsonl"))) == MAX_ROUNDS
    assert evidence.read_text() == "preserved evidence" and (directory / "keep.txt").is_file()
    assert len(read_console(config, task, monitor)["rounds"]) == MAX_ROUNDS


def test_overlong_output_is_omitted_before_partial_secret_can_escape(env):
    config, task, _, monitor, directory = env
    log = ConsoleLog(directory, "a" * 32)
    log.drain(io.BytesIO(("z" * (MAX_LINE + 500) + "\nnormal 中文\nlast").encode()))
    log.close()
    texts = [r["text"] for r in read_console(config, task, monitor)["items"]]
    assert texts == ["[oversized output line omitted]", "normal 中文", "last"]


def test_size_limit_keeps_draining_and_collection_does_not_block(env):
    config, task, _, monitor, directory = env
    log = ConsoleLog(directory, "a" * 32, max_bytes=1024)
    run_process([sys.executable, "-u", "-c", "import sys; [print('progress'*100) for _ in range(10000)]; print('stderr',file=sys.stderr)"],
                cwd=directory, env=os.environ.copy(), stop=threading.Event(), timeout=10, output_log=log)
    log.close()
    assert log.capped and (directory / ("a" * 32 + ".jsonl")).stat().st_size < 1300
    assert "log size limit reached" in read_console(config, task, monitor)["items"][-1]["text"]


def test_live_stdout_and_stderr_are_visible_before_child_exit_then_cancel(env):
    config, task, _, monitor, directory = env
    log = ConsoleLog(directory, "a" * 32, secrets=["known-cookie-value"])
    stop, errors = threading.Event(), []
    def run():
        try:
            run_process([sys.executable, "-u", "-c", "import sys,time; print('page 1 known-cookie-value'); print('waiting 5 seconds',file=sys.stderr); time.sleep(30)"],
                cwd=directory, env=os.environ.copy(), stop=stop, timeout=15, output_log=log)
        except EngineError as exc: errors.append(exc.code)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            rows = read_console(config, task, monitor)["items"]
            if len(rows) >= 2: break
            time.sleep(.03)
        assert worker.is_alive() and len(rows) == 2
        assert "known-cookie-value" not in json.dumps(rows)
        assert "waiting 5 seconds" in rows[1]["text"]
    finally:
        stop.set(); worker.join(timeout=8); log.close()
    assert not worker.is_alive() and errors == ["cancelled"]
    assert not any(t.name == "monitor-console" and t.is_alive() for t in threading.enumerate())


def test_historical_run_without_captured_output_returns_empty_page(env):
    config, task, _, monitor, _ = env
    page = read_console(config, task, monitor)
    assert page["items"] == [] and page["round_id"] is None
