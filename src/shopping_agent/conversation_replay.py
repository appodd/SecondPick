"""Synthetic eight-turn journey through real services and persistence.

No platform executor is constructed. Checks below are external fixture oracles,
not model input, ranking heuristics or a semantic quality score.
"""
from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from pydantic import ValidationError

from shopping_agent.assessment import signature
from shopping_agent.codex_runtime import CodexExecutionError, CodexRequest, CodexRuntime
from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.db import (add_listing_snapshot, attach_run_to_task, connect,
                               create_search_run, upsert_listing)
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.web.services import WorkbenchService


JOURNEY_VERSION = "purchase-journey-v1"
CHECKER_VERSION = "journey-checks-v3"
GOAL = ("想买台二手 iPhone 15 Pro，256GB，预算3800以内，上海面交。电池至少88%，"
        "成色别太差，尽量原装。我不太懂，你帮我看看。请逐项重评当前任务内全部已保存候选并生成比较，"
        "仅使用已有证据，不访问网站或执行工具。")
ROUND_NAMES = ("initial-review", "price-question", "requirements-change", "seller-screen-repair",
               "capacity-conflict", "capacity-explanation", "inspection-checklist", "abandon-first-choice")


@dataclass(frozen=True)
class JourneyTurn:
    message: str
    binding: dict | None = None


def journey_turn(number: int, ids: dict[str, int]) -> JourneyTurn:
    """Only the current turn is sent; future evidence is never pre-seeded."""
    a, b, c = (ids[key] for key in "ABC")
    review = "请用已有证据重评全部历史候选并更新比较，不改变购买要求，不执行平台采集。"
    turns = {
        1: JourneyTurn(GOAL),
        2: JourneyTurn(f"商品#{b}比商品#{a}贵250，值得吗？是不是更靠谱？仅比较已有证据，不改变要求。"),
        3: JourneyTurn("预算可以到4300，但这次原装是硬要求，换过屏的不要。电池至少90%。其他要求保持，并重评全部已保存候选。"),
        4: JourneyTurn(f"商品#{b}卖家答复原文：‘屏幕去年在官方换过，有维修单。官方换的跟原装一样，放心买。’\n{review}",
                       dict(listing_id=b, kind="seller_reply")),
        5: JourneyTurn(f"我查看商品#{c}卖家刚发的关于本机截图，显示容量128GB，与已存256GB文字不一致，尚未说明原因。"
                       f"这是我提供的结构化截图观察，不是让你读取原始图片。还能考虑吗？帮我写几个要问的问题。{review}",
                       dict(listing_id=c, kind="user_observation")),
        6: JourneyTurn(f"商品#{c}补充记录：卖家解释128GB截图是家里另一台，之前发错了。我查看了新连续视频，"
                       "看到本机容量256GB、电池95%，部件页面未显示异常，视频局部设备标识与凭证相符。"
                       f"卖家另明确回复‘没有拆修换件’。这些是用户记录的结构化观察和转述，未经独立验机。{review}",
                       dict(listing_id=c, kind="user_observation")),
        7: JourneyTurn(f"那我准备去看商品#{c}。给我一份简短的针对性面交检查清单，什么情况就别买？不要替我联系卖家或预约。"),
        8: JourneyTurn(f"商品#{c}现场卖家承认：‘边框换过，但屏幕没换，便宜200能买。’我现在还是想要全原，怎么办？{review}",
                       dict(listing_id=c, kind="seller_reply")),
    }
    return turns[number]


def seed_saved_candidates(config: AppConfig, task_id: int, seed: int) -> dict[str, int]:
    """Seed only initial collected evidence. Never seed judgments or revisions."""
    facts = dict(A=(3500, 89, "上海", "卖家称全原无修、上海可面交；外观细小划痕；暂无部件页面。"),
                 B=(3750, 92, "上海", "卖家称外观良好、上海可面交。未说明维修史，无部件页面或购买凭证。"
                    "结构化转录：卖家电池截图显示92%，未经独立核实；本测试不包含原始图片。"),
                 C=(4200, 95, "上海", "卖家称全原无修、上海可面交，有购买凭证照片。"
                    "结构化转录：卖家电池截图显示95%，凭证称256GB；是否同机仍待核对。未经独立核实，本测试不含原始图片。"),
                 D=(3650, 94, "苏州", "卖家称原装，只支持苏州面交、可邮寄，不支持上海面交。"))
    order = list(facts)
    random.Random(seed).shuffle(order)
    ids = {}
    with connect(config.database_path) as conn:
        run = create_search_run(conn, GOAL, "上海")
        attach_run_to_task(conn, task_id, run)
        for key in order:
            price, battery, city, description = facts[key]
            listing = upsert_listing(conn, "xianyu", f"https://example.test/journey/{seed}/{key}")
            ids[key] = listing
            add_listing_snapshot(conn, listing, run, title="iPhone 15 Pro 256GB", price_text=str(price),
                                 location=city, description=f"虚构已保存证据：电池{battery}%。{description}")
    return ids


