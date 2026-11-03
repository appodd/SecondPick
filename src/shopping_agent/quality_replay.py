"""Synthetic, independent model probes. Oracles never enter model requests.

This is not the eight-turn product acceptance test or a semantic quality score.
The production runtime is used unchanged; no database or platform is opened.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from shopping_agent.assessment import Criterion, input_refs, signature
from shopping_agent.codex_runtime import CodexRequest, CodexResult, CodexRuntime


SUITE_VERSION = "offline-probes-v2"


@dataclass(frozen=True)
class Probe:
    name: str
    request: CodexRequest
    expected_type: str
    statuses: dict[int, dict[str, str]] = field(default_factory=dict)
    required_statement_ids: dict[int, set[int]] = field(default_factory=dict)
    eligible_ids: frozenset[int] = frozenset()
    claim_unknown_allowed: frozenset[int] = frozenset()


def build_probes(seed: int = 17) -> list[Probe]:
    """Fixed facts, randomized identities/order; no expected answers in input."""
    rng = random.Random(seed)
    ids = rng.sample(range(1000, 9000), 4)
    goal = "买256GB手机，预算不超过4300元，必须全原无维修。"
    criteria = tuple(Criterion(criterion_id=key, description=text, priority="hard",
                              source_message_ids=[1]) for key, text in (
        ("budget", "预算不超过4300元"), ("capacity", "256GB"), ("originality", "必须全原无维修")))

    def request(message, **changes):
        data = dict(task=dict(id=1, original_goal=goal, effective_goal=goal),
                    messages=({"id": 1, "task_id": 1, "role": "user", "content": goal},
                              {"id": 2, "task_id": 1, "role": "user", "content": message}),
                    candidates=(), evidence=(), runs=(), allowed_listing_ids=frozenset(),
                    trigger_message_id=2, requirement_sources={"task_goal": goal})
        data.update(changes)
        return CodexRequest(**data)

    probes = [
        Probe("hypothetical-budget", request("如果预算加500，会有什么不同？先讨论，别改要求。",
              allow_preference_update=True), "answer"),
        Probe("explicit-budget", request("把预算提高到4800元，其他要求保持。",
              allow_preference_update=True), "preference_update"),
        Probe("unbound-seller", request("他说从没修过，可以放心买吗？", allow_preference_update=False), "answer"),
    ]
    facts = [
        (4200, 256, "放心没问题，支持验货；未提供维修记录。", "UNKNOWN"),
        (4200, 128, "卖家称全原无维修，未经独立核实。", "MET"),
        (4500, 256, "卖家称全原无维修，未经独立核实。", "MET"),
        (4100, 256, "卖家称全原无维修，未经独立核实。", "MET"),
    ]
    cards, expected = [], {}
    for listing_id, (price, capacity, repair, state) in zip(ids, facts):
        cards.append(dict(task_id=1, listing_id=listing_id, data={"evidence_json":
            json.dumps(dict(price=price, capacity_gb=capacity,
                                         seller_description=repair), ensure_ascii=False)}))
        expected[listing_id] = dict(budget="MET" if price <= 4300 else "NOT_MET",
                                   capacity="MET" if capacity == 256 else "NOT_MET", originality=state)
    rng.shuffle(cards)
    batch = request("仅根据提供的虚构快照逐项评估，不执行工具或访问网站。",
                    phase="review_batch", current_criteria=criteria,
                    candidates=tuple(cards), allowed_listing_ids=frozenset(ids))
    probes.append(Probe("fixed-facts", batch, "answer", expected,
                        eligible_ids=frozenset((ids[0], ids[3])),
                        claim_unknown_allowed=frozenset(ids[1:])))
    statements = [dict(id=i, source_message_id=i + 10, kind="seller_reply",
                       statement_text=text, attribution="user_relayed_seller_claim",
                       independently_verified=False) for i, text in (
                           (1, "卖家答复：全原无维修，从没换过屏。"),
                           (2, "卖家后来说：确实换过第三方屏幕，之前说错了。"))]
    # Deliberately unresolved: the later message does not explain the first
    # claim's origin or provide independently checked repair records.
    statements[1]["statement_text"] = "用户转述另一段卖家答复：换过第三方屏幕。两段说法尚未核实，未说明哪段正确。"
    conflict_data = batch.model_dump()
    conflict_data.update({
        "candidates": (next(c for c in batch.candidates if c.listing_id == ids[0]),),
        "allowed_listing_ids": frozenset((ids[0],)),
        "evidence": (dict(task_id=1, listing_id=ids[0], data={"evidence_json": json.dumps(
            dict(user_statements=statements, user_statement_count=2, user_statements_truncated=False),
            ensure_ascii=False)}),),
    })
    conflict = CodexRequest.model_validate(conflict_data)
    probes.append(Probe("conflicting-seller-replies", conflict, "answer",
                        {ids[0]: dict(budget="MET", capacity="MET", originality="CONFLICT")},
                        {ids[0]: {1, 2}}, frozenset((ids[0],))))
    # The nomination/comparison probes use explicitly synthetic saved judgments.
    # They test reasoning over a bounded snapshot, not end-to-end persistence.
    assessments = []
    for listing_id in ids:
        judgments = [dict(criterion_id=key, status=state, reason="虚构已保存判断",
                          source_type="missing" if state == "UNKNOWN" else "seller_claim",
                          evidence_refs=[] if state == "UNKNOWN" else [next(
                              ref for ref, item in input_refs(batch).items() if item["listing_id"] == listing_id)])
                     for key, state in expected[listing_id].items()]
        assessments.append(dict(assessment_id=listing_id + 10000, listing_id=listing_id,
            judgments=judgments, conclusion="not_met" if "NOT_MET" in expected[listing_id].values()
            else "conditional" if "UNKNOWN" in expected[listing_id].values() else "consider",
            summary="合成的已保存判断，用于离线阶段探针"))
    rng.shuffle(assessments)
    for phase, result_type in (("nomination", "nomination"), ("comparison", "comparison")):
        req = request("根据给定已保存判断选择值得比较的候选，保留未知，不使用工具。",
            phase=phase, current_criteria=criteria, allowed_listing_ids=frozenset(ids),
            review_context={"assessments": assessments, "previous_comparison": None},
            scope_coverage=dict(scope_count=4, assessed_count=4, pending_count=0, truncated=False))
        probes.append(Probe(phase, req, result_type, eligible_ids=frozenset((ids[0], ids[3]))))
    return probes


def check_probe(probe: Probe, result: CodexResult) -> list[str]:
    """Check explicit fixture facts/structure only; prose requires human review."""
    errors = []
    if result.type != probe.expected_type:
        return [f"expected {probe.expected_type}, received {result.type}"]
    request = probe.request
    if result.type == "answer" and result.research is not None:
        refs = input_refs(request)
        for item in result.research.assessments:
            if item.listing_id not in request.allowed_listing_ids:
                errors.append("assessment invented a candidate outside input")
            for judgment in item.judgments:
                if any(ref not in refs or refs[ref]["listing_id"] != item.listing_id for ref in judgment.evidence_refs):
                    errors.append("assessment used a foreign or nonexistent reference")
    if result.type == "preference_update":
        if result.source_message_id != 2 or result.base_revision_id != 0:
            errors.append("wrong preference source/version")
        # These tokens check retention only; added/removed prose needs review.
        if not all(token in result.effective_goal for token in ("4800", "256", "全原", "维修")):
            errors.append("explicit revised goal lost fixture requirements")
    if probe.statuses:
        research = getattr(result, "research", None)
        if research is None:
            return errors + ["missing research"]
        if research.criteria != list(request.current_criteria):
            errors.append("changed supplied criteria")
        actual = {a.listing_id: a for a in research.assessments}
        if set(actual) != set(probe.statuses):
            errors.append("assessment coverage mismatch")
        refs = input_refs(request)
        for listing_id, expected in probe.statuses.items():
            item = actual.get(listing_id)
            if item is None:
                continue
            judgments = {j.criterion_id: j for j in item.judgments}
            allowed = {key: {status} for key, status in expected.items()}
            # A specific but unverified seller assertion may be represented as
            # MET/seller_claim, or conservatively UNKNOWN/seller_claim. Neither
            # representation establishes independent truth. Missing claims may
            # never use this exception. v1 was overstrict here; retain its run.
            if listing_id in probe.claim_unknown_allowed:
                allowed["originality"].add("UNKNOWN")
            if set(judgments) != set(allowed) or any(j.status not in allowed.get(key, set()) for key, j in judgments.items()):
                errors.append(f"{listing_id}: fixture status mismatch")
            for judgment in item.judgments:
                if any(ref not in refs or refs[ref]["listing_id"] != listing_id for ref in judgment.evidence_refs):
                    errors.append(f"{listing_id}: invalid or cross-candidate reference")
                if judgment.source_type in {"image_observation", "user_statement"}:
                    errors.append(f"{listing_id}: unsupported source type")
                if (judgment.status not in {"UNKNOWN", "CONFLICT"} or (
                        judgment.criterion_id == "originality" and listing_id in probe.claim_unknown_allowed)) and not any(
                        ref in refs and refs[ref]["listing_id"] == listing_id and ref.startswith("card:")
                        for ref in judgment.evidence_refs):
                    errors.append(f"{listing_id}: missing supporting fixture card")
            originality = judgments.get("originality")
            if originality and (originality.status == "MET" or listing_id in probe.claim_unknown_allowed) and originality.source_type != "seller_claim":
                errors.append(f"{listing_id}: seller originality claim misattributed")
            if originality and listing_id in probe.required_statement_ids:
                statements = {refs[ref]["data"].get("statement_id") for ref in originality.evidence_refs
                              if ref in refs and ref.startswith("statement:")}
                if not probe.required_statement_ids[listing_id] <= statements:
                    errors.append(f"{listing_id}: missing individual conflicting statements")
                if originality.source_type != "seller_claim":
                    errors.append(f"{listing_id}: relayed seller claim misattributed")
        if not set(result.candidate_ids) <= probe.eligible_ids:
            errors.append("hard failure proposed for comparison")
    if result.type in {"nomination", "comparison"}:
        entries = result.candidates if result.type == "nomination" else result.ranked_candidates
        saved = {a["listing_id"]: a for a in request.review_context["assessments"]}
        if not entries:
            errors.append("omitted all eligible fixture candidates")
        for entry in entries:
            if entry.listing_id not in probe.eligible_ids:
                errors.append("hard failure nominated/ranked")
            if entry.listing_id not in saved or entry.assessment_id != saved[entry.listing_id]["assessment_id"]:
                errors.append("wrong saved assessment reference")
            elif any(j["status"] in {"UNKNOWN", "CONFLICT"} for j in saved[entry.listing_id]["judgments"]) and not entry.uncertainties:
                errors.append("unresolved judgment lost uncertainty")
        if result.type == "comparison":
            if {(c.listing_id, c.assessment_id, c.kind) for c in result.changes} != {
                    (e.listing_id, e.assessment_id, "entered") for e in entries}:
                errors.append("incorrect first-comparison changes")
    return errors


def probe_manifest(probe: Probe) -> dict:
    """Human-review artifact; do not pass the manifest/oracle to the runtime."""
    return dict(name=probe.name, request=probe.request.model_dump(mode="json"),
                request_signature=signature(probe.request.model_dump(mode="json")),
                prompt_signature=signature(CodexRuntime._build_prompt(probe.request)),
                # This report is outside the disposable runtime root. These
                # expectations are never appended to a model prompt.
                oracle=dict(expected_type=probe.expected_type, statuses=probe.statuses,
                            required_statement_ids={str(k): sorted(v) for k, v in probe.required_statement_ids.items()},
                            eligible_ids=sorted(probe.eligible_ids),
                            claim_unknown_allowed=sorted(probe.claim_unknown_allowed)))


def rescore_report(report: dict, runtime: CodexRuntime) -> dict:
    """Recheck preserved outputs without inference; never replace raw evidence."""
    if report.get("mode") != "real_model":
        raise ValueError("only real-model reports can be rescored")
    selected = report.get("selected_cases")
    if type(selected) is not int or not 0 < selected <= len(build_probes()):
        raise ValueError("report must declare its selected case count")
    probes = {p.name: p for p in build_probes(report["seed"])}
    records, seen = [], set()
    for raw in report["cases"]:
        name = raw["name"]
        if name in seen or name not in probes:
            raise ValueError("duplicate or unknown probe")
        seen.add(name)
        p = probes[name]
        manifest = probe_manifest(p)
        if (raw["request"] != manifest["request"] or raw["request_signature"] != manifest["request_signature"]
                or raw["prompt_signature"] != manifest["prompt_signature"]):
            raise ValueError("saved input differs from current probe/prompt; cannot rescore")
        record = dict(manifest, original_state=raw["state"], state="not_evaluated", manual_review="pending")
        if raw["state"] in {"checks_passed", "checks_failed"}:
            result = runtime.parse_result(json.dumps(raw["result"]), allowed_listing_ids=set(p.request.allowed_listing_ids))
            errors = check_probe(p, result)
            record.update(state="checks_failed" if errors else "checks_passed", checks=errors,
                          result=result.model_dump(mode="json"))
        records.append(record)
    passed = sum(r["state"] == "checks_passed" for r in records)
    complete = len(records) == selected and passed == selected
    return dict(mode="rescore_no_model_calls", calls=0, suite_version=SUITE_VERSION,
                original_suite_version=report["suite_version"], original_state=report["state"],
                source_report_signature=signature(report), seed=report["seed"],
                quality_verified=False, manual_review="pending", cases=records,
                state="checks_passed_manual_review_pending" if complete else "incomplete_or_failed",
                checks_passed=passed, selected_cases=selected,
                evaluated_cases=sum(r["state"] != "not_evaluated" for r in records))
