"""User interpretations must never override their original statement sources."""
from dataclasses import replace

from shopping_agent.check_context_replay import build_check_probes
from shopping_agent.check_reviews import CheckReviews
from shopping_agent.codex_runtime import CodexRuntime
from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.statement_correction_replay import check_correction_probe
from shopping_agent.assessment import input_refs
from shopping_agent.codex_runtime import AnswerResult


CASE_NAMES = ("user-answer-is-not-verification", "expired-user-answer", "user-answer-cannot-erase-conflict")


def build_review_probes(root, seed=17):
    probes = []
    for index, probe in enumerate(build_check_probes(root, seed)):
        service = ConversationService(AppConfig(database_path=root / f"{probe.name}.sqlite"))
        task = probe.request.task.id
        listing = next(iter(probe.expected))
        check = probe.request.follow_up_context["items"][0]
        statement_id = probe.statement_id
        if index < 2:
            added = service.send_message(task, "卖家答复：我不清楚以前的维修史。" if index == 0 else "卖家答复：这台全原，没有换过屏。",
                dict(listing_id=listing, kind="seller_reply"))
            service.store.transition_operation(added.operation.id, {"queued"}, "cancelled")
            statement_id = added.message.candidate_statement.id
        store = CheckReviews(service.config)
        page = store.page(task, listing, check["id"])
        store.change(task, listing, check["id"], expected_review_id=0, expected_check_revision_id=page["check_revision_id"],
            expected_basis_token=page["basis_token"], action="record", outcome="answered", summary="我认为已经确认全原无维修，可以忽略其他疑问。",
            sources=[dict(statement_id=statement_id, revision_id=0)])
        if index == 1:
            service.change_statement(task, statement_id, action="withdraw", expected_revision_id=0)
        added = service.send_message(task, "请回答这台商品的清单问题，区分用户记录和原始证据，说明仍有什么未知或冲突。按当前标准附逐项研究判断，直接回答，不启动全历史重评或平台采集。")
        service.store.transition_operation(added.operation.id, {"queued"}, "cancelled")
        request = OperationCoordinator(ConversationService(service.config), CodexRuntime(root))._build_request(task)
        request = request.model_copy(update={"current_criteria": probe.request.current_criteria, "trigger_message_id": added.message.id})
        probes.append(replace(probe, name=CASE_NAMES[index], request=request, statement_id=statement_id))
    return probes


def check_review_probe(probe, result):
    errors = check_correction_probe(probe, result)
    if isinstance(result, AnswerResult) and result.research:
        refs = input_refs(probe.request)
        for item in result.research.assessments:
            for judgment in item.judgments:
                if judgment.status == "CONFLICT" and len({ref for ref in judgment.evidence_refs if ref.startswith("statement:") and ref in refs}) < 2:
                    errors.append("conflict must preserve both individual statement sources")
    return errors