class TracedRuntime:
    """Record actual requests/results without changing production prompts."""
    build_request = CodexRuntime.build_request

    def __init__(self, runtime, calls: list, save, max_calls: int = 32):
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        self.runtime, self.calls, self.save, self.max_calls = runtime, calls, save, max_calls
        self.lock = threading.RLock()

    def run(self, request, *, run_id, stage_callback=None):
        with self.lock:
            if len(self.calls) >= self.max_calls:
                raise CodexExecutionError("Replay call limit reached")
            row = dict(operation_id=run_id, phase=request.phase, state="running",
                       request=request.model_dump(mode="json"), request_signature=signature(request.model_dump(mode="json")),
                       prompt_signature=signature(CodexRuntime._build_prompt(request)), stages=[])
            self.calls.append(row)
            self.save()
        started = time.monotonic()
        def stage(value):
            row["stages"].append(value)
            if stage_callback:
                stage_callback(value)
        try:
            result = self.runtime.run(request, run_id=run_id, stage_callback=stage)
            row.update(state="returned", result=result.model_dump(mode="json"))
            return result
        except Exception as exc:
            row.update(state="execution_error", error_type=type(exc).__name__)
            if getattr(exc, "diagnostics", None) is not None:
                row["failure_diagnostics"] = exc.diagnostics
            if isinstance(exc.__cause__, ValidationError):
                row["validation_errors"] = exc.__cause__.errors(include_input=False, include_context=False, include_url=False)
            raise
        finally:
            raw = getattr(self.runtime, "last_raw_result", None)
            if raw is not None:
                row["raw_result"] = raw
            take_telemetry = getattr(self.runtime, "take_telemetry", None)
            if callable(take_telemetry):
                metadata = take_telemetry(run_id)
                if metadata is not None:
                    row["telemetry"] = metadata
            row["duration_seconds"] = round(time.monotonic() - started, 3)
            self.save()

    def cancel(self, run_id):
        return self.runtime.cancel(run_id)


class CapturingCodexRuntime(CodexRuntime):
    """Synthetic replay diagnostics only; also retain rejected CLI output."""
    last_raw_result = None

    def run(self, *args, **kwargs):
        self.last_raw_result = None
        return super().run(*args, **kwargs)

    def parse_result(self, raw, *, allowed_listing_ids):
        self.last_raw_result = raw
        return super().parse_result(raw, allowed_listing_ids=allowed_listing_ids)


def saved_failed_request(report: dict, *, allow_prompt_change: bool = False) -> CodexRequest:
    if report.get("mode") != "real_model_service_journey" or not report.get("calls"):
        raise ValueError("expected a saved service journey")
    call = report["calls"][-1]
    if call["state"] != "execution_error":
        raise ValueError("last call was not an execution error")
    request = CodexRequest.model_validate_json(json.dumps(call["request"]))
    if (call["request_signature"] != signature(request.model_dump(mode="json"))
            or (not allow_prompt_change and call["prompt_signature"] != signature(CodexRuntime._build_prompt(request)))):
        raise ValueError("saved failed request or prompt has changed")
    return request


def restored_snapshot(config: AppConfig, task_id: int) -> dict:
    """Use fresh services, as after a service restart; no fabricated state."""
    service = ConversationService(config)
    return dict(task=WorkbenchService(config).get_task(task_id).model_dump(mode="json"),
                messages=service.get_messages(task_id, limit=100).model_dump(mode="json"),
                actions=service.get_action_requests(task_id).model_dump(mode="json"))


