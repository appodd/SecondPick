import json

import pytest

from shopping_agent.db import connect
from shopping_agent.goofish_status import WorkerStatus, read_worker_status
from shopping_agent.monitor_diagnostics import MonitorDiagnostics, diagnostic_events, retention_status
from shopping_agent.monitoring import MonitorStore
from shopping_agent.config import AppConfig


@pytest.fixture
def env(tmp_path):
    from shopping_agent.db import create_research_task
    store = MonitorStore(AppConfig(database_path=tmp_path / "db.sqlite"))
    with connect(store.config.database_path) as conn:
        task = create_research_task(conn, "手柄", "NS2 Pro", "上海")
        other = create_research_task(conn, "其他", "其他", "上海")
    monitor = store.create(task, keyword="NS2 Pro", confirmed=True)
    return store, monitor, other, tmp_path


def test_event_allowlist_and_cursor_pages_are_task_scoped(env):
    store, monitor, other, _ = env
    log = MonitorDiagnostics(store.config, monitor, "a" * 32)
    assert log.emit("process", "round_started", imported=3, cookie="secret", url="https://private.test",
                    invalid=True, duplicates=-1)
    log.emit("sync", "sync_progress", imported=4)
    page = diagnostic_events(store.config, monitor["task_id"], monitor["id"], limit=1)
    assert page["has_more"] and page["items"][0]["counts"] == {"imported": 4}
    last = diagnostic_events(store.config, monitor["task_id"], monitor["id"], limit=1, before_id=page["next_before_id"])
    assert not last["has_more"] and last["items"][0]["counts"] == {"imported": 3}
    assert "secret" not in json.dumps(last) and "private.test" not in json.dumps(last)
    with pytest.raises(ValueError, match="当前任务"):
        diagnostic_events(store.config, other, monitor["id"])
    with pytest.raises(ValueError):
        log.emit("private path", "round_started")
    with pytest.raises(ValueError):
        log.emit("process", "raw exception with secret")
    with pytest.raises(ValueError):
        diagnostic_events(store.config, monitor["task_id"], monitor["id"], limit=101)


def test_retention_removes_only_disposable_diagnostic_events(env, monkeypatch):
    import shopping_agent.monitor_diagnostics as module
    from shopping_agent.goofish_import import import_goofish_jsonl
    from test_goofish_import import product
    store, monitor, _, directory = env
    path = directory / "products.jsonl"
    data = json.dumps(product(), ensure_ascii=False).encode() + b"\n"
    path.write_bytes(data)
    import_goofish_jsonl(store.config, path=path, task_id=monitor["task_id"], keyword="NS2 Pro", incremental=True)
    log = MonitorDiagnostics(store.config, monitor, "a" * 32)
    log.emit("process", "round_started")
    with connect(store.config.database_path) as conn:
        conn.execute("UPDATE monitor_diagnostic_events SET created_at='2000-01-01T00:00:00+00:00'")
    monkeypatch.setattr(module, "MAX_EVENTS", 3)
    for n in range(5):
        log.emit("sync", "sync_progress", imported=n)
    page = diagnostic_events(store.config, monitor["task_id"], monitor["id"])
    assert [item["counts"]["imported"] for item in page["items"]] == [4, 3, 2]
    with connect(store.config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM monitor_diagnostic_events").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM monitor_import_records").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM listing_snapshots").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM monitor_stream_checkpoints").fetchone()[0] == 1
    monkeypatch.setattr(module, "EVIDENCE_WARNING_BYTES", 1)
    status = retention_status(directory)
    assert status["warning"] and status["policy"] == "preserve_evidence"
    assert path.read_bytes() == data


def test_busy_diagnostics_do_not_raise_or_change_evidence(env):
    store, monitor, _, _ = env
    log = MonitorDiagnostics(store.config, monitor, "a" * 32)
    with connect(store.config.database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        assert log.emit("sync", "sync_progress", imported=3) is False
    assert not log.available
    assert log.emit("finished", "round_finished")


def test_worker_status_rejects_wrong_round_unknown_fields_and_oversize(env):
    _, _, _, directory = env
    status = WorkerStatus(directory)
    status.round_id = "a" * 32
    status.update("engine_import", "engine_dependencies_missing")
    assert read_worker_status(directory, "a" * 32) == dict(phase="engine_import", error_code="engine_dependencies_missing")
    assert read_worker_status(directory, "b" * 32) is None
    path = directory / "status.json"
    path.write_text(json.dumps(dict(phase="collecting", round_id="a" * 32, error_code=None,
                                   cookie="private", traceback="private")))
    assert read_worker_status(directory, "a" * 32) == dict(phase="collecting", error_code=None)
    path.write_text('{"phase":[],' + '"round_id":"' + "a" * 32 + '"}')
    assert read_worker_status(directory, "a" * 32) is None
    path.write_bytes(b"x" * 4097)
    assert read_worker_status(directory, "a" * 32) is None
