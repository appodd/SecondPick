"""Synthetic chat probes for saved checklists; no platform or product database."""
from pathlib import Path

from shopping_agent.candidate_checks import CandidateChecks
from shopping_agent.codex_runtime import AnswerResult, CodexRuntime
from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.db import add_listing_snapshot, attach_run_to_task, connect, create_search_run, upsert_listing
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.statement_correction_replay import CorrectionProbe, check_correction_probe, GOAL
from shopping_agent.assessment import Criterion, input_refs


CASE_NAMES = ("question-is-not-evidence", "withdrawn-linked-claim", "linked-replies-conflict")


def build_check_probes(root: Path, seed=17):
    probes = []
    for name in CASE_NAMES:
        service = ConversationService(AppConfig(database_path=root / f"{name}.sqlite"))
        created = service.create_task(GOAL)
        task = created.task.id
        service.store.transition_operation(created.operation.id, {"queued"}, "cancelled")
        with connect(service.config.database_path) as conn:
            run = create_search_run(conn, GOAL, "上海")
            attach_run_to_task(conn, task, run)
            listing = upsert_listing(conn, "xianyu", f"https://example.test/checks/{seed}/{name}")
            add_listing_snapshot(conn, listing, run, title="虚构手机256GB", price_text="4000", location="上海",
                description="卖家标称256GB，维修史未说明，未提供部件页面或维修记录。")
        checks = CandidateChecks(service.config)
        item = checks.create(task, listing, question="这台手机是否全原、有没有换屏？", request_key="probe-check-key")
        statement_id = 0
        if name != "question-is-not-evidence":
            reply = service.send_message(task, "卖家答复：一直全原，没有换屏。", dict(listing_id=listing, kind="seller_reply"))
            service.store.transition_operation(reply.operation.id, {"queued"}, "cancelled")
            statement_id = reply.message.candidate_statement.id
            checks.change(task, listing, item["id"], expected_revision_id=0, state="evidence_linked",
                statement_id=statement_id, statement_revision_id=0, note="已记录卖家说法，仍需核对实物与记录。")
            if name == "withdrawn-linked-claim":
                service.change_statement(task, statement_id, action="withdraw", expected_revision_id=0)
            else:
                added = service.send_message(task, "卖家后来改口：去年换过第三方屏幕。", dict(listing_id=listing, kind="seller_reply"))
                service.store.transition_operation(added.operation.id, {"queued"}, "cancelled")
        added = service.send_message(task, "请直接回答这台商品的待核实问题：现有哪些说法、能否回答、还需要什么证据？请按当前标准附逐项研究判断，保留不确定性；不启动全历史重评或平台采集。")
        service.store.transition_operation(added.operation.id, {"queued"}, "cancelled")
        request = OperationCoordinator(ConversationService(service.config), CodexRuntime(root))._build_request(task)
        criteria = tuple(Criterion(criterion_id=key, description=text, priority="hard", source_message_ids=[created.message.id])
            for key, text in (("budget", "预算不超过4300元"), ("capacity", "256GB"), ("originality", "必须全原无维修")))
        request = request.model_copy(update={"current_criteria": criteria, "trigger_message_id": added.message.id})
        status = "CONFLICT" if name == "linked-replies-conflict" else "UNKNOWN"
        probes.append(CorrectionProbe(name, request, {listing: (status, "seller_claim" if status == "CONFLICT" else None)}, statement_id))
    return probes


def check_check_probe(probe, result):
    errors = check_correction_probe(probe, result)
    if not isinstance(result, AnswerResult) or not result.research:
        return errors
    # Semantic prose still needs human review; do not accept keywords as proof.
    refs = input_refs(probe.request)
    for item in result.research.assessments:
        for judgment in item.judgments:
            if judgment.criterion_id == "originality":
                if probe.name == "linked-replies-conflict" and len({ref for ref in judgment.evidence_refs if ref.startswith("statement:") and ref in refs}) < 2:
                    errors.append("conflict must preserve both individual replies")
                if probe.name != "linked-replies-conflict" and judgment.source_type != "missing":
                    errors.append("question or withdrawn link cannot establish a factual source")
    return errors