def check_journey_round(number: int, snapshot: dict, ids: dict, previous: dict | None) -> list[str]:
    """Known fixture constraints only. Full prose/ranking needs separate review."""
    errors = []
    detail, messages = snapshot["task"], snapshot["messages"]["items"]
    research = detail["research"]
    revisions = detail["preference_revisions"]
    expected_revisions = 0 if number < 3 else 1
    if len(revisions) != expected_revisions:
        errors.append("unexpected requirement revision count")
    if detail["task"]["original_goal"] != GOAL:
        errors.append("original goal overwritten")
    if number >= 3 and not all(s in detail["task"]["effective_goal"] for s in ("4300", "90", "256", "上海")):
        errors.append("revised goal lost fixture conditions")
    if len([m for m in messages if m["role"] == "user"]) != number:
        errors.append("persisted user-message count mismatch")
    if snapshot["actions"]["items"]:
        errors.append("unexpected platform action request; no action was executed")
    if previous:
        for key in ("assessment_batches", "comparisons"):
            old = {r["id"]: r["result"] for r in previous["task"]["research"][key]}
            now = {r["id"]: r["result"] for r in research[key]}
            if any(now.get(i) != result for i, result in old.items()):
                errors.append(f"saved {key} result overwritten or lost")
    if number in (2, 7):
        return errors
    comparisons = research["comparisons"]
    if not comparisons or comparisons[-1]["stale"]:
        return errors + ["no current persisted comparison"]
    comparison = comparisons[-1]
    if previous and comparison["id"] in {r["id"] for r in previous["task"]["research"]["comparisons"]}:
        errors.append("review did not publish a new comparison")
    if comparison["coverage"] != dict(scope_count=4, reviewed_count=4, assessed_count=4, pending_count=0, truncated=False):
        errors.append("full saved scope not assessed")
    standard = next((s for s in research["standards"] if s["id"] == comparison["standard_id"]), None)
    criteria = {c["criterion_id"]: c for c in standard["criteria"]} if standard else {}
    core = {"budget", "battery", "capacity", "location", "originality"}
    if not core <= criteria.keys():
        errors.append("core semantic criterion IDs missing; manual mapping required")
    if "originality" in criteria and criteria["originality"]["priority"] != ("soft" if number == 1 else "hard"):
        errors.append("originality priority differs from explicit requirement")
    if criteria.get("condition", {}).get("priority") != "soft":
        errors.append("vague cosmetic preference became a hard requirement or was omitted")
    current = {}
    for batch in research["assessment_batches"]:
        if batch["standard_id"] == comparison["standard_id"]:
            for item in batch["result"]["assessments"]:
                if not batch["candidate_stale"].get(str(item["listing_id"]), batch["stale"]):
                    current[item["listing_id"]] = item
    if set(current) != set(ids.values()):
        return errors + ["current persisted per-candidate judgments incomplete"]
    def status(key, criterion):
        return next((j["status"] for j in current[ids[key]]["judgments"] if j["criterion_id"] == criterion), None)
    if status("D", "location") != "NOT_MET":
        errors.append("Suzhou-only candidate lost Shanghai hard failure")
    if number == 1 and status("C", "budget") != "NOT_MET":
        errors.append("initial over-budget candidate not excluded")
    if number >= 3:
        if status("A", "battery") != "NOT_MET":
            errors.append("89-percent battery did not fail revised 90-percent minimum")
        if status("C", "budget") == "NOT_MET":
            errors.append("saved 4200 candidate did not recover under 4300 budget")
    if number >= 4 and status("B", "originality") != "NOT_MET":
        errors.append("admitted screen replacement did not fail originality")
    if number == 5 and status("C", "capacity") != "CONFLICT":
        errors.append("unresolved 128/256 capacity conflict lost")
    if number == 6 and status("C", "capacity") == "NOT_MET":
        errors.append("new explanatory evidence ignored")
    if number in (4, 5, 6, 8):
        latest = next(m for m in reversed(messages) if m["role"] == "user")
        binding = latest["candidate_statement"]
        if binding is None:
            errors.append("explicit evidence binding not restored")
        else:
            target = binding["listing_id"]
            criterion = "originality" if number in (4, 8) else "capacity"
            judgment = next((j for j in current[target]["judgments"] if j["criterion_id"] == criterion), None)
            supplied = {ref for batch in research["assessment_batches"] for ref, value in batch["evidence_refs"].items()
                        if ref.startswith("statement:") and value["listing_id"] == target
                        and value["data"].get("source_message_id") == latest["id"]}
            if judgment is None or not supplied.intersection(judgment["evidence_refs"]):
                errors.append("changed judgment did not cite the newly bound source")
            expected_source = "seller_claim" if binding["kind"] == "seller_reply" else "user_statement"
            allowed_sources = {expected_source}
            # Combining a card with a user observation or reasoning about a
            # later explanation can legitimately be labelled inference. The
            # individual new statement reference is still mandatory.
            if judgment and expected_source == "user_statement" and (judgment["status"] == "CONFLICT" or number == 6):
                allowed_sources.add("inference")
            if judgment and judgment["source_type"] not in allowed_sources:
                errors.append("bound claim/observation source type lost")
    ranked = {c["listing_id"] for c in comparison["result"]["ranked_candidates"]}
    if ids["D"] in ranked or (number == 1 and ids["C"] in ranked) or (number >= 3 and ids["A"] in ranked) or (number >= 4 and ids["B"] in ranked):
        errors.append("fixture hard failure present in current comparison")
    if number == 8:
        if status("C", "originality") not in {"NOT_MET", "CONFLICT"} or ranked:
            errors.append("final repair admission did not withdraw shortlist")
    return errors


