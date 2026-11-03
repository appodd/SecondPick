"""Region intent regressions: local SQLite snapshots and a runtime double, no collection/AI."""
import pytest

from shopping_agent.candidate_pool import CandidatePoolOptions, build_candidate_pool
from shopping_agent.config import AppConfig
from shopping_agent.db import initialize, connect, create_search_run, upsert_listing, add_listing_snapshot
from shopping_agent.goal_plan import build_goal_plan
from shopping_agent.region_preference import region_preference, normalize_region_draft, region_instruction
from shopping_agent.tasks import create_task
from shopping_agent.research_assessment import build_research_assessment


@pytest.mark.parametrize("text,mode,city", [
    ("买二手 NS2 Pro 手柄", "none", None),
    ("原装优先，性能优先，成色好优先", "none", None),
    ("买手柄，上海优先", "preferred", "上海"),
    ("买手柄，只考虑上海自提", "restricted", "上海"),
    ("不限定上海", "none", None),
    ("不要求全新，但只考虑上海自提", "restricted", "上海"),
    ("仅限昆山市面交", "restricted", "昆山"),
    ("我在上海工作，买手柄不限地区", "none", None),
])
def test_explicit_intent_only(text, mode, city):
    preference = region_preference(text, legacy_city="上海")
    assert (preference["mode"], preference["city"]) == (mode, city)
    assert preference["legacy_city"] == "上海"
    assert preference["legacy_unverified"] == (mode == "none")


def test_soft_list_and_priority_wording_never_become_a_hard_restriction():
    assert region_preference(hard=["上海优先"])["mode"] == "preferred"
    assert region_preference(soft=["只考虑上海自提"])["mode"] == "preferred"
    assert region_preference(hard=["交易地区：上海"])["mode"] == "restricted"


@pytest.mark.parametrize("goal,mode", [("买手柄", "none"), ("买手柄，上海优先", "preferred"), ("买手柄，只考虑上海自提", "restricted")])
def test_goal_plans_do_not_invent_a_default_city(goal, mode):
    plan = build_goal_plan(goal)
    assert plan["region_preference"]["mode"] == mode
    assert plan["city"] == ("" if mode == "none" else "上海")
    assert all(not item["filters"].get("area") for item in plan["search_rounds"])
    assert not any("外地只作为价格参考" in question for question in plan["clarification_questions"])


def test_draft_does_not_invent_or_upgrade_city():
    payload = dict(title="手柄", goal="买手柄上海优先", budget=None, hard=["上海自提", "必须原装"], soft=[])
    neutral = normalize_region_draft(payload, "买手柄")
    assert neutral["goal"] == "买手柄" and neutral["hard"] == ["必须原装"] and neutral["soft"] == []
    soft = normalize_region_draft(payload, "买手柄，上海优先")
    assert soft["hard"] == ["必须原装"] and soft["soft"] == ["上海优先"]
    hard = normalize_region_draft(payload, "买手柄，只考虑上海自提")
    assert "只考虑上海自提" in hard["hard"]


def test_city_defaults_do_not_change_new_task_or_candidate_scores(tmp_path):
    config = AppConfig(default_city="上海", database_path=tmp_path / "test.sqlite")
    task = create_task(config, "手柄", "买手柄")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        assert conn.execute("SELECT city FROM research_tasks WHERE id=?", (task,)).fetchone()[0] == ""
        run = create_search_run(conn, "手柄", "上海")
        for index, city in enumerate(["上海", "广州"]):
            listing = upsert_listing(conn, "xianyu", f"https://www.goofish.com/item?id={index}")
            add_listing_snapshot(conn, listing, run, title="NS2 Pro 手柄", price_text="300", location=city)
    pool = build_candidate_pool(config, [run], CandidatePoolOptions(goal="买手柄"))
    candidates = pool["all_candidates"]
    assert len(candidates) == 2
    assert candidates[0]["tool_priority_score"] == candidates[1]["tool_priority_score"]
    assert not any(item["signals"]["target_city_hint"] for item in candidates)
    preferred = build_candidate_pool(config, [run], CandidatePoolOptions(goal="买手柄，上海优先"))
    assert len(preferred["all_candidates"]) == 2
    assert preferred["all_candidates"][0]["location"] == "上海"
    restricted = build_candidate_pool(config, [run], CandidatePoolOptions(goal="只考虑上海自提"))
    assert restricted["region_preference"]["mode"] == "restricted"
    # Region and self-pickup evidence is left for evaluation, never inferred from missing data.
    assert len(restricted["all_candidates"]) == 2
    explicit = create_task(config, "手柄", "买手柄", city="上海")
    with connect(config.database_path) as conn:
        saved = conn.execute("SELECT goal,city FROM research_tasks WHERE id=?", (explicit,)).fetchone()
        assert saved['city'] == '上海'
        assert region_preference(saved['goal'])['mode'] == 'preferred'


def test_no_region_preference_does_not_produce_a_missing_city_search_warning():
    assessment = build_research_assessment(
        goal_plan={"search_rounds": [], "conditional_filters": []}, selected_searches=[],
        run_summaries=[], candidate_pool={"candidate_count": 16, "all_candidates": [{"signals": {}}] * 16, "shortlist_for_next_evidence": []})
    assert "no_target_city_signal" not in assessment["quality_flags"]


def test_region_instructions_distinguish_all_three_modes():
    assert "不设置地区偏好" in region_instruction(region_preference("买手柄"))
    assert "软偏好" in region_instruction(region_preference("上海优先"))
    assert "硬条件" in region_instruction(region_preference("只考虑上海自提"))


def test_unrecognized_region_is_kept_for_confirmation_not_filled_with_shanghai():
    preference = region_preference("买手柄，只考虑横店自提")
    assert preference["city"] is None and preference["needs_confirmation"]
    assert "需核对原文" in region_instruction(preference)


def test_real_goal_draft_route_cannot_invent_a_city(tmp_path):
    import json
    from fastapi.testclient import TestClient
    from shopping_agent.codex_runtime import CodexRuntime, AnswerResult
    from shopping_agent.web.app import create_app

    class DraftRuntime(CodexRuntime):
        def __init__(self):
            self.requests = []

        def run(self, request, **kwargs):
            self.requests.append(request)
            return AnswerResult(type="answer", content=json.dumps(dict(title="手柄", goal="买手柄上海自提", hard=["上海自提", "必须原装"], soft=[], budget=None)), candidate_ids=[])

    config = tmp_path / "config.toml"
    config.write_text(f'database_path="{(tmp_path / "app.sqlite").as_posix()}"\ndefault_city="上海"\n', encoding="utf-8")
    app = create_app(config, tmp_path / "settings.json")
    runtime = DraftRuntime()
    app.state.codex_runtime = runtime
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for goal, field, expected in [("买手柄", None, None), ("买手柄，上海优先", "soft", "上海优先"), ("买手柄，只考虑上海自提", "hard", "只考虑上海自提")]:
            response = client.post("/api/project-goal-drafts", json={"goal": goal})
            assert response.status_code == 200, response.text
            draft = response.json()
            assert draft["goal"] == goal
            if field:
                assert expected in draft[field]
            else:
                assert draft["hard"] == ["必须原装"] and draft["soft"] == []
            if field == "soft":
                assert draft["hard"] == ["必须原装"]
        with connect(app.state.project_research.config.database_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM research_tasks").fetchone()[0] == 0
