"""Fabricated model output validates the harness, never real model quality."""
import copy
import importlib.util
import json
import sys

import pytest

from shopping_agent.assessment import Criterion, ResearchResult, input_refs
from shopping_agent.codex_runtime import AnswerResult, CodexCancelledError, CodexExecutionError, InvalidCodexResult, PreferenceUpdateResult
from shopping_agent.config import AppConfig
from shopping_agent.conversation_replay import (GOAL, TracedRuntime, check_journey_round, journey_turn,
                                                CapturingCodexRuntime, audit_saved_journey, restored_snapshot,
                                                run_journey, saved_failed_request, seed_saved_candidates)
from shopping_agent.conversation_service import ConversationService
from shopping_agent.db import connect
from shopping_agent.history_review import ComparisonResult, HistoryReviewResult, NominationResult


class FabricatedJourneyModel:
    def __init__(self):
        self.current_round = 0

    def run(self, request, *, run_id, stage_callback=None):
        stage_callback("analyzing_evidence")
        # Real user messages, not model calls, advance the fixture turn.
        self.current_round = sum(m.role == "user" for m in request.messages) if request.messages else self.current_round
        number = self.current_round
        criteria = list(request.current_criteria) or [Criterion(criterion_id=key, description=text,
            priority="soft" if key == "condition" or key == "originality" and number < 3 else "hard", source_message_ids=[request.trigger_message_id])
            for key, text in (("budget", "预算"), ("battery", "电池"), ("capacity", "256GB"),
                              ("location", "上海面交"), ("originality", "原装"), ("condition", "成色别太差"))]
        if request.phase == "chat":
            if number == 3 and request.allow_preference_update:
                return PreferenceUpdateResult(type="preference_update", source_message_id=request.trigger_message_id,
                    base_revision_id=0, effective_goal="iPhone15Pro256GB，上海面交，4300元，电池90%，必须全原，换屏不要",
                    added_preferences=["4300元", "90%", "必须全原"], removed_preferences=["3800元", "88%", "尽量原装"])
            if number in (2, 7):
                return AnswerResult(type="answer", content="夹具普通问答，不代表质量。", candidate_ids=[])
            return HistoryReviewResult(type="history_review", summary="夹具重评", criteria=criteria)
        if request.phase == "review_batch":
            refs = input_refs(request)
            items = []
            for card in request.candidates:
                price = json.loads(card.data["evidence_json"])["price_value"]
                key = {3500: "A", 3750: "B", 4200: "C", 3650: "D"}[price]
                statuses = dict(budget="NOT_MET" if key == "C" and number < 3 else "MET",
                    battery="NOT_MET" if key == "A" and number >= 3 else "MET", capacity="CONFLICT" if key == "C" and number == 5 else "MET",
                    location="NOT_MET" if key == "D" else "MET", condition="MET", originality="NOT_MET" if (key == "B" and number >= 4) or (key == "C" and number == 8) else "UNKNOWN")
                judgments = []
                for criterion in criteria:
                    state = statuses[criterion.criterion_id]
                    own = [ref for ref, data in refs.items() if data["listing_id"] == card.listing_id]
                    fresh = [ref for ref in own if ref.startswith("statement:") and refs[ref]["data"]["source_message_id"] == request.trigger_message_id]
                    changed = bool(fresh) and ((number in (4, 8) and criterion.criterion_id == "originality")
                                               or (number in (5, 6) and criterion.criterion_id == "capacity"))
                    evidence = [own[0], fresh[0]] if changed and state == "CONFLICT" else fresh if changed else own[:1]
                    judgments.append(dict(criterion_id=criterion.criterion_id, status=state,
                        reason="夹具判断，不用于质量评分", source_type="user_statement" if changed and number in (5, 6) else "missing" if state == "UNKNOWN" else "seller_claim",
                        evidence_refs=[] if state == "UNKNOWN" else evidence))
                items.append(dict(listing_id=card.listing_id, judgments=judgments, summary="夹具摘要",
                    conclusion="not_met" if any(j["status"] == "NOT_MET" and c.priority == "hard" for j, c in zip(judgments, criteria)) else "conditional"))
            return AnswerResult(type="answer", content="夹具逐项评估", candidate_ids=[a["listing_id"] for a in items if a["conclusion"] != "not_met"],
                                research=ResearchResult(criteria=criteria, assessments=items))
        items = request.review_context["assessments"]
        eligible = [a for a in items if a["conclusion"] != "not_met"]
        entries = [dict(listing_id=a["listing_id"], assessment_id=a["assessment_id"], reason="夹具选择", uncertainties=["未经核实"]) for a in eligible]
        if request.phase == "nomination":
            return NominationResult(type="nomination", candidates=entries)
        previous = request.review_context["previous_comparison"]
        before = {c["listing_id"] for c in previous["ranked_candidates"]} if previous else set()
        after = {c["listing_id"] for c in entries}
        by_id = {a["listing_id"]: a for a in items}
        return ComparisonResult(type="comparison", content="夹具比较，不代表真实判断", ranked_candidates=entries,
            changes=[dict(listing_id=i, assessment_id=by_id[i]["assessment_id"], kind=kind, reason="夹具进出")
                     for ids, kind in ((after-before, "entered"), (before-after, "exited")) for i in sorted(ids)])

    def cancel(self, run_id):
        pass