def run_journey(config: AppConfig, runtime: TracedRuntime, *, seed: int, report: dict,
                save, turn_timeout: float = 480) -> dict:
    """Invoke normal service creation/followups and normal coordinator workers."""
    if turn_timeout <= 0:
        raise ValueError("turn_timeout must be positive")
    service = ConversationService(config)
    created = service.create_task(GOAL)
    task_id = created.task.id
    ids = seed_saved_candidates(config, task_id, seed)
    report.update(task_id=task_id, candidate_legend=ids, rounds=[], state="running")
    save()
    previous = None
    for number, name in enumerate(ROUND_NAMES, 1):
        service = ConversationService(config)
        turn = journey_turn(number, ids)
        operation = created.operation if number == 1 else service.send_message(task_id, turn.message, turn.binding).operation
        record = dict(number=number, name=name, message=turn.message, binding=turn.binding,
                      operation_id=operation.id, state="running", call_start=len(runtime.calls))
        report["rounds"].append(record)
        save()
        print(f"seed={seed} round={number}/8 {name}: running", flush=True)
        coordinator = OperationCoordinator(service, runtime)
        started = time.monotonic()
        try:
            coordinator.start(operation.id)
            while True:
                operation = service.store.get_operation(operation.id)
                if operation.state not in {"queued", "running"}:
                    break
                if time.monotonic() - started >= turn_timeout:
                    coordinator.cancel(operation.id)
                    record["turn_timeout"] = True
                    break
                time.sleep(.1)
        finally:
            coordinator.shutdown()
        restored = restored_snapshot(config, task_id)
        operation = service.store.get_operation(operation.id)
        errors = check_journey_round(number, restored, ids, previous) if operation.state == "completed" else ["operation did not complete"]
        record.update(state="checks_failed" if errors else "checks_passed", checks=errors, snapshot=restored,
                      operation=service.get_operation(operation.id).model_dump(mode="json"),
                      call_end=len(runtime.calls), duration_seconds=round(time.monotonic() - started, 3))
        save()
        print(f"seed={seed} round={number}: {record['state']} ({operation.state})", flush=True)
        if errors:
            break
        previous = restored
    report.update(state="checks_passed_manual_review_pending" if len(report["rounds"]) == 8 and not errors else "incomplete_or_failed",
                  not_run=list(ROUND_NAMES[len(report["rounds"]):]), calls_count=len(runtime.calls))
    save()
    return report


def audit_saved_journey(report: dict) -> dict:
    """Recheck trace signatures and restored snapshots, with zero model calls."""
    if report.get("mode") != "real_model_service_journey" or report.get("suite_version") != JOURNEY_VERSION:
        raise ValueError("unsupported journey report")
    ids = report["candidate_legend"]
    if set(ids) != set("ABCD") or len(set(ids.values())) != 4 or any(type(i) is not int or i <= 0 for i in ids.values()):
        raise ValueError("invalid candidate legend")
    rounds, previous, last_call = [], None, 0
    for index, row in enumerate(report["rounds"], 1):
        if index > 8 or row["number"] != index or row["name"] != ROUND_NAMES[index - 1]:
            raise ValueError("missing, repeated or reordered round")
        if "snapshot" not in row:
            rounds.append(dict(number=index, state="not_evaluated", checks=["incomplete saved round"]))
            break
        errors = check_journey_round(index, row["snapshot"], ids, previous)
        if row["operation"]["operation"]["state"] != "completed":
            errors.append("operation did not complete")
        if row["call_start"] != last_call or not row["call_start"] < row["call_end"] <= len(report["calls"]):
            errors.append("call trace coverage mismatch")
        for call in report["calls"][row["call_start"]:row["call_end"]]:
            request = CodexRequest.model_validate_json(json.dumps(call["request"]))
            if (call["request_signature"] != signature(request.model_dump(mode="json"))
                    or call["prompt_signature"] != signature(CodexRuntime._build_prompt(request))):
                errors.append("changed call request or prompt signature")
            if call["operation_id"] != row["operation_id"] or call["state"] != "returned":
                errors.append("call not returned for this operation")
        last_call = row["call_end"]
        rounds.append(dict(number=index, state="checks_failed" if errors else "checks_passed", checks=errors))
        previous = row["snapshot"]
    complete = len(rounds) == 8 and all(r["state"] == "checks_passed" for r in rounds) and last_call == len(report["calls"])
    return dict(mode="journey_audit_no_model_calls", calls=0, suite_version=JOURNEY_VERSION,
                checker_version=CHECKER_VERSION, source_checker_version=report.get("checker_version", "journey-checks-v1"),
                source_report_signature=signature(report), seed=report["seed"], rounds=rounds,
                state="checks_passed_manual_review_pending" if complete else "incomplete_or_failed",
                quality_verified=False, manual_review="pending")
