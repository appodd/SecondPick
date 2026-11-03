import json

import pytest

from shopping_agent.candidate_context import build_candidate_index
from shopping_agent.config import AppConfig
from shopping_agent.db import connect, create_research_task, initialize
from shopping_agent.goofish_import import import_goofish_jsonl, MAX_LINE_BYTES


def product(number=123, **changes):
    record = {"搜索关键字": "NS2 Pro", "任务名称": "手柄监控", "爬取时间": "2026-10-20T09:00:00",
              "商品信息": {"商品ID": str(number), "商品链接": f"https://www.goofish.com/item?id={number}&spm=tracking",
                       "商品标题": "NS2 Pro 手柄", "当前售价": "399", "发货地区": "上海", "卖家昵称": "个人卖家自称"},
              "ai_analysis": {"is_recommended": True, "reason": "已验证全原装"},
              "卖家信息": {"AI总结": "已确认个人身份"}}
    record.update(changes)
    return record


@pytest.fixture
def env(tmp_path):
    config = AppConfig(database_path=tmp_path / "test.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task_id = create_research_task(conn, "手柄", "个人闲置优先", "上海")
    path = tmp_path / "results.jsonl"
    return config, task_id, path


def write(path, records):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


def sync(env, **kwargs):
    config, task_id, path = env
    return import_goofish_jsonl(config, path=path, task_id=task_id, keyword="NS2 Pro", **kwargs)


def test_bulk_sync_flows_into_existing_candidate_context_without_ai_claims(env):
    config, task_id, path = env
    write(path, [product(n) for n in range(1000, 1405)])
    assert sync(env)["imported"] == 405
    index = build_candidate_index(config, task_id=task_id)
    assert index["deduplicated_count"] == 405
    assert all(not c["has_detail"] for c in index["candidates"])
    assert all(c["external_source"]["independently_verified"] is False for c in index["candidates"])
    assert index["candidates"][0]["external_source"]["source_observed_at"] == "2026-10-20T09:00:00"
    assert all(c["url"].endswith(str(n)) for c, n in zip(index["candidates"], range(1000, 1405)))
    with connect(config.database_path) as conn:
        row = conn.execute("SELECT * FROM listing_snapshots LIMIT 1").fetchone()
        assert row["source_type"] == "external_monitor"
        assert row["description"] is None
        assert row["seller_realname_verified"] is None
        assert conn.execute("SELECT count(*) FROM research_assessments").fetchone()[0] == 0
        assert conn.execute("SELECT observed_at FROM monitor_import_records LIMIT 1").fetchone()[0] == "2026-10-20T09:00:00"


def test_repeated_sync_is_idempotent_but_price_change_appends_snapshot(env):
    config, task_id, path = env
    first = product()
    second = product()
    second["商品信息"]["当前售价"] = "369"
    write(path, [first])
    assert sync(env)["imported"] == 1
    assert sync(env) == dict(imported=0, duplicates=1, invalid=0, out_of_scope=0, run_id=None)
    write(path, [first, second])
    assert sync(env)["imported"] == 1
    index = build_candidate_index(config, task_id=task_id)
    assert index["deduplicated_count"] == 1
    assert index["candidates"][0]["price_text"] == "369"
    with connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM listing_snapshots").fetchone()[0] == 2


def test_allowlisted_profile_appends_evidence_without_converting_seller_claims(env):
    config, task_id, path = env
    card = product()
    enriched = product(卖家信息={"卖家芝麻信用": "优秀", "卖家注册时长": "来闲鱼1年",
                            "作为卖家的好评率": "99%", "卖家在售/已售商品数": 20,
                            "seller_realname_verified": True, "AI总结": "must-not-import",
                            "cookies": "must-not-import"})
    write(path, [card, enriched])
    assert sync(env)["imported"] == 2
    assert sync(env)["duplicates"] == 2
    index = build_candidate_index(config, task_id=task_id)
    assert index["deduplicated_count"] == 1
    profile = index["candidates"][0]["external_source"]["seller_profile"]
    assert profile["卖家注册时长"] == "来闲鱼1年"
    assert profile["卖家在售/已售商品数"] == "20"
    from shopping_agent.web.services import WorkbenchService
    workbench = WorkbenchService(config)
    page = workbench.get_candidates(task_id, limit=20, cursor=None)
    assert page.candidates[0].external_source.seller_profile == profile
    evidence = workbench.get_listing_evidence(task_id, page.candidates[0].listing_id)
    assert evidence.external_source.independently_verified is False
    with connect(config.database_path) as conn:
        latest = conn.execute("SELECT * FROM listing_snapshots ORDER BY id DESC LIMIT 1").fetchone()
        assert latest["seller_realname_verified"] is None
        assert latest["seller_registered_days"] is None
        assert latest["seller_sold_count"] is None
        assert "must-not-import" not in conn.execute("SELECT seller_json FROM monitor_import_records ORDER BY snapshot_id DESC LIMIT 1").fetchone()[0]


def test_bad_optional_profile_field_does_not_discard_valid_product(env):
    _, _, path = env
    write(path, [product(卖家信息={"卖家昵称": ["invalid"], "作为卖家的好评率": "99%"})])
    result = sync(env)
    assert result["imported"] == 1 and result["invalid"] == 0


def test_explicit_keyword_and_source_task_scope(env):
    _, _, path = env
    write(path, [product(), product(124, 搜索关键字="其他"), product(125, 任务名称="其他任务")])
    result = sync(env, source_task="手柄监控")
    assert (result["imported"], result["out_of_scope"]) == (1, 2)


def test_same_source_can_be_attached_to_another_task_without_shared_runs(env):
    config, task_id, path = env
    write(path, [product()])
    first = sync(env)
    with connect(config.database_path) as conn:
        other = create_research_task(conn, "另一任务", "其他标准", "北京")
    second = import_goofish_jsonl(config, path=path, task_id=other, keyword="NS2 Pro")
    assert second["imported"] == 1
    assert first["run_id"] != second["run_id"]
    with connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM listings").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM task_runs WHERE task_id=?", (task_id,)).fetchone()[0] == 1


