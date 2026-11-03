"""Harness/oracle tests with fabricated outputs, never model-quality evidence."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from shopping_agent.assessment import input_refs
from shopping_agent.codex_runtime import (AnswerResult, CodexExecutionError, CodexRuntime,
                                          PreferenceUpdateResult)
from shopping_agent.history_review import ComparisonResult, NominationResult
from shopping_agent.quality_replay import build_probes, check_probe, probe_manifest, rescore_report
from shopping_agent.setup_status import CodexStatus


def probe(name):
    return next(p for p in build_probes() if p.name == name)


def fabricated_answer(p):
    refs = input_refs(p.request)
    assessments = []
    for listing_id, statuses in p.statuses.items():
        judgments = []
        for key, status in statuses.items():
            selected = [ref for ref, item in refs.items() if item["listing_id"] == listing_id
                        and (ref.startswith("statement:") if status == "CONFLICT" else ref.startswith("card:"))]
            judgments.append(dict(criterion_id=key, status=status, reason="测试夹具",
                source_type="missing" if status == "UNKNOWN" else "seller_claim",
                evidence_refs=[] if status == "UNKNOWN" else selected))
        assessments.append(dict(listing_id=listing_id, judgments=judgments, summary="测试夹具",
            conclusion="not_met" if "NOT_MET" in statuses.values() else "conditional"))
    return AnswerResult.model_validate(dict(type="answer", content="测试夹具",
        candidate_ids=list(p.eligible_ids), research=dict(criteria=[c.model_dump() for c in p.request.current_criteria],
                                                        assessments=assessments)))


def test_reproducible_seed_and_oracle_not_in_prompt():
    left, right = build_probes(17), build_probes(18)
    assert [probe_manifest(p) for p in left] == [probe_manifest(p) for p in build_probes(17)]
    assert left[3].request.allowed_listing_ids != right[3].request.allowed_listing_ids
    for p in left:
        prompt = CodexRuntime._build_prompt(p.request)
        assert "expected_type" not in prompt and "eligible_ids" not in prompt and "required_statement_ids" not in prompt
        assert p.request.runs == ()
        assert "shopping-research" not in p.request.task.original_goal


@pytest.mark.parametrize("name", ["fixed-facts", "conflicting-seller-replies"])
def test_fabricated_correct_facts(name):
    p = probe(name)
    assert check_probe(p, fabricated_answer(p)) == []


@pytest.mark.parametrize("fault", ["status", "coverage", "reference", "source", "criteria", "hard_failure"])
def test_corrupt_fact_result_fails(fault):
    p = probe("fixed-facts")
    answer = fabricated_answer(p)
    item = answer.research.assessments[0]
    if fault == "status":
        item.judgments[2].status = "MET"
        item.judgments[2].source_type = "seller_claim"
    elif fault == "coverage":
        answer.research.assessments.pop()
    elif fault == "reference":
        item.judgments[0].evidence_refs = [next(ref for ref, data in input_refs(p.request).items()
                                              if data["listing_id"] != item.listing_id)]
    elif fault == "source":
        item.judgments[0].source_type = "image_observation"
    elif fault == "criteria":
        answer.research.criteria[0].description = "预算随便"
    else:
        answer.candidate_ids.append(next(i for i in p.statuses if i not in p.eligible_ids))
    assert check_probe(p, answer)


def test_conflict_requires_both_individual_statement_refs():
    p = probe("conflicting-seller-replies")
    answer = fabricated_answer(p)
    item = answer.research.assessments[0]
    # Two generic parent excerpts do not establish attribution of two replies.
    item.judgments[-1].evidence_refs = [ref for ref in input_refs(p.request) if not ref.startswith("statement:")]
    assert any("individual conflicting" in error for error in check_probe(p, answer))


def test_unverified_positive_claim_can_remain_unknown_but_not_become_verified():
    p = probe("fixed-facts")
    answer = fabricated_answer(p)
    item = next(a for a in answer.research.assessments if a.listing_id in p.claim_unknown_allowed)
    item.judgments[-1].status = "UNKNOWN"
    assert check_probe(p, answer) == []
    item.judgments[-1].source_type = "platform_display"
    assert any("misattributed" in e for e in check_probe(p, answer))


def test_chat_cannot_hide_invented_candidates_inside_research():
    answer = fabricated_answer(probe("fixed-facts"))
    answer.candidate_ids = []
    errors = check_probe(probe("unbound-seller"), answer)
    assert "assessment invented a candidate outside input" in errors
    assert "assessment used a foreign or nonexistent reference" in errors


@pytest.mark.parametrize("fault", [None, "input", "prompt", "duplicate", "missing"])
def test_rescore_uses_saved_outputs_and_preserves_original(fault):
    p = probe("fixed-facts")
    raw = dict(probe_manifest(p), state="checks_failed", result=fabricated_answer(p).model_dump(mode="json"))
    report = dict(mode="real_model", seed=17, suite_version="offline-probes-v1",
                  state="incomplete_or_failed", selected_cases=1, cases=[raw])
    if fault == "input":
        raw["request"]["task"]["effective_goal"] = "changed"
    elif fault == "prompt":
        raw["prompt_signature"] = "changed"
    elif fault == "duplicate":
        report["cases"].append(raw)
    elif fault == "missing":
        report["cases"] = []
    before = json.dumps(report)
    runtime = CodexRuntime(Path.cwd())
    if fault in {"input", "prompt", "duplicate"}:
        with pytest.raises(ValueError):
            rescore_report(report, runtime)
    else:
        rescored = rescore_report(report, runtime)
        assert rescored["calls"] == 0 and rescored["quality_verified"] is False
        assert rescored["checks_passed"] == (0 if fault else 1)
        assert rescored["state"] == ("incomplete_or_failed" if fault else "checks_passed_manual_review_pending")
    assert json.dumps(report) == before


def test_routing_and_revised_goal_retention():
    answer = AnswerResult(type="answer", content="需要先澄清对象。", candidate_ids=[])
    assert check_probe(probe("unbound-seller"), answer) == []
    assert check_probe(probe("explicit-budget"), answer)
    update = PreferenceUpdateResult(type="preference_update", source_message_id=2, base_revision_id=0,
        effective_goal="256GB手机，预算4800元，必须全原无维修", added_preferences=["4800元"], removed_preferences=["4300元"])
    assert check_probe(probe("explicit-budget"), update) == []
    update.effective_goal = "预算4800"
    assert check_probe(probe("explicit-budget"), update)


@pytest.mark.parametrize("phase", ["nomination", "comparison"])
def test_saved_judgment_references_and_unknowns(phase):
    p = probe(phase)
    saved = p.request.review_context["assessments"]
    unknown = next(a for a in saved if any(j["status"] == "UNKNOWN" for j in a["judgments"]))
    entry = dict(listing_id=unknown["listing_id"], assessment_id=unknown["assessment_id"],
                 reason="测试夹具", uncertainties=["维修记录未知"])
    result = (NominationResult(type="nomination", candidates=[entry]) if phase == "nomination"
              else ComparisonResult(type="comparison", content="测试夹具", ranked_candidates=[entry],
                                    changes=[dict(**{k: entry[k] for k in ("listing_id", "assessment_id", "reason")}, kind="entered")]))
    assert check_probe(p, result) == []
    items = result.candidates if phase == "nomination" else result.ranked_candidates
    items[0].uncertainties = []
    assert "unresolved judgment lost uncertainty" in check_probe(p, result)
    items[0].assessment_id = 999999
    assert "wrong saved assessment reference" in check_probe(p, result)
    items[0].listing_id = next(a["listing_id"] for a in saved if a["conclusion"] == "not_met")
    assert "hard failure nominated/ranked" in check_probe(p, result)


def load_script():
    spec = importlib.util.spec_from_file_location("replay_script", "scripts/replay_model_quality.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_default_plan_makes_no_setup_or_model_calls(monkeypatch, capsys):
    module = load_script()
    monkeypatch.setattr(sys, "argv", ["replay", "--case", "fixed-facts"])
    monkeypatch.setattr(module, "check_codex_availability", lambda: pytest.fail("setup called"))
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)["calls"] == 0


def test_cli_never_overwrites_existing_report(tmp_path, monkeypatch):
    module = load_script()
    path = tmp_path / "report.json"
    path.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["replay", "--run", "--output", str(path)])
    monkeypatch.setattr(module, "check_codex_availability", lambda: pytest.fail("setup called"))
    with pytest.raises(FileExistsError):
        module.main()
    assert path.read_text() == "keep"


def test_cli_success_keeps_manual_review_pending(tmp_path, monkeypatch):
    module = load_script()
    path = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["replay", "--run", "--case", "fixed-facts", "--output", str(path)])
    monkeypatch.setattr(module, "check_codex_availability", lambda: CodexStatus(
        cli_available=True, auth_available=True, detail="fixture"))
    monkeypatch.setattr(CodexRuntime, "run", lambda self, request, run_id: fabricated_answer(probe("fixed-facts")))
    assert module.main() == 0
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["state"] == "checks_passed_manual_review_pending"
    assert report["quality_verified"] is False and report["model_identity"].startswith("CLI configured default")
    assert report["tokens"] is None and report["tool_calls"] is None
    monkeypatch.setattr(module, "check_codex_availability", lambda: pytest.fail("setup called during rescore"))
    monkeypatch.setattr(CodexRuntime, "run", lambda *a, **k: pytest.fail("inference during rescore"))
    rescore_path = tmp_path / "rescored.json"
    monkeypatch.setattr(sys, "argv", ["replay", "--rescore", str(path), "--output", str(rescore_path)])
    assert module.main() == 0
    assert json.loads(rescore_path.read_text(encoding="utf-8"))["calls"] == 0


@pytest.mark.parametrize("available", [True, False])
def test_cli_setup_and_execution_failure_are_not_quality_pass(tmp_path, monkeypatch, available):
    module = load_script()
    path = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["replay", "--run", "--output", str(path)])
    monkeypatch.setattr(module, "check_codex_availability", lambda: CodexStatus(
        cli_available=available, auth_available=available, detail="fixture"))
    calls = []
    def fail(self, request, *, run_id):
        calls.append(request)
        assert self.project_root != Path.cwd()
        assert set(p.name for p in self.project_root.iterdir()) == {".git"}
        raise CodexExecutionError("fixture")
    monkeypatch.setattr(CodexRuntime, "run", fail)
    assert module.main() == (1 if available else 2)
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["quality_verified"] is False and report["manual_review"] == "pending"
    assert len(calls) == (1 if available else 0)
    if available:
        assert len(report["not_run"]) == 6
        assert report["cases"][0]["state"] == "execution_error"