@pytest.fixture
def journey(tmp_path):
    config = AppConfig(database_path=tmp_path / "fixture.sqlite")
    report = {"calls": [], "quality_verified": False, "manual_review": "pending", "seed": 17,
              "mode": "real_model_service_journey", "suite_version": "purchase-journey-v1"}
    runtime = TracedRuntime(FabricatedJourneyModel(), report["calls"], lambda: None)
    run_journey(config, runtime, seed=17, report=report, save=lambda: None, turn_timeout=10)
    return config, report


def test_eight_turns_use_persisted_service_results_and_no_future_evidence(journey):
    config, report = journey
    assert report["state"] == "checks_passed_manual_review_pending", [(r["number"], r.get("checks")) for r in report["rounds"]]
    assert len(report["rounds"]) == 8 and len(report["calls"]) > 8
    first_input = json.dumps(report["calls"][0]["request"], ensure_ascii=False)
    assert "128GB" not in first_input and "边框换过" not in first_input and "官方换过" not in first_input
    before = report["rounds"][2]["snapshot"]["task"]
    assert len(before["preference_revisions"]) == 1
    final = restored_snapshot(config, report["task_id"])
    assert not final["task"]["research"]["comparisons"][-1]["result"]["ranked_candidates"]
    assert len([m for m in final["messages"]["items"] if m["candidate_statement"]]) == 4
    with connect(config.database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidate_statements").fetchone()[0] == 4
    assert report["quality_verified"] is False and report["manual_review"] == "pending"
    audited = audit_saved_journey(report)
    assert audited["state"] == "checks_passed_manual_review_pending" and audited["calls"] == 0


@pytest.mark.parametrize("fault", ["prompt", "trace", "missing_round", "reordered_round"])
def test_audit_rejects_changed_or_incomplete_trace(journey, fault):
    _, original = journey
    report = copy.deepcopy(original)
    if fault == "prompt": report["calls"][0]["prompt_signature"] = "changed"
    elif fault == "trace": report["rounds"][0]["call_end"] = 0
    elif fault == "missing_round": report["rounds"].pop()
    else: report["rounds"][0]["number"] = 2
    if fault == "reordered_round":
        with pytest.raises(ValueError): audit_saved_journey(report)
    else:
        assert audit_saved_journey(report)["state"] == "incomplete_or_failed"


@pytest.mark.parametrize("fault", ["revision", "original", "snapshot", "coverage", "ranking", "priority", "cosmetic_priority", "binding_reference", "binding_type"])
def test_checker_detects_persisted_state_failures(journey, fault):
    _, report = journey
    row = report["rounds"][3]
    snapshot = copy.deepcopy(row["snapshot"])
    previous = report["rounds"][2]["snapshot"]
    detail = snapshot["task"]
    if fault == "revision":
        detail["preference_revisions"] = []
    elif fault == "original":
        detail["task"]["original_goal"] = "overwritten"
    elif fault == "snapshot":
        detail["research"]["assessment_batches"][0]["result"]["assessments"][0]["summary"] = "rewritten"
    elif fault == "coverage":
        detail["research"]["comparisons"][-1]["coverage"]["assessed_count"] = 3
    elif fault == "ranking":
        detail["research"]["comparisons"][-1]["result"]["ranked_candidates"].append(dict(listing_id=report["candidate_legend"]["B"]))
    elif fault in {"priority", "cosmetic_priority"}:
        for standard in detail["research"]["standards"]:
            for c in standard["criteria"]:
                if c["criterion_id"] == ("condition" if fault == "cosmetic_priority" else "originality"):
                    c["priority"] = "hard" if fault == "cosmetic_priority" else "soft"
    else:
        item = detail["research"]["assessment_batches"][-1]["result"]["assessments"][0]
        judgment = next(j for j in item["judgments"] if j["criterion_id"] == "originality")
        if fault == "binding_reference": judgment["evidence_refs"] = []
        else: judgment["source_type"] = "platform_display"
    assert check_journey_round(4, snapshot, report["candidate_legend"], previous)


def test_mixed_source_conflict_may_be_inference_with_new_source_cited(journey):
    _, report = journey
    snapshot = copy.deepcopy(report["rounds"][4]["snapshot"])
    item = snapshot["task"]["research"]["assessment_batches"][-1]["result"]["assessments"][0]
    next(j for j in item["judgments"] if j["criterion_id"] == "capacity")["source_type"] = "inference"
    assert check_journey_round(5, snapshot, report["candidate_legend"], report["rounds"][3]["snapshot"]) == []


def test_call_limit_does_not_execute_extra_inference():
    calls = []
    runtime = TracedRuntime(FabricatedJourneyModel(), calls, lambda: None, max_calls=1)
    from shopping_agent.quality_replay import build_probes
    request = build_probes()[0].request
    runtime.run(request, run_id=1)
    with pytest.raises(CodexExecutionError):
        runtime.run(request, run_id=2)
    assert len(calls) == 1


def test_rejected_raw_model_output_and_validation_cause_are_retained(tmp_path):
    from shopping_agent.quality_replay import build_probes
    raw = '{"type":"answer","content":"","candidate_ids":[]}'
    class InvalidRaw(CapturingCodexRuntime):
        def run(self, request, **kwargs):
            return self.parse_result(raw, allowed_listing_ids=set())
    calls = []
    runtime = TracedRuntime(InvalidRaw(tmp_path), calls, lambda: None)
    with pytest.raises(InvalidCodexResult): runtime.run(build_probes()[0].request, run_id=1)
    assert calls[0]["raw_result"] == raw
    assert calls[0]["validation_errors"][0]["msg"]
    assert "input" not in calls[0]["validation_errors"][0]


def test_diagnostic_saved_input_requires_original_signature(journey):
    _, original = journey
    report = copy.deepcopy(original)
    report["calls"][-1]["state"] = "execution_error"
    assert saved_failed_request(report).phase == report["calls"][-1]["phase"]
    report["calls"][-1]["prompt_signature"] = "changed"
    with pytest.raises(ValueError): saved_failed_request(report)
    assert saved_failed_request(report, allow_prompt_change=True).phase == report["calls"][-1]["phase"]
    report["calls"][-1]["request_signature"] = "changed"
    with pytest.raises(ValueError): saved_failed_request(report, allow_prompt_change=True)


def test_conflict_does_not_justify_not_met_but_can_stop_purchase(tmp_path):
    runtime = CapturingCodexRuntime(tmp_path)
    result = dict(type="answer", content="冲突未解除，暂停购买。", candidate_ids=[], research=dict(
        criteria=[dict(criterion_id="originality", description="全原", priority="hard", source_message_ids=[1])],
        assessments=[dict(listing_id=1, judgments=[dict(criterion_id="originality", status="CONFLICT",
            source_type="seller_claim", reason="前后卖家答复矛盾", evidence_refs=["old", "new"])],
            conclusion="not_met", summary="停止购买")]))
    with pytest.raises(InvalidCodexResult): runtime.parse_result(json.dumps(result), allowed_listing_ids={1})
    result["research"]["assessments"][0]["conclusion"] = "insufficient_evidence"
    parsed = runtime.parse_result(json.dumps(result), allowed_listing_ids={1})
    assert parsed.research.assessments[0].judgments[0].status == "CONFLICT"
    assert parsed.candidate_ids == []


def test_failed_operation_stops_future_rounds_and_keeps_boundaries(tmp_path):
    class Broken(FabricatedJourneyModel):
        def run(self, *args, **kwargs): raise CodexExecutionError("fixture")
    report = {"calls": []}
    run_journey(AppConfig(database_path=tmp_path / "db.sqlite"), TracedRuntime(Broken(), report["calls"], lambda: None),
                seed=17, report=report, save=lambda: None, turn_timeout=10)
    assert report["state"] == "incomplete_or_failed"
    assert len(report["rounds"]) == 1 and len(report["not_run"]) == 7
    assert report["rounds"][0]["operation"]["operation"]["error_code"] == "codex_execution_failed"


def test_turn_timeout_cancels_worker_and_preserves_partial_trace(tmp_path):
    import threading
    class Blocking(FabricatedJourneyModel):
        def __init__(self): self.stopped = threading.Event()
        def run(self, *args, **kwargs):
            self.stopped.wait(5)
            raise CodexCancelledError("fixture cancelled")
        def cancel(self, run_id): self.stopped.set()
    report = {"calls": []}
    model = Blocking()
    run_journey(AppConfig(database_path=tmp_path / "db.sqlite"), TracedRuntime(model, report["calls"], lambda: None),
                seed=17, report=report, save=lambda: None, turn_timeout=.05)
    assert report["rounds"][0]["turn_timeout"] is True
    assert report["rounds"][0]["operation"]["operation"]["state"] == "cancelled"
    assert model.stopped.is_set()
    # Context construction may take longer than the short deadline. Cancelling
    # before the runner starts legitimately leaves no model-call trace.
    assert all(call["state"] == "execution_error" for call in report["calls"])
    assert len(report["not_run"]) == 7


def test_successful_plain_answer_is_not_full_journey_review(tmp_path):
    class Plain(FabricatedJourneyModel):
        def run(self, *args, **kwargs):
            return AnswerResult(type="answer", content="没有实际保存评估或比较", candidate_ids=[])
    report = {"calls": []}
    run_journey(AppConfig(database_path=tmp_path / "db.sqlite"), TracedRuntime(Plain(), report["calls"], lambda: None),
                seed=17, report=report, save=lambda: None, turn_timeout=10)
    row = report["rounds"][0]
    assert row["operation"]["operation"]["state"] == "completed"
    assert row["state"] == "checks_failed" and "no current persisted comparison" in row["checks"]


def test_seed_changes_listing_identity_order_without_future_data(tmp_path):
    identities = []
    for seed in (17, 41):
        config = AppConfig(database_path=tmp_path / f"seed{seed}.sqlite")
        created = ConversationService(config).create_task(GOAL)
        ids = seed_saved_candidates(config, created.task.id, seed)
        identities.append(ids)
        assert journey_turn(4, ids).binding == dict(listing_id=ids["B"], kind="seller_reply")
    assert identities[0] != identities[1]


def test_cli_default_plan_has_no_setup_calls(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("journey_script", "scripts/replay_purchase_journey.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "argv", ["replay"])
    monkeypatch.setattr(module, "check_codex_availability", lambda: pytest.fail("setup called"))
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)["calls"] == 0


def test_cli_existing_output_refused_before_auth_or_inference(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("journey_script", "scripts/replay_purchase_journey.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "keep.json"
    path.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["replay", "--run", "--output", str(path)])
    monkeypatch.setattr(module, "check_codex_availability", lambda: pytest.fail("setup called"))
    with pytest.raises(FileExistsError): module.main()
    assert path.read_text(encoding="utf-8") == "keep"