@pytest.mark.parametrize("url", ["https://evil.test/item?id=123", "https://www.goofish.com/item?id=123&id=124",
                                "https://www.goofish.com:bad/item?id=123", "https://user@www.goofish.com/item?id=123",
                                "https://www.goofish.com/item?id=999"])
def test_invalid_or_mismatched_product_url_is_not_imported(env, url):
    _, _, path = env
    record = product()
    record["商品信息"]["商品链接"] = url
    write(path, [record])
    result = sync(env)
    assert result["invalid"] == 1 and result["run_id"] is None


def test_incomplete_tail_can_be_read_again_after_writer_finishes(env):
    _, _, path = env
    text = json.dumps(product(), ensure_ascii=False)
    path.write_text(text[:30], encoding="utf-8")
    assert sync(env)["invalid"] == 1
    path.write_text(text + "\n", encoding="utf-8")
    assert sync(env)["imported"] == 1


def test_oversized_or_non_object_lines_do_not_hide_following_records(env):
    _, _, path = env
    path.write_bytes(b"x" * (MAX_LINE_BYTES + 20) + b"\n[]\n" + json.dumps(product()).encode() + b"\n")
    result = sync(env)
    assert result["invalid"] == 2 and result["imported"] == 1


def test_unknown_task_does_not_create_runs(env):
    config, _, path = env
    write(path, [product()])
    with pytest.raises(ValueError, match="task"):
        import_goofish_jsonl(config, path=path, task_id=999, keyword="NS2 Pro")
    with connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM search_runs").fetchone()[0] == 0


def test_write_failure_rolls_back_entire_batch(env, monkeypatch):
    import shopping_agent.goofish_import as module
    config, _, path = env
    write(path, [product(123), product(124)])
    original = module.add_listing_snapshot
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("injected write failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "add_listing_snapshot", fail_second)
    with pytest.raises(RuntimeError):
        sync(env)
    with connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM listings").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM monitor_import_records").fetchone()[0] == 0


