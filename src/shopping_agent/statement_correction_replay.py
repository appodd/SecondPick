"""Synthetic correction probes; expected judgments never enter model input.

Uses real message/correction/context services, then a single review phase per
case with fixture criteria. This is not a persisted multi-turn model journey.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from shopping_agent.assessment import Criterion, input_refs
from shopping_agent.codex_runtime import AnswerResult, CodexRequest, CodexRuntime
from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.db import add_listing_snapshot, attach_run_to_task, connect, create_search_run, upsert_listing
from shopping_agent.operation_coordinator import OperationCoordinator


CASE_NAMES = ("withdrawn-repair-claim", "rebound-repair-claim", "corrected-user-observation")
GOAL = "买256GB二手手机，预算不超过4300元，必须全原无维修。只使用已保存证据，不访问网站或执行工具。"


@dataclass(frozen=True)
class CorrectionProbe:
    name: str
    request: CodexRequest
    expected: dict[int, tuple[str, str | None]]
    statement_id: int


def build_correction_probes(root: Path, seed: int = 17) -> list[CorrectionProbe]:
    probes = []
    for name in CASE_NAMES:
        config = AppConfig(database_path=root / f"{name}.sqlite")
        service = ConversationService(config)
        created = service.create_task(GOAL)
        # Context preparation only: cancel queued analysis, never fabricate
        # successful model answers, standards, assessments or comparisons.
        service.store.transition_operation(created.operation.id, {"queued"}, "cancelled")
        task_id = created.task.id
        order = ["A", "B"]
        random.Random(seed).shuffle(order)
        ids = {}
        with connect(config.database_path) as conn:
            run = create_search_run(conn, GOAL, "上海")
            attach_run_to_task(conn, task_id, run)
            for label in order:
                listing_id = upsert_listing(conn, "xianyu", f"https://example.test/correction/{seed}/{label}")
                ids[label] = listing_id
                add_listing_snapshot(conn, listing_id, run, title="虚构手机256GB", price_text="4000",
                                     location="上海", description="卖家标称256GB，维修史未说明，未提供部件页面或维修记录。")
        a, b = ids["A"], ids["B"]
        text = (f"商品#{a}卖家明确答复：去年换过第三方屏幕。" if name != "corrected-user-observation" else
                f"我现场查看商品#{a}的本机维修单，单上写着第三方换屏；这是我的观察记录，未经独立核验。")
        added = service.send_message(task_id, text, dict(listing_id=a, kind="seller_reply"))
        service.store.transition_operation(added.operation.id, {"queued"}, "cancelled")
        statement = added.message.candidate_statement
        if name == "withdrawn-repair-claim":
            service.change_statement(task_id, statement.id, action="withdraw", expected_revision_id=0)
            expected = {a: ("UNKNOWN", None), b: ("UNKNOWN", None)}
        else:
            target = b if name == "rebound-repair-claim" else a
            kind = "seller_reply" if name == "rebound-repair-claim" else "user_observation"
            service.change_statement(task_id, statement.id, action="rebind", expected_revision_id=0,
                                     listing_id=target, kind=kind)
            expected = {a: ("UNKNOWN", None), b: ("UNKNOWN", None)}
            expected[target] = ("NOT_MET", "seller_claim" if kind == "seller_reply" else "user_statement")
        service = ConversationService(config)  # Read persisted corrections afresh.
        coordinator = OperationCoordinator(service, CodexRuntime(root))
        try:
            request = coordinator._build_request(task_id)
        finally:
            coordinator.shutdown()
        criteria = tuple(Criterion(criterion_id=key, description=text, priority="hard",
                                   source_message_ids=[created.message.id]) for key, text in (
            ("budget", "预算不超过4300元"), ("capacity", "256GB"), ("originality", "必须全原无维修")))
        request = request.model_copy(update={"phase": "review_batch", "current_criteria": criteria,
                                              "trigger_message_id": added.message.id})
        probes.append(CorrectionProbe(name, request, expected, statement.id))
    return probes


def check_correction_probe(probe: CorrectionProbe, result) -> list[str]:
    if not isinstance(result, AnswerResult) or result.research is None:
        return ["expected structured review answer"]
    errors = []
    if result.research.criteria != list(probe.request.current_criteria):
        errors.append("changed fixture criteria")
    actual = {a.listing_id: a for a in result.research.assessments}
    if set(actual) != set(probe.expected):
        errors.append("assessment coverage mismatch")
    refs = input_refs(probe.request)
    for listing_id, (status, source) in probe.expected.items():
        item = actual.get(listing_id)
        if item is None:
            continue
        judgments = {j.criterion_id: j for j in item.judgments}
        expected = {"budget": "MET", "capacity": "MET", "originality": status}
        if {key: j.status for key, j in judgments.items()} != expected:
            errors.append(f"{listing_id}: fixture status mismatch")
        for judgment in item.judgments:
            if any(ref not in refs or refs[ref]["listing_id"] != listing_id for ref in judgment.evidence_refs):
                errors.append(f"{listing_id}: invalid or cross-candidate reference")
        originality = judgments.get("originality")
        if originality and source:
            if originality.source_type != source:
                errors.append(f"{listing_id}: corrected source type ignored")
            if not any(ref.startswith("statement:") and ref in refs
                       and refs[ref]["data"].get("statement_id") == probe.statement_id
                       and refs[ref]["listing_id"] == listing_id for ref in originality.evidence_refs):
                errors.append(f"{listing_id}: missing corrected individual statement")
        if status == "NOT_MET" and (item.conclusion != "not_met" or listing_id in result.candidate_ids):
            errors.append(f"{listing_id}: hard failure proposed or misclassified")
    if not set(result.candidate_ids) <= set(probe.expected):
        errors.append("invented candidate")
    return errors


def correction_manifest(probe: CorrectionProbe) -> dict:
    return dict(name=probe.name, request=probe.request.model_dump(mode="json"),
                oracle={str(i): dict(originality=status, source_type=source)
                        for i, (status, source) in probe.expected.items()}, statement_id=probe.statement_id)
