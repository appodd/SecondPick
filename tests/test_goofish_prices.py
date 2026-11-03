import json

import pytest

from shopping_agent.config import AppConfig
from shopping_agent.db import initialize, connect, create_research_task
from shopping_agent.goofish_prices import import_price_observations, candidate_price_history
from shopping_agent.goofish_pipeline import EvidenceJournal, price_recorder


def observation():
    return dict(keyword="手柄", task_name="monitor-1", run_id="native-second", round_id="round-1",
        snapshot_time="2026-10-20T09:00:00", item_id="123", title="手柄",
        price=399, price_display="399", link="https://www.goofish.com/item?id=123")


@pytest.fixture
def env(tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task = create_research_task(conn, "手柄", "手柄", "上海")
        other = create_research_task(conn, "其他", "其他", "上海")
    return config, task, other, tmp_path / "prices.jsonl"


def sync(env, records, task=None):
    config, task_id, _, path = env
    path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    return import_price_observations(config, path=path, task_id=task or task_id,
        keyword="手柄", source_task="monitor-1")


def test_round_identity_replay_scope_and_bounded_history(env):
    record = observation()
    first = sync(env, [record])
    assert first["imported"] == 1
    assert sync(env, [record])["duplicates"] == 1
    assert sync(env, [record], task=env[2])["imported"] == 1
    with connect(env[0].database_path) as conn:
        listing = conn.execute("SELECT listing_id FROM monitor_price_observations LIMIT 1").fetchone()[0]
        assert len(candidate_price_history(conn, listing, [first["run_id"]])) == 1
        assert candidate_price_history(conn, listing, []) == []
        assert conn.execute("SELECT count(*) FROM listing_snapshots").fetchone()[0] == 0
    records = [{**record, "round_id": f"round-{n}"} for n in range(2, 27)]
    last = sync(env, records)
    with connect(env[0].database_path) as conn:
        assert len(candidate_price_history(conn, listing, [last["run_id"]])) == 20


@pytest.mark.parametrize("field,value", [("price", True), ("price", float("nan")),
    ("price", -1), ("price", 1e13), ("snapshot_time", "yesterday"), ("round_id", ""),
    ("link", "https://evil.test/item?id=123"), ("item_id", "456"), ("title", [])])
def test_invalid_prices_do_not_create_evidence(env, field, value):
    assert sync(env, [{**observation(), field: value}])["invalid"] == 1
    with connect(env[0].database_path) as conn:
        assert conn.execute("SELECT count(*) FROM monitor_price_observations").fetchone()[0] == 0


def test_filter_and_partial_tail_can_be_replayed(env):
    assert sync(env, [{**observation(), "keyword": "其他"}])["out_of_scope"] == 1
    config, task, _, path = env
    path.write_text('{"unfinished":', encoding="utf-8")
    assert import_price_observations(config, path=path, task_id=task, keyword="手柄", source_task="monitor-1")["invalid"] == 1
    assert sync(env, [observation()])["imported"] == 1


def test_oversized_line_and_bad_json_do_not_hide_following_prices(env):
    from shopping_agent.goofish_import import MAX_LINE_BYTES
    config, task, _, path = env
    path.write_bytes(b"x" * (MAX_LINE_BYTES + 10) + b"\n[]\n" + json.dumps(observation()).encode() + b"\n")
    result = import_price_observations(config, path=path, task_id=task, keyword="手柄", source_task="monitor-1")
    assert result["invalid"] == 2 and result["imported"] == 1


def test_write_failure_rolls_back_price_batch(env, monkeypatch):
    import shopping_agent.goofish_prices as module
    original = module.upsert_listing
    calls = []
    def fail_second(*args):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("synthetic write failure")
        return original(*args)
    monkeypatch.setattr(module, "upsert_listing", fail_second)
    with pytest.raises(OSError):
        sync(env, [observation(), {**observation(), "round_id": "round-2"}])
    with connect(env[0].database_path) as conn:
        assert conn.execute("SELECT count(*) FROM monitor_price_observations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM search_runs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM listings").fetchone()[0] == 0


def test_price_adapter_preserves_native_call_and_drops_unapproved_fields(tmp_path):
    calls = []
    errors = []
    record = {**observation(), "cookies": "secret", "ai_analysis": "untrusted"}
    def native(**kwargs):
        calls.append(kwargs)
        return [record]
    path = tmp_path / "prices.jsonl"
    wrapped = price_recorder(native, EvidenceJournal(path), "parent-round", errors.append)
    assert wrapped(items=[1]) == [record]
    assert calls == [{"items": [1]}] and not errors
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["round_id"] == "parent-round"
    assert "secret" not in path.read_text() and "ai_analysis" not in stored
    class BrokenJournal:
        def write(self, _):
            raise OSError("private path")
    with pytest.raises(OSError):
        price_recorder(native, BrokenJournal(), "round", errors.append)(items=[])
    assert errors == ["engine_save_failed"]


def test_search_card_capture_precedes_price_filter_and_preserves_native_dedup_contract(tmp_path):
    cards = tmp_path / "cards.jsonl"
    prices = tmp_path / "prices.jsonl"
    errors, native_calls = [], []
    items = [{"商品ID": "123", "商品链接": "https://www.goofish.com/item?id=123",
        "商品标题": "无报价手柄", "当前售价": None, "发货地区": "上海", "卖家昵称": "来源昵称",
        "cookie": "must-not-store", "ai_analysis": "must-not-store"},
        {"商品ID": "124", "商品链接": "https://www.goofish.com/item?id=124",
         "商品标题": "有报价手柄", "当前售价": "399"}]
    seen = set()
    def native(**kwargs):
        # Cards must already be durable, and generator input is still available.
        assert len(cards.read_text(encoding="utf-8").splitlines()) == 2
        assert kwargs["items"] == items
        assert kwargs["seen_item_ids"] is seen
        native_calls.append(True)
        return []
    wrapped = price_recorder(native, EvidenceJournal(prices), "round-1", errors.append,
                             cards_journal=EvidenceJournal(cards))
    kwargs = dict(keyword="手柄", task_name="monitor-1", run_id="native-run",
                  snapshot_time="2026-10-20T09:00:00", seen_item_ids=seen)
    assert wrapped(items=iter(items), **kwargs) == []
    assert wrapped(items=iter(items), **kwargs) == []
    assert len(native_calls) == 2 and not errors
    rows = [json.loads(line) for line in cards.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and rows[0]["商品信息"]["当前售价"] is None
    assert rows[0]["商品信息"]["发货地区"] == "上海"
    assert rows[0]["_collection_stage"] == "search_card" and rows[0]["_source_round_id"] == "round-1"
    assert "must-not-store" not in cards.read_text()
    assert not prices.exists()


def test_native_price_failure_does_not_lose_saved_search_cards(tmp_path):
    path = tmp_path / "cards.jsonl"
    def native(**kwargs):
        raise RuntimeError("native price persistence failed")
    wrapped = price_recorder(native, EvidenceJournal(tmp_path / "prices.jsonl"), "round", lambda _: None,
                             cards_journal=EvidenceJournal(path))
    with pytest.raises(RuntimeError):
        wrapped(keyword="手柄", task_name="monitor", items=[{"商品ID": "123", "商品标题": "手柄"}])
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