def search_card(number=123, round_id="round-1", **changes):
    return product(number, _collection_stage="search_card", _source_round_id=round_id, **changes)


def test_bulk_search_cards_include_unpriced_items_and_reach_workbench(env):
    from shopping_agent.web.services import WorkbenchService
    config, task_id, path = env
    records = [search_card(n) for n in range(1000, 1405)]
    records[0]["商品信息"]["当前售价"] = None
    records[0]["卖家信息"] = {"卖家芝麻信用": "不可从卡片推断", "作为卖家的好评率": "100%"}
    write(path, records)
    assert sync(env)["imported"] == 405
    assert sync(env)["duplicates"] == 405
    index = build_candidate_index(config, task_id=task_id)
    assert index["deduplicated_count"] == 405
    assert all(not item["has_detail"] for item in index["candidates"])
    first = index["candidates"][0]
    assert first["price_value"] is None
    assert first["external_source"]["evidence_stage"] == "search_card"
    assert first["external_source"]["seller_profile"] == {}
    assert first["external_source"]["source_round_id"] == "round-1"
    workbench = WorkbenchService(config)
    page = workbench.get_candidates(task_id, limit=20, cursor=None)
    assert page.deduplicated_count == 405
    evidence = workbench.get_listing_evidence(task_id, first["listing_id"])
    assert evidence.external_source.evidence_stage == "search_card"
    assert evidence.external_source.independently_verified is False


