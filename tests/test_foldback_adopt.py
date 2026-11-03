from __future__ import annotations

import json

import pytest

from shopping_agent import research_loop
from shopping_agent.cli import _load_prior_foldback
from shopping_agent.config import AppConfig
from shopping_agent.research_assessment import build_research_assessment


def test_build_foldback_adoption_adopts_when_foldback_improves(monkeypatch):
    captured = {}

    def fake_comparison(config, *, run_ids, options):
        captured["run_ids"] = list(run_ids)
        captured["goal"] = options.goal
        captured["target_city"] = options.target_city
        return {
            "run_metrics": [
                {"noise_ratio": 0.7, "useful_candidate_count": 9},
                {"noise_ratio": 0.6, "useful_candidate_count": 12},
            ]
        }

    monkeypatch.setattr(research_loop, "build_run_comparison", fake_comparison)
    config = AppConfig()
    verdict = research_loop.build_foldback_adoption(
        config,
        baseline_run_id=13,
        foldback_run_id=16,
        query="better term",
        goal="macbook pro m1",
        target_city="Shanghai",
    )
    assert verdict["adopted"] is True
    assert verdict["verdict"] == "adopted"
    assert verdict["noise_ratio_delta"] == -0.1
    assert verdict["useful_candidate_delta"] == 3
    assert captured["run_ids"] == [13, 16]
    assert captured["goal"] == "macbook pro m1"
    assert captured["target_city"] == "Shanghai"


def test_build_foldback_adoption_indeterminate_when_metrics_missing(monkeypatch):
    monkeypatch.setattr(
        research_loop,
        "build_run_comparison",
        lambda *a, **k: {"run_metrics": [{}]},
    )
    config = AppConfig()
    verdict = research_loop.build_foldback_adoption(
        config, baseline_run_id=1, foldback_run_id=2, query="x"
    )
    assert verdict["verdict"] == "indeterminate"
    assert verdict["adopted"] is False
    assert "Could not build metrics" in verdict["reason"]


def test_load_prior_foldback_returns_none_for_empty_path():
    assert _load_prior_foldback(None) is None
    assert _load_prior_foldback("") is None


def test_load_prior_foldback_reads_bom_json(tmp_path):
    f = tmp_path / "verdict.json"
    payload = json.dumps({"verdict": "rejected", "query": "bad term"})
    f.write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))
    data = _load_prior_foldback(str(f))
    assert data["verdict"] == "rejected"
    assert data["query"] == "bad term"


def test_load_prior_foldback_rejects_non_object(tmp_path):
    f = tmp_path / "arr.json"
    f.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(SystemExit):
        _load_prior_foldback(str(f))



def test_rejected_prior_foldback_is_rendered_into_next_search_prompt():
    assessment = build_research_assessment(
        goal_plan={
            "goal": "macbook pro m1",
            "search_rounds": [{"round": 1, "platform": "xianyu", "query": "MacBook Pro M1", "filters": {}}],
        },
        selected_searches=[{"platform": "xianyu", "query": "MacBook Pro M1", "filters": {}}],
        run_summaries=[
            {
                "run_id": 9,
                "result_quality": {
                    "listing_count": 30,
                    "priced_listing_count": 30,
                    "located_listing_count": 30,
                    "access_blocked": False,
                },
            }
        ],
        candidate_pool=None,
        next_search_via_codex=True,
        prior_foldback={
            "verdict": "rejected",
            "query": "bad size term",
            "reason": "noise rose 0.533->0.633",
            "noise_ratio_delta": 0.1,
            "useful_candidate_delta": -3,
        },
    )
    request = assessment["next_search_request"]
    assert request is not None
    prompt = request["codex_prompt"]
    assert "Prior foldback verdict" in prompt
    assert "bad size term" in prompt
    assert "rejected" in prompt
    assert "noise_delta=+0.100" in prompt
    assert "useful_delta=-3" in prompt
    assert assessment["foldback_adoption"]["verdict"] == "rejected"
