"""Candidate validity without weakening atomic whole-review publication guards."""
import json

import pytest

from shopping_agent.assessment import evidence_state
from shopping_agent.conversation_service import ConversationService
from shopping_agent.db import connect, initialize, create_search_run, add_listing_snapshot, attach_run_to_task
from shopping_agent.research_history import assessment_detail
from shopping_agent.tasks import update_task_preferences
from test_history_review import ReviewRunner, add_noise, saved
from test_structured_assessments import seed_phones, scripted_assessment
from test_web_preference_updates import ready_service, run_turn, ScriptedRunner, UPDATED


@pytest.fixture
def reviewed(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    assert run_turn(service, task_id, ReviewRunner(), "重评历史候选").state == "completed"
    return service, task_id


def mutate(conn, kind, tmp_path, listing_id=2):
    run_id = conn.execute("SELECT run_id FROM task_runs LIMIT 1").fetchone()[0]
    if kind in {"price", "description", "seller"}:
        column = {"price": "price_text", "description": "description", "seller": "seller_good_rate"}[kind]
        conn.execute(f"UPDATE listing_snapshots SET {column}=? WHERE listing_id=?", ("changed", listing_id))
    elif kind in {"detail", "detail_file"}:
        path = tmp_path / "detail.txt"
        path.write_text("卖家称维修史已经补充", encoding="utf-8")
        conn.execute("INSERT INTO detail_snapshots(listing_id,run_id,url,text_path,created_at) VALUES (?,?,?,?,?)",
                     (listing_id, run_id, "https://example.test/detail", str(path), "fixture"))
        return path
    elif kind == "seller_items":
        conn.execute("INSERT INTO seller_items(seller_listing_id,source_run_id,title,collected_at) VALUES (?,?,?,?)",
                     (listing_id, run_id, "其他公开商品", "fixture"))
    elif kind in {"media", "ocr"}:
        media_id = conn.execute("INSERT INTO media_assets(listing_id,media_type,local_path,created_at) VALUES (?,?,?,?)",
                                (listing_id, "product_image", "not-opened.png", "fixture")).lastrowid
        if kind == "ocr":
            conn.execute("INSERT INTO ocr_results(media_asset_id,ocr_text,created_at) VALUES (?,?,?)", (media_id, "92%", "fixture"))


@pytest.mark.parametrize("kind", ["price", "description", "seller", "detail", "seller_items", "media", "ocr"])
def test_only_changed_candidate_is_stale_in_page_and_direct_reference(reviewed, tmp_path, kind):
    service, task_id = reviewed
    original = saved(service, task_id)
    with connect(service.config.database_path) as conn:
        mutate(conn, kind, tmp_path)
    current = saved(ConversationService(service.config), task_id)
    batch = current["assessment_batches"][0]
    assert batch["candidate_stale"] == {"1": False, "2": True, "3": False, "4": False}
    assert batch["stale"]
    assert batch["result"] == original["assessment_batches"][0]["result"]
    assert batch["evidence_signature"] != batch["validity_signature"]
    assert current["comparisons"][0]["stale"] and current["reviews"][0]["stale"]
    with connect(service.config.database_path) as conn:
        detail = assessment_detail(conn, task_id, batch["id"])
        assert detail["candidate_stale"] == batch["candidate_stale"]
        assert "dependencies_json" not in detail and "input_json" not in detail
    # Even the UNKNOWN judgment with no cited refs depends on absence of detail.
    assert batch["result"]["assessments"][1]["judgments"][-1]["status"] == "UNKNOWN"


@pytest.mark.parametrize("change", ["edit", "delete"])
def test_saved_detail_file_change_invalidates_only_its_candidate(tmp_path, change):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    with connect(service.config.database_path) as conn:
        path = mutate(conn, "detail_file", tmp_path)
    assert run_turn(service, task_id, ReviewRunner()).state == "completed"
    if change == "edit":
        path.write_text("卖家改口：换过屏幕", encoding="utf-8")
    else:
        path.unlink()
    assert saved(service, task_id)["assessment_batches"][0]["candidate_stale"] == {"1": False, "2": True, "3": False, "4": False}


def test_retry_after_unrelated_change_reuses_unchanged_batch_after_restart(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    add_noise(service, task_id, 19)  # 23 candidates
    assert run_turn(service, task_id, ReviewRunner()).state == "completed"
    before = saved(service, task_id)
    assert len(before["assessment_batches"]) == 2
    # Change the second batch only; the complete first batch and its proposals survive.
    with connect(service.config.database_path) as conn:
        mutate(conn, "price", tmp_path, listing_id=23)
    stale = saved(service, task_id)
    assert [b["stale"] for b in stale["assessment_batches"]] == [False, True]
    runner = ReviewRunner()
    restarted = ConversationService(service.config)
    assert run_turn(restarted, task_id, runner, "继续重评").state == "completed"
    batch_inputs = [r for r in runner.requests if r.phase == "review_batch"]
    assert len(batch_inputs) == 1 and batch_inputs[0].allowed_listing_ids == frozenset({23})
    after = saved(restarted, task_id)
    assert len(after["assessment_batches"]) == 3
    assert after["comparisons"][-1]["coverage"]["assessed_count"] == 23
    assert not after["comparisons"][-1]["stale"]
    assert any(c["assessment_id"] == before["assessment_batches"][0]["id"] for c in after["comparisons"][-1]["result"]["ranked_candidates"])


def test_new_candidate_keeps_old_judgments_but_invalidates_complete_comparison(reviewed):
    service, task_id = reviewed
    add_noise(service, task_id, 1)
    current = saved(service, task_id)
    assert not current["assessment_batches"][0]["stale"]
    assert current["comparisons"][0]["stale"]
    runner = ReviewRunner()
    assert run_turn(service, task_id, runner).state == "completed"
    assert [r.allowed_listing_ids for r in runner.requests if r.phase == "review_batch"] == [frozenset({5})]
    assert saved(service, task_id)["comparisons"][-1]["coverage"]["scope_count"] == 5


def test_removed_candidate_invalidates_own_judgment_and_prevents_batch_reuse(reviewed):
    service, task_id = reviewed
    with connect(service.config.database_path) as conn:
        conn.execute("DELETE FROM listing_snapshots WHERE listing_id=2")
    assert saved(service, task_id)["assessment_batches"][0]["candidate_stale"] == {"1": False, "2": True, "3": False, "4": False}
    runner = ReviewRunner()
    operation = run_turn(service, task_id, runner)
    # The old shortlist's removed candidate has no current assessment. Publishing
    # a comparison must fail safely rather than inventing an exit reference.
    assert operation.state == "failed"
    assert not [r for r in runner.requests if r.phase == "review_batch"]
    assert len(saved(service, task_id)["comparisons"]) == 1


def test_unattached_run_evidence_does_not_change_candidate_dependencies(reviewed):
    service, task_id = reviewed
    with connect(service.config.database_path) as conn:
        before = evidence_state(conn, task_id)
        run = create_search_run(conn, goal="other", city="上海")
        add_listing_snapshot(conn, listing_id=2, run_id=run, title="未归属详情", description="not in task")
        assert evidence_state(conn, task_id) == before
        attach_run_to_task(conn, task_id=task_id, run_id=run)
    assert saved(service, task_id)["assessment_batches"][0]["candidate_stale"] == {"1": False, "2": True, "3": False, "4": False}


def test_preference_change_still_invalidates_every_candidate(reviewed):
    service, task_id = reviewed
    update_task_preferences(service.config, task_id, "新要求", UPDATED)
    batch = saved(service, task_id)["assessment_batches"][0]
    assert all(batch["candidate_stale"].values()) and batch["stale"]


@pytest.mark.parametrize("mode", ["legacy", "chat"])
def test_unbound_old_or_chat_assessments_use_global_fallback(tmp_path, mode):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    runner = ReviewRunner() if mode == "legacy" else ScriptedRunner(scripted_assessment)
    assert run_turn(service, task_id, runner).state == "completed"
    with connect(service.config.database_path) as conn:
        if mode == "legacy":
            conn.execute("UPDATE research_assessments SET dependencies_json='{}'")
        snapshot = conn.execute("SELECT input_json,result_json FROM research_assessments").fetchone()
        original = tuple(snapshot)
        conn.execute("ALTER TABLE research_assessments DROP COLUMN dependencies_json")
    initialize(service.config.database_path)
    initialize(service.config.database_path)
    with connect(service.config.database_path) as conn:
        assert tuple(conn.execute("SELECT input_json,result_json FROM research_assessments").fetchone()) == original
        assert json.loads(conn.execute("SELECT dependencies_json FROM research_assessments").fetchone()[0]) == {}
    add_noise(service, task_id, 1)
    assert all(saved(service, task_id)["assessment_batches"][0]["candidate_stale"].values())


@pytest.mark.parametrize("contract", ["prompt", "schema", "runtime"])
def test_changed_generation_contract_prevents_reuse(reviewed, contract):
    service, task_id = reviewed
    with connect(service.config.database_path) as conn:
        if contract == "runtime":
            snapshot = json.loads(conn.execute("SELECT input_json FROM research_assessments").fetchone()[0])
            snapshot["runtime_config"]["adapter"] = "different"
            conn.execute("UPDATE research_assessments SET input_json=?", (json.dumps(snapshot),))
        else:
            column = "prompt_version" if contract == "prompt" else "schema_version"
            conn.execute(f"UPDATE research_assessments SET {column}='older'")
    runner = ReviewRunner()
    assert run_turn(service, task_id, runner).state == "completed"
    assert len([r for r in runner.requests if r.phase == "review_batch"]) == 1
