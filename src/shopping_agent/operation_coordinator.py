from __future__ import annotations

import json
import threading

from shopping_agent.codex_runtime import (
    AnswerResult, CodexRuntime, CodexCancelledError, CodexTimeoutError,
    InvalidCodexResult, RUNTIME_STAGES,
    PreferenceUpdateResult,
)
from shopping_agent.conversation_service import ConversationService
from shopping_agent.conversation_store import (
    ActionRequestInput, InvalidActionRequestError, OperationStateError, PreferenceRevisionConflictError,
)
from shopping_agent.web.services import WorkbenchService
from shopping_agent.assessment import Criterion, evidence_signature, input_refs, read_standards
from shopping_agent.check_context import check_signature, follow_up_context, require_current_checks, CheckContextChangedError
from shopping_agent.db import connect
from shopping_agent.candidate_context import build_candidate_index, build_candidate_evidence
from shopping_agent.history_review import (HistoryReviewResult, ComparisonResult, NominationResult, assessed_items,
    comparison_context, nomination_context, nomination_progress, ReviewInputChangedError)


class OperationCoordinator:
    """Own live workers; SQLite owns every user-visible result."""

    def __init__(self, service: ConversationService, runtime: CodexRuntime):
        self.service = service
        self.store = service.store
        self.runtime = runtime
        self._lock = threading.RLock()
        self._workers: dict[int, threading.Thread] = {}
        self._closed = False

    def start(self, operation_id: int) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Coordinator is shutting down")
            if operation_id in self._workers:
                return
            if self.store.get_operation(operation_id).state != "queued":
                return
            worker = threading.Thread(target=self._run, args=(operation_id,), daemon=True)
            self._workers[operation_id] = worker
            worker.start()

    def _stage(self, operation_id: int, stage: str) -> None:
        with self._lock:
            if self.store.get_operation(operation_id).state != "running":
                # Also closes the cancellation gap before the runner registers a process.
                raise CodexCancelledError("Operation stopped")
            if stage not in (*RUNTIME_STAGES, "preparing_context"):
                raise ValueError("Unknown runtime stage")
            self.store.append_event(operation_id, "stage", {"stage": stage})

    def _build_request(self, task_id: int, listing_ids: list[int] | None = None):
        # Guard both context construction and eventual publication against evidence writes.
        with connect(self.service.config.database_path) as conn:
            dependency_signature = evidence_signature(conn, task_id)
            standards = read_standards(conn, task_id)
            checks_signature = check_signature(conn, task_id)
            recent_check_ids = [row[0] for row in conn.execute(
                "SELECT listing_id FROM candidate_check_current WHERE task_id=? AND effective_state!='dismissed' GROUP BY listing_id ORDER BY MAX(id) DESC LIMIT 20", (task_id,))]
        workbench = WorkbenchService(self.service.config)
        detail = workbench.get_task(task_id, include_research=False, history_limit=20)
        task = detail.task
        task_context = task.model_dump(mode="json")
        task_context["preference_revision_id"] = detail.preference_revision_id
        candidates = []
        evidence = []
        messages = self.service.get_messages(task_id, limit=100).items
        recent_candidate_ids = list(dict.fromkeys(
            listing_id for message in reversed(messages) for listing_id in
            ([message.candidate_statement.listing_id] if message.candidate_statement and message.candidate_statement.status == "active" else message.candidate_ids)
        ))
        all_cards = build_candidate_index(self.service.config, task_id=task_id)["candidates"] if detail.runs else []
        index = {card["listing_id"]: card for card in all_cards}
        if listing_ids is not None:
            if len(listing_ids) > 20 or len(set(listing_ids)) != len(listing_ids) or not set(listing_ids) <= set(index):
                raise InvalidCodexResult("Invalid history review batch scope.")
            selected = [index[i] for i in listing_ids]
        else:
            # Bounded chat context plus explicit task-scoped recent shortlist supplement.
            supplements = [i for i in dict.fromkeys([*recent_check_ids, *recent_candidate_ids]) if i in index][:20]
            selected_ids = list(dict.fromkeys([*list(index)[:200], *supplements]))
            selected = [index[i] for i in selected_ids]
        for card in selected:
            candidates.append({"task_id": task_id, "listing_id": card["listing_id"],
                               "evidence_json": json.dumps(card, ensure_ascii=False)})
        allowed_ids = {candidate["listing_id"] for candidate in candidates}
        captured_ids = [card["listing_id"] for card in selected if card["detail_status"] == "captured"]
        evidence_ids = [i for i in dict.fromkeys([*recent_check_ids, *recent_candidate_ids, *captured_ids, *(c["listing_id"] for c in selected)]) if i in allowed_ids][:20]
        if evidence_ids:
            items = build_candidate_evidence(self.service.config, task_id=task_id, listing_ids=evidence_ids)["candidates"]
            evidence = [{"task_id": task_id, "listing_id": item["listing_id"],
                         "evidence_json": json.dumps(item, ensure_ascii=False)} for item in items]
        from shopping_agent.match_semantics import MATCH_SEMANTICS
        request = self.runtime.build_request(
            task=task_context, messages=[{"task_id": task_id, "role": "system", "content": MATCH_SEMANTICS}, *messages],
            candidates=candidates, evidence=evidence,
            runs=[{"task_id": task_id, "run_id": run.run_id, "run_json": run.model_dump_json()} for run in detail.runs[-20:]],
            allowed_listing_ids=allowed_ids,
        )
        with connect(self.service.config.database_path) as conn:
            if dependency_signature != evidence_signature(conn, task_id):
                raise InvalidCodexResult("Evidence changed while building the input snapshot.")
            require_current_checks(conn, task_id, checks_signature)
            checks = follow_up_context(conn, task_id, allowed_ids, input_refs(request)) if listing_ids is None else {}
            require_current_checks(conn, task_id, checks_signature)
        current = next((s for s in standards
                        if s["preference_revision_id"] == request.task.preference_revision_id), None)
        previous = standards[-1] if standards else None
        requirement_sources = {"task_goal": {"kind": "original_goal", "text": request.task.original_goal}}
        relevant_revision_ids = {request.task.preference_revision_id}
        for standard in (current, previous):
            if standard:
                for criterion in standard["criteria"]:
                    relevant_revision_ids.update(int(ref.split(":")[1]) for ref in criterion.get("source_refs", []) if ref.startswith("preference_revision:"))
        with connect(self.service.config.database_path) as conn:
            for revision_id in relevant_revision_ids:
                revision = conn.execute("SELECT id,effective_goal,user_message FROM task_preference_revisions WHERE task_id=? AND id=?", (task_id, revision_id)).fetchone()
                if revision:
                    requirement_sources[f"preference_revision:{revision['id']}"] = {
                        "kind": "preference_revision", "text": revision["effective_goal"], "user_message": revision["user_message"],
                    }
        return request.model_copy(update={
            "current_criteria": tuple(Criterion.model_validate(c) for c in current["criteria"]) if current else (),
            "previous_criteria": tuple(Criterion.model_validate(c) for c in previous["criteria"]) if previous else (),
            "evidence_signature": dependency_signature,
            "follow_up_context": checks,
            "check_context_signature": checks_signature if listing_ids is None else "",
            "scope_coverage": {"scope_count": len(all_cards), "input_candidate_count": len(selected),
                               "truncated": len(selected) < len(all_cards)},
            "requirement_sources": requirement_sources,
            "runtime_config": {"adapter": type(self.runtime).__name__,
                "model": "CLI configured default; not resolved by service",
                "timeout_seconds": getattr(self.runtime, "timeout_seconds", None)},
        })

    def _allow_preference_update(self, operation):
        # Earlier user messages may be outside the recent window in long histories.
        with connect(self.service.config.database_path) as conn:
            return self.store._preference_update_allowed(conn, operation.task_id, operation.user_message_id)

    def _runtime_result(self, operation_id, request):
        self._stage(operation_id, "preparing_context")
        result = self.runtime.run(request, run_id=operation_id,
                                  stage_callback=lambda stage: self._stage(operation_id, stage))
        raw = result.model_dump_json() if hasattr(result, "model_dump_json") else json.dumps(result)
        return CodexRuntime.parse_result(self.runtime, raw, allowed_listing_ids=set(request.allowed_listing_ids))

    def _run_history_review(self, operation, initial_request, result):
        with self._lock:
            review_id = self.store.begin_history_review(operation.id, initial_request, result)
        with connect(self.service.config.database_path) as conn:
            review = conn.execute("SELECT * FROM history_reviews WHERE id=?", (review_id,)).fetchone()
            criteria = tuple(Criterion.model_validate(c) for c in result.criteria)
            pending = [i for i in json.loads(review["scope_ids_json"]) if i not in assessed_items(conn, review_id)]
        for offset in range(0, len(pending), 20):
            self._stage(operation.id, "preparing_context")
            request = self._build_request(operation.task_id, pending[offset:offset + 20]).model_copy(update={
                "trigger_message_id": operation.user_message_id, "allow_preference_update": False,
                "phase": "review_batch", "current_criteria": criteria,
            })
            if (request.task.preference_revision_id != review["preference_revision_id"]
                    or request.evidence_signature != review["evidence_signature"]):
                raise ReviewInputChangedError("Review inputs changed between batches.")
            answer = self._runtime_result(operation.id, request)
            if not isinstance(answer, AnswerResult):
                raise InvalidCodexResult("Review batch must return structured answer, not another action.")
            if answer.check_suggestions:
                raise InvalidCodexResult("Review batches cannot propose checklist items.")
            with self._lock:
                self.store.save_history_batch(operation.id, review_id, request, answer)
        with connect(self.service.config.database_path) as conn:
            groups = nomination_progress(conn, review)["total_groups"]
        for group_index in range(groups):
            with connect(self.service.config.database_path) as conn:
                context = nomination_context(conn, review, group_index)
            request = initial_request.model_copy(update={
                "phase": "nomination", "allow_preference_update": False, "current_criteria": criteria,
                "candidates": (), "evidence": (), "runs": (), "messages": (),
                "allowed_listing_ids": frozenset(a["listing_id"] for a in context["assessments"]),
                "review_context": context,
                "follow_up_context": {}, "check_context_signature": "",
            })
            nominations = self._runtime_result(operation.id, request)
            if not isinstance(nominations, NominationResult):
                raise InvalidCodexResult("Nomination group must return structured nominations.")
            with self._lock:
                self.store.save_history_nomination(operation.id, review_id, request, nominations)
        with connect(self.service.config.database_path) as conn:
            context = comparison_context(conn, review)
        # No current evidence is substituted for stored assessments during comparison.
        allowed = frozenset(item["listing_id"] for item in context["assessments"])
        with connect(self.service.config.database_path) as conn:
            checks_signature = check_signature(conn, operation.task_id)
            checks = follow_up_context(conn, operation.task_id, allowed, {})
            require_current_checks(conn, operation.task_id, checks_signature)
        request = initial_request.model_copy(update={
            "phase": "comparison", "allow_preference_update": False, "current_criteria": criteria,
            "candidates": (), "evidence": (), "allowed_listing_ids": allowed, "review_context": context,
            "follow_up_context": checks, "check_context_signature": checks_signature,
        })
        comparison = self._runtime_result(operation.id, request)
        if not isinstance(comparison, ComparisonResult):
            raise InvalidCodexResult("History review must finish with a structured comparison.")
        with self._lock:
            self.store.complete_with_answer(operation.id, comparison.content,
                [c.listing_id for c in comparison.ranked_candidates],
                expected_preference_revision_id=initial_request.task.preference_revision_id,
                research_request=request, comparison=comparison, review_id=review_id,
                check_suggestions=comparison.check_suggestions)

    def _run(self, operation_id: int) -> None:
        preferences_saved = False
        try:
            with self._lock:
                operation = self.store.transition_with_event(operation_id, {"queued"}, "running")
            self._stage(operation_id, "preparing_context")
            request = self._build_request(operation.task_id)
            request = request.model_copy(update={
                "trigger_message_id": operation.user_message_id,
                "allow_preference_update": self._allow_preference_update(operation),
            })
            self._stage(operation_id, "preparing_context")
            result = self.runtime.run(request, run_id=operation_id,
                                      stage_callback=lambda stage: self._stage(operation_id, stage))
            # Validate again at the coordinator boundary, including custom adapters.
            raw = result.model_dump_json() if hasattr(result, "model_dump_json") else json.dumps(result)
            result = CodexRuntime.parse_result(self.runtime, raw,
                                              allowed_listing_ids=set(request.allowed_listing_ids))
            if isinstance(result, PreferenceUpdateResult):
                if not request.allow_preference_update:
                    raise InvalidCodexResult("Preference changes are not allowed for this turn.")
                if result.base_revision_id != request.task.preference_revision_id:
                    raise PreferenceRevisionConflictError("Model update does not match its input revision.")
                with self._lock:
                    self.store.apply_preference_update(operation_id, result, expected_check_signature=request.check_context_signature)
                    preferences_saved = True
                request = self._build_request(operation.task_id).model_copy(update={
                    "trigger_message_id": operation.user_message_id,
                    "allow_preference_update": False,
                })
                self._stage(operation_id, "preparing_context")
                result = self.runtime.run(request, run_id=operation_id,
                                          stage_callback=lambda stage: self._stage(operation_id, stage))
                raw = result.model_dump_json() if hasattr(result, "model_dump_json") else json.dumps(result)
                result = CodexRuntime.parse_result(self.runtime, raw,
                                                  allowed_listing_ids=set(request.allowed_listing_ids))
                if isinstance(result, PreferenceUpdateResult):
                    raise InvalidCodexResult("Repeated preference update instead of reasoning.")
            if isinstance(result, HistoryReviewResult):
                self._run_history_review(operation, request, result)
                return
            if isinstance(result, (ComparisonResult, NominationResult)):
                raise InvalidCodexResult("Comparison requires a complete local history review.")
            with self._lock:
                if isinstance(result, AnswerResult):
                    self.store.complete_with_answer(operation_id, result.content, result.candidate_ids,
                        expected_preference_revision_id=request.task.preference_revision_id,
                        research=result.research, research_request=request, check_suggestions=result.check_suggestions)
                else:
                    self.store.complete_with_action_request(operation_id, ActionRequestInput(
                        summary=result.summary, risk=result.risk,
                        listing_ids=result.listing_ids, actions=result.actions,
                        analysis=result.analysis, search_query=result.search_query, max_pages=result.max_pages),
                        expected_preference_revision_id=request.task.preference_revision_id,
                        expected_check_signature=request.check_context_signature)
        except OperationStateError:
            pass  # A cancellation or completion already won the transaction.
        except Exception as exc:
            if isinstance(exc, CodexCancelledError):
                state, code, detail = "cancelled", None, None
            elif isinstance(exc, PreferenceRevisionConflictError):
                state, code, detail = "failed", "requirements_changed", "Requirements changed. Retry using the current requirements."
            elif isinstance(exc, CheckContextChangedError):
                state, code, detail = "failed", "review_inputs_changed", str(exc)
            elif isinstance(exc, ReviewInputChangedError):
                state, code, detail = "failed", "review_inputs_changed", "要求或证据已变化，已完成批次保留为历史，请按当前输入重试。"
            elif isinstance(exc, (InvalidCodexResult, InvalidActionRequestError)):
                state, code, detail = "failed", "invalid_codex_result", "Codex returned an invalid structured result."
            elif isinstance(exc, CodexTimeoutError):
                state, code, detail = "failed", "codex_timeout", "Codex timed out. Please retry."
            else:
                state, code, detail = "failed", "codex_execution_failed", "Codex could not complete the request. Saved work is retained; retry, or check Settings if failures persist."
            diagnostics = getattr(exc, "diagnostics", None)
            categories = diagnostics.get("failure_categories") if isinstance(diagnostics, dict) else None
            hints = {"authentication": "CLI reported an authentication error; check authentication in Settings.",
                     "rate_limit": "CLI reported a rate or quota limit; wait or check the provider quota before retrying.",
                     "network": "CLI reported a network or connection error; check connectivity before retrying.",
                     "service": "CLI reported a service error; retry later."}
            if code in {"codex_execution_failed", "codex_timeout"} and isinstance(categories, list):
                selected = [text for key, text in hints.items() if key in categories]
                if selected:
                    detail += " " + " ".join(selected)
            if preferences_saved and state == "failed":
                detail = f"购买要求已保存，但后续分析未完成。{detail}"
            with self._lock:
                try:
                    self.store.transition_with_event(operation_id, {"queued", "running"}, state,
                                                     error_code=code, error_detail=detail)
                except OperationStateError:
                    pass
        finally:
            with self._lock:
                self._workers.pop(operation_id, None)

    def cancel(self, operation_id: int):
        with self._lock:
            record = self.store.get_operation(operation_id)
            if record.state in {"queued", "running"}:
                self.store.transition_with_event(operation_id, {"queued", "running"}, "cancelled")
            self.runtime.cancel(operation_id)
            return self.service.get_operation(operation_id)

    def recover_interrupted(self) -> None:
        for operation in self.store.list_active_operations():
            if operation.state in {"queued", "running"}:
                self.store.transition_with_event(operation.id, {"queued", "running"}, "interrupted",
                                                error_code="service_restarted",
                                                error_detail="Service restarted. Send a message to retry.")

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            workers = list(self._workers.items())
            # Mark all operations before releasing any fake/real runner.
            for operation_id, _ in workers:
                record = self.store.get_operation(operation_id)
                if record.state in {"queued", "running"}:
                    self.store.transition_with_event(operation_id, {"queued", "running"}, "cancelled")
            for operation_id, _ in workers:
                self.runtime.cancel(operation_id)
        for _, worker in workers:
            worker.join(timeout=15)
