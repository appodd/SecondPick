import json

import pytest

from shopping_agent.config import AppConfig
from shopping_agent.db import connect, create_research_task, initialize
from shopping_agent.goofish_import import import_goofish_jsonl
from shopping_agent.goofish_prices import import_price_observations
from shopping_agent.goofish_journal import MAX_LINE_BYTES
from test_goofish_import import product


@pytest.fixture(params=["products", "prices"])
def journal(request, tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task_id = create_research_task(conn, "手柄", "NS2 Pro", "上海")
    path = tmp_path / "stream.jsonl"
    importer = import_goofish_jsonl if request.param == "products" else import_price_observations

    def record(number=123):
        if request.param == "products":
            return product(number)
        return dict(keyword="NS2 Pro", task_name="手柄监控", run_id="native", round_id="round-1",
                    snapshot_time="2026-10-20T09:00:00", item_id=str(number), title="手柄", price=399,
                    price_display="399", link=f"https://www.goofish.com/item?id={number}")

    def sync(**kwargs):
        return importer(config, path=path, task_id=kwargs.pop("task_id", task_id), keyword="NS2 Pro",
                        source_task=kwargs.pop("source_task", "手柄监控"), incremental=True, **kwargs)
    return config, path, record, sync, task_id, request.param


def encoded(record):
    return json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"


def test_checkpoint_recreation_append_and_no_history_reread(journal):
    config, path, record, sync, task_id, _ = journal
    first = encoded(record())
    path.write_bytes(first)
    assert sync()["imported"] == 1
    result = sync()
    assert result["bytes_read"] == 0 and result["duplicates"] == 0 and not result["has_more"]
    # A separate importer invocation uses only the appended suffix.
    second = encoded(record(124))
    with path.open("ab") as stream:
        stream.write(second)
    result = sync()
    assert result["imported"] == 1 and result["bytes_read"] == len(second)
    with connect(config.database_path) as conn:
        row = conn.execute("SELECT * FROM monitor_stream_checkpoints WHERE task_id=?", (task_id,)).fetchone()
        assert row["byte_offset"] == len(first + second)
        assert str(path) not in row["stream_key"]


def test_live_partial_json_and_utf8_tail_wait_for_newline(journal):
    config, path, record, sync, _, _ = journal
    data = encoded(record())
    cut = data.index("手柄".encode()) + 1  # Cut through a UTF-8 character.
    path.write_bytes(data[:cut])
    first = sync()
    assert first["imported"] == first["invalid"] == 0 and first["pending_tail"]
    with path.open("ab") as stream:
        stream.write(data[cut:-1])
    assert sync()["imported"] == 0  # Even complete JSON is not yet a committed line.
    with path.open("ab") as stream:
        stream.write(b"\n")
    last = sync()
    assert last["imported"] == 1 and not last["pending_tail"]
    assert sync()["bytes_read"] == 0


@pytest.mark.parametrize("mode", ["replace", "truncate", "rewrite-boundary"])
def test_file_changes_reset_cursor_without_losing_records(journal, mode):
    _, path, record, sync, _, _ = journal
    old = encoded(record())
    path.write_bytes(old + encoded(record(125)) if mode == "truncate" else old)
    sync()
    new = encoded(record(124))
    if mode == "replace":
        replacement = path.with_suffix(".new")
        replacement.write_bytes(old + new)
        replacement.replace(path)
        expected_duplicates = 1
    elif mode == "truncate":
        path.write_bytes(new)
        expected_duplicates = 0
    else:
        # Same inode, at least the previous size, changed checked boundary.
        path.write_bytes(new + b"\n" * len(old))
        expected_duplicates = 0
    result = sync()
    assert result["imported"] == 1 and result["duplicates"] == expected_duplicates


def test_transaction_failure_does_not_advance_checkpoint(journal, monkeypatch):
    config, path, record, sync, _, kind = journal
    module_name = "shopping_agent.goofish_import" if kind == "products" else "shopping_agent.goofish_prices"
    import importlib
    module = importlib.import_module(module_name)
    path.write_bytes(encoded(record()) + encoded(record(124)))
    original = module.upsert_listing
    calls = []
    def fail(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("synthetic failure")
        return original(*args)
    monkeypatch.setattr(module, "upsert_listing", fail)
    with pytest.raises(RuntimeError):
        sync()
    with connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM monitor_stream_checkpoints").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM search_runs").fetchone()[0] == 0
    monkeypatch.setattr(module, "upsert_listing", original)
    assert sync()["imported"] == 2


def test_batch_limit_and_scope_specific_checkpoints(journal, monkeypatch):
    import shopping_agent.goofish_journal as module
    config, path, record, sync, _, _ = journal
    monkeypatch.setattr(module, "MAX_BATCH_LINES", 2)
    path.write_bytes(b"".join(encoded(record(n)) for n in range(100, 105)))
    first, second, third = sync(), sync(), sync()
    assert [r["imported"] for r in (first, second, third)] == [2, 2, 1]
    assert first["has_more"] and second["has_more"] and not third["has_more"]
    assert sync(source_task="其他监控")["out_of_scope"] == 2
    with connect(config.database_path) as conn:
        other = create_research_task(conn, "另一任务", "手柄", "上海")
    assert sync(task_id=other)["imported"] == 2


def test_oversize_discard_resumes_across_bounded_batches_and_tail_repair(journal, monkeypatch):
    import shopping_agent.goofish_journal as module
    _, path, record, sync, _, _ = journal
    monkeypatch.setattr(module, "MAX_BATCH_BYTES", MAX_LINE_BYTES + 1)
    path.write_bytes(b"x" * (MAX_LINE_BYTES * 3))
    results = [sync(), sync(), sync()]
    assert sum(r["invalid"] for r in results) == 1
    assert results[-1]["pending_tail"]
    with path.open("ab") as stream:
        stream.write(b"\n" + encoded(record()))
    result = sync()
    assert result["imported"] == 1 and result["invalid"] == 0


def test_failure_after_checkpoint_write_rolls_back_rows_and_cursor_together(journal, monkeypatch):
    import shopping_agent.goofish_journal as module
    config, path, record, sync, _, _ = journal
    path.write_bytes(encoded(record()))
    original = module.JournalBatch.save
    def fail_after_save(self):
        original(self)
        raise RuntimeError("commit not reached")
    monkeypatch.setattr(module.JournalBatch, "save", fail_after_save)
    with pytest.raises(RuntimeError):
        sync()
    with connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM monitor_stream_checkpoints").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM search_runs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM listings").fetchone()[0] == 0
    monkeypatch.setattr(module.JournalBatch, "save", original)
    assert sync()["imported"] == 1


def test_concurrent_readers_serialize_rows_and_checkpoint(journal):
    from concurrent.futures import ThreadPoolExecutor
    _, path, record, sync, _, _ = journal
    path.write_bytes(b"".join(encoded(record(n)) for n in range(100, 120)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sync(), range(2)))
    assert sum(row["imported"] for row in results) == 20
    assert sum(row["duplicates"] for row in results) == 0
    assert sorted(row["bytes_read"] for row in results)[0] == 0


def test_busy_database_defers_without_checkpoint_and_can_retry(journal):
    import sqlite3
    import time
    config, path, record, sync, _, _ = journal
    path.write_bytes(encoded(record()))
    with connect(config.database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            sync()
        assert time.monotonic() - started < 2
        assert conn.execute("SELECT count(*) FROM monitor_stream_checkpoints").fetchone()[0] == 0
    assert sync()["imported"] == 1