@pytest.mark.parametrize("same_file", [False, True])
@pytest.mark.parametrize("full_first", [False, True])
def test_search_cards_never_replace_product_and_seller_evidence(env, same_file, full_first):
    from shopping_agent.candidate_context import build_candidate_evidence
    config, task_id, path = env
    full = product(卖家信息={"作为卖家的好评率": "99%"})
    full["商品信息"]["商品标题"] = "详情阶段标题"
    card = search_card()
    card["商品信息"]["商品标题"] = "搜索阶段标题"
    card["商品信息"]["当前售价"] = "359"
    records = [full, card] if full_first else [card, full]
    if same_file:
        write(path, records)
        assert sync(env)["imported"] == 2
    else:
        for record in records:
            write(path, [record])
            assert sync(env)["imported"] == 1
    candidate = build_candidate_index(config, task_id=task_id)["candidates"][0]
    assert candidate["title"] == "详情阶段标题" and candidate["price_text"] == "399"
    assert candidate["external_source"]["evidence_stage"] == "product_record"
    assert candidate["external_source"]["seller_profile"] == {"作为卖家的好评率": "99%"}
    evidence = build_candidate_evidence(config, task_id=task_id, listing_ids=[candidate["listing_id"]])
    assert evidence["candidates"][0]["title"] == "详情阶段标题"
    with connect(config.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM listing_snapshots").fetchone()[0] == 2


def test_search_card_rounds_append_without_inflating_candidate_count_or_crossing_tasks(env):
    config, task_id, path = env
    write(path, [search_card()])
    first = sync(env)
    second_card = search_card(round_id="round-2")
    second_card["商品信息"]["当前售价"] = "359"
    write(path, [second_card])
    second = sync(env)
    assert second["imported"] == 1 and second["run_id"] != first["run_id"]
    index = build_candidate_index(config, task_id=task_id)
    assert index["deduplicated_count"] == 1
    assert index["candidates"][0]["price_text"] == "359"
    with connect(config.database_path) as conn:
        other = create_research_task(conn, "另一任务", "其他标准", "北京")
    write(path, [product()])
    import_goofish_jsonl(config, path=path, task_id=other, keyword="NS2 Pro")
    assert build_candidate_index(config, task_id=other)["candidates"][0]["external_source"]["evidence_stage"] == "product_record"
    assert build_candidate_index(config, task_id=task_id)["candidates"][0]["external_source"]["evidence_stage"] == "search_card"


@pytest.mark.parametrize("changes", [{"_source_round_id": ""}, {"_source_round_id": []},
    {"爬取时间": "not-a-time"}, {"爬取时间": None}])
def test_search_card_requires_round_and_source_time(env, changes):
    _, _, path = env
    write(path, [{**search_card(), **changes}])
    assert sync(env)["invalid"] == 1


def test_migration_keeps_existing_records_and_fingerprints(env):
    config, task_id, path = env
    write(path, [product()])
    assert sync(env)["imported"] == 1
    with connect(config.database_path) as conn:
        before = dict(conn.execute("SELECT * FROM monitor_import_records").fetchone())
        conn.execute("ALTER TABLE monitor_import_records DROP COLUMN evidence_stage")
        conn.execute("ALTER TABLE monitor_import_records DROP COLUMN source_round_id")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        after = dict(conn.execute("SELECT * FROM monitor_import_records").fetchone())
    assert after == {**before, "evidence_stage": "product_record", "source_round_id": None}
    assert sync(env)["duplicates"] == 1
    assert build_candidate_index(config, task_id=task_id)["candidates"][0]["external_source"]["evidence_stage"] == "product_record"


def test_monitor_provenance_and_price_changes_invalidate_only_their_candidate(env):
    from shopping_agent.assessment import evidence_state
    from shopping_agent.goofish_prices import import_price_observations
    config, task_id, path = env
    write(path, [product(123), product(124)])
    sync(env)
    with connect(config.database_path) as conn:
        listing_id = conn.execute("SELECT id FROM listings WHERE url LIKE '%id=123'").fetchone()[0]
        before_guard, before = evidence_state(conn, task_id)
    prices = path.with_name("prices.jsonl")
    write(prices, [dict(keyword="NS2 Pro", task_name="手柄监控", run_id="native", round_id="round-1",
        snapshot_time="2026-10-20T09:30:00", item_id="123", title="手柄", price=359,
        price_display="359", link="https://www.goofish.com/item?id=123")])
    import_price_observations(config, path=prices, task_id=task_id, keyword="NS2 Pro", source_task="手柄监控")
    with connect(config.database_path) as conn:
        after_guard, after = evidence_state(conn, task_id)
        assert after_guard != before_guard and after[str(listing_id)] != before[str(listing_id)]
        assert all(value == before[key] for key, value in after.items() if key != str(listing_id))
        conn.execute("UPDATE monitor_import_records SET observed_at='2026-10-20T10:00:00' WHERE snapshot_id IN (SELECT id FROM listing_snapshots WHERE listing_id=?)", (listing_id,))
        _, changed = evidence_state(conn, task_id)
        assert changed[str(listing_id)] != after[str(listing_id)]
        assert all(value == after[key] for key, value in changed.items() if key != str(listing_id))


def test_replaying_prices_does_not_change_evidence_or_listing_seen_time(env, monkeypatch):
    from shopping_agent.assessment import evidence_state
    import shopping_agent.db as db
    from shopping_agent.goofish_prices import import_price_observations
    config, task_id, path = env
    write(path, [product()])
    sync(env)
    prices = path.with_name("prices.jsonl")
    write(prices, [dict(keyword="NS2 Pro", task_name="手柄监控", run_id="native", round_id="round-1",
        snapshot_time="2026-10-20T09:30:00", item_id="123", title="手柄", price=359,
        price_display="359", link="https://www.goofish.com/item?id=123")])
    import_price_observations(config, path=prices, task_id=task_id, keyword="NS2 Pro", source_task="手柄监控")
    with connect(config.database_path) as conn:
        before = evidence_state(conn, task_id)
    monkeypatch.setattr(db, "utc_now_iso", lambda: "2099-01-01T00:00:00+00:00")
    result = import_price_observations(config, path=prices, task_id=task_id, keyword="NS2 Pro", source_task="手柄监控")
    assert result["duplicates"] == 1 and result["imported"] == 0
    with connect(config.database_path) as conn:
        assert evidence_state(conn, task_id) == before
