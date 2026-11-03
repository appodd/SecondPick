from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_task_preference_revision, connect, create_research_task, initialize, utc_now_iso,
)
from shopping_agent.codex_runtime import PreferenceUpdateResult
from shopping_agent.assessment import save_research
from shopping_agent.check_context import require_current_checks
from shopping_agent.history_review import begin_review, save_batch, save_comparison, save_nomination, nomination_progress, coverage, ReviewInputChangedError


MUTABLE_OPERATION_STATES = {"queued", "running", "waiting_confirmation"}
TERMINAL_OPERATION_STATES = {"completed", "failed", "cancelled", "interrupted"}
OPERATION_STATES = MUTABLE_OPERATION_STATES | TERMINAL_OPERATION_STATES
ALLOWED_ACTIONS = {"search", "detail", "media", "ocr"}


class ConversationStoreError(RuntimeError):
    pass


class RecordNotFoundError(ConversationStoreError):
    pass


class OperationConflictError(ConversationStoreError):
    pass


class OperationStateError(ConversationStoreError):
    pass


class PreferenceRevisionConflictError(ConversationStoreError):
    pass


class InvalidActionRequestError(ConversationStoreError):
    pass


class ActionDecisionConflictError(ConversationStoreError):
    pass


@dataclass(frozen=True)
class MessageRecord:
    id: int
    task_id: int
    role: str
    content: str
    operation_id: int | None
    candidate_ids: list[int]
    created_at: str
    candidate_statement: dict | None = None


@dataclass(frozen=True)
class OperationRecord:
    id: int
    task_id: int
    user_message_id: int
    kind: str
    state: str
    error_code: str | None
    error_detail: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None


@dataclass(frozen=True)
class OperationEventRecord:
    id: int
    operation_id: int
    task_id: int
    event_type: str
    payload: dict[str, object]
    created_at: str


@dataclass(frozen=True)
class ActionRequestRecord:
    id: int
    operation_id: int
    task_id: int
    summary: str
    risk: str
    listing_ids: list[int]
    actions: list[str]
    state: str
    created_at: str
    decided_at: str | None
    search_query: str | None = None
    max_pages: int = 1


@dataclass(frozen=True)
class ActionRequestInput:
    summary: str
    risk: str
    listing_ids: list[int]
    actions: list[str]
    analysis: str = ""
    search_query: str | None = None
    max_pages: int = 1


@dataclass(frozen=True)
class CreatedTaskOperation:
    task_id: int
    message: MessageRecord
    operation: OperationRecord


@dataclass(frozen=True)
class CreatedMessageOperation:
    message: MessageRecord
    operation: OperationRecord


@dataclass(frozen=True)
class MessagePage:
    items: list[MessageRecord]
    has_more: bool
    next_before_id: int | None


@dataclass(frozen=True)
class ActionRequestPage:
    items: list[ActionRequestRecord]
    has_more: bool
    next_before_id: int | None


class ConversationStore:
    def __init__(self, config: AppConfig) -> None:
        self.database_path: Path = config.database_path
        initialize(self.database_path)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self.database_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_task_with_message(
        self,
        title: str,
        message: str,
        city: str,
    ) -> CreatedTaskOperation:
        with self._transaction() as conn:
            task_id = create_research_task(conn, title=title, goal=message, city=city)
            created = self._create_message_operation(conn, task_id, message)
        return CreatedTaskOperation(task_id, created.message, created.operation)

    def rename_task(self, task_id: int, title: str) -> None:
        with self._transaction() as conn:
            now = utc_now_iso()
            cursor = conn.execute(
                "UPDATE research_tasks SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, task_id),
            )
            if cursor.rowcount != 1:
                raise RecordNotFoundError(f"Research task not found: {task_id}")

    def create_message_operation(self, task_id: int, message: str, candidate_statement=None) -> CreatedMessageOperation:
        try:
            with self._transaction() as conn:
                self._require_task(conn, task_id)
                if candidate_statement is not None:
                    if (not isinstance(candidate_statement, dict) or set(candidate_statement) != {"listing_id", "kind"}
                            or type(candidate_statement["listing_id"]) is not int or not 0 < candidate_statement["listing_id"] <= 2**63-1
                            or not isinstance(candidate_statement["kind"], str)
                            or candidate_statement["kind"] not in {"seller_reply", "user_observation"} or len(message) > 8000):
                        raise InvalidActionRequestError("Invalid candidate statement binding (maximum 8000 characters).")
                    if not conn.execute("SELECT 1 FROM listing_snapshots s JOIN task_runs t ON t.run_id=s.run_id WHERE t.task_id=? AND s.listing_id=? LIMIT 1", (task_id, candidate_statement["listing_id"])).fetchone():
                        raise InvalidActionRequestError("Statement candidate is outside this task's saved scope.")
                return self._create_message_operation(conn, task_id, message, candidate_statement=candidate_statement)
        except sqlite3.IntegrityError as exc:
            if "operations.task_id" in str(exc):
                raise OperationConflictError(
                    f"Task {task_id} already has a mutable operation"
                ) from exc
            raise RuntimeError(str(exc)) from exc

    def change_statement(self, task_id, statement_id, **change):
        from shopping_agent.statement_changes import change_statement
        with self._transaction() as conn:
            self._require_task(conn, task_id)
            if (conn.execute("SELECT 1 FROM browser_jobs WHERE task_id=? AND state IN ('queued','running')", (task_id,)).fetchone()
                    or conn.execute("SELECT 1 FROM operations WHERE task_id=? AND state='waiting_confirmation'", (task_id,)).fetchone()):
                raise OperationConflictError("请先结束采集或处理待确认请求，再更正补充证据。")
            return change_statement(conn, task_id, statement_id, **change)

    def list_messages(self, task_id: int, limit: int, before_id: int | None) -> MessagePage:
        self._validate_page(limit, before_id)
        with connect(self.database_path) as conn:
            self._require_task(conn, task_id)
            params: list[object] = [task_id]
            before_clause = ""
            if before_id is not None:
                before_clause = "AND id < ?"
                params.append(before_id)
            params.append(limit + 1)
            rows = list(
                conn.execute(
                    f"""
                    SELECT m.*, s.id AS statement_id, s.listing_id AS statement_listing_id, s.kind AS statement_kind,
                    s.status AS statement_status,s.revision_id AS statement_revision_id,s.original_listing_id AS statement_original_listing_id
                    FROM conversation_messages m LEFT JOIN candidate_statement_current s ON s.source_message_id=m.id AND s.task_id=m.task_id
                    WHERE m.task_id = ? {before_clause.replace('id <', 'm.id <')}
                    ORDER BY m.id DESC
                    LIMIT ?
                    """,
                    params,
                )
            )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = [self._message_from_row(row) for row in reversed(page_rows)]
        return MessagePage(
            items=items,
            has_more=has_more,
            next_before_id=page_rows[-1]["id"] if has_more else None,
        )

    def list_action_requests(
        self,
        task_id: int,
        limit: int,
        before_id: int | None,
    ) -> ActionRequestPage:
        self._validate_page(limit, before_id)
        with connect(self.database_path) as conn:
            self._require_task(conn, task_id)
            params: list[object] = [task_id]
            before_clause = ""
            if before_id is not None:
                before_clause = "AND id < ?"
                params.append(before_id)
            params.append(limit + 1)
            rows = list(
                conn.execute(
                    f"""
                    SELECT * FROM action_requests
                    WHERE task_id = ? {before_clause}
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    params,
                )
            )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = [self._action_request_from_row(row) for row in reversed(page_rows)]
        return ActionRequestPage(
            items=items,
            has_more=has_more,
            next_before_id=page_rows[-1]["id"] if has_more else None,
        )

    def get_operation(self, operation_id: int) -> OperationRecord:
        with connect(self.database_path) as conn:
            row = conn.execute("SELECT * FROM operations WHERE id = ?", (operation_id,)).fetchone()
        if row is None:
            raise RecordNotFoundError(f"Operation not found: {operation_id}")
        return self._operation_from_row(row)

    def list_active_operations(self) -> list[OperationRecord]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM operations
                WHERE state IN ('queued', 'running', 'waiting_confirmation')
                ORDER BY id
                """
            ).fetchall()
        return [self._operation_from_row(row) for row in rows]

    def transition_operation(
        self,
        operation_id: int,
        expected: set[str],
        target: str,
        **fields: object,
    ) -> OperationRecord:
        if not expected or not expected <= OPERATION_STATES or target not in OPERATION_STATES:
            raise ValueError("Invalid operation state transition")
        allowed_fields = {"error_code", "error_detail", "started_at", "completed_at"}
        if unknown := set(fields) - allowed_fields:
            raise ValueError(f"Unsupported operation fields: {sorted(unknown)}")
        values = dict(fields)
        now = utc_now_iso()
        if target == "running" and "started_at" not in values:
            values["started_at"] = now
        if target in TERMINAL_OPERATION_STATES and "completed_at" not in values:
            values["completed_at"] = now
        with self._transaction() as conn:
            row = self._transition_operation(conn, operation_id, expected, target, values)
        return self._operation_from_row(row)

    def append_event(
        self,
        operation_id: int,
        event_type: str,
        payload: dict[str, object],
    ) -> OperationEventRecord:
        payload_json = self._dump_json_object(payload)
        with self._transaction() as conn:
            operation = self._require_operation(conn, operation_id)
            row = self._insert_event(
                conn,
                operation_id,
                int(operation["task_id"]),
                event_type,
                payload_json,
            )
        return self._event_from_row(row)

    def transition_with_event(
        self, operation_id: int, expected: set[str], target: str,
        *, error_code: str | None = None, error_detail: str | None = None,
    ) -> OperationRecord:
        """Commit lifecycle state and its replay notification together."""
        if target not in OPERATION_STATES or not expected or not expected <= OPERATION_STATES:
            raise ValueError("Invalid operation state transition")
        fields = {"error_code": error_code, "error_detail": error_detail}
        if target == "running":
            fields["started_at"] = utc_now_iso()
        if target in TERMINAL_OPERATION_STATES:
            fields["completed_at"] = utc_now_iso()
        with self._transaction() as conn:
            row = self._transition_operation(conn, operation_id, expected, target, fields)
            self._insert_event(conn, operation_id, int(row["task_id"]), target,
                               self._dump_json_object({"state": target}))
        return self._operation_from_row(row)

    def list_events(self, operation_id: int, after_id: int) -> list[OperationEventRecord]:
        if after_id < 0:
            raise ValueError("after_id must be non-negative")
        with connect(self.database_path) as conn:
            self._require_operation(conn, operation_id)
            rows = conn.execute(
                """
                SELECT * FROM operation_events
                WHERE operation_id = ? AND id > ?
                ORDER BY id
                """,
                (operation_id, after_id),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    @staticmethod
    def _check_preference_revision(conn, task_id: int, expected: int | None) -> None:
        if expected is None:
            return
        row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS revision FROM task_preference_revisions WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if int(row["revision"]) != expected:
            raise PreferenceRevisionConflictError("Task requirements changed while reasoning was running.")

    def apply_preference_update(self, operation_id: int, update: PreferenceUpdateResult, *, expected_check_signature: str = "") -> int:
        """Commit a revision and its event together, without completing the analysis."""
        update = PreferenceUpdateResult.model_validate(update.model_dump())
        payload = update.model_dump(mode="json")
        with self._transaction() as conn:
            operation = self._require_running_operation(conn, operation_id)
            task_id = int(operation["task_id"])
            require_current_checks(conn, task_id, expected_check_signature)
            if int(operation["user_message_id"]) != update.source_message_id:
                raise InvalidActionRequestError("Preference change must refer to the triggering user message.")
            message = conn.execute(
                "SELECT * FROM conversation_messages WHERE id = ? AND task_id = ? AND role = 'user'",
                (update.source_message_id, task_id),
            ).fetchone()
            if message is None or not self._preference_update_allowed(conn, task_id, update.source_message_id):
                raise InvalidActionRequestError("A preference update requires a subsequent user message.")
            existing = conn.execute(
                "SELECT payload_json FROM operation_events WHERE operation_id = ? AND event_type = 'preferences_updated'",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                saved = json.loads(existing["payload_json"])
                if saved["update"] != payload:
                    raise InvalidActionRequestError("This message already applied a different preference update.")
                return int(saved["revision_id"])
            self._check_preference_revision(conn, task_id, update.base_revision_id)
            current = conn.execute(
                "SELECT effective_goal FROM task_preference_revisions WHERE task_id = ? ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            goal = current["effective_goal"] if current else self._require_task(conn, task_id)["goal"]
            if update.effective_goal.strip() == goal.strip():
                raise InvalidActionRequestError("Preference update must change the effective goal.")
            revision_id = add_task_preference_revision(
                conn, task_id, message["content"], update.effective_goal,
                json.dumps(update.added_preferences, ensure_ascii=False),
                json.dumps(update.removed_preferences, ensure_ascii=False),
            )
            self._insert_event(conn, operation_id, task_id, "preferences_updated",
                               self._dump_json_object({"revision_id": revision_id, "update": payload}))
        return revision_id

    @staticmethod
    def _preference_update_allowed(conn, task_id, message_id):
        if conn.execute("SELECT 1 FROM candidate_statements WHERE task_id=? AND source_message_id=?", (task_id, message_id)).fetchone():
            return False
        row = conn.execute("SELECT m.role,m.content,t.goal FROM conversation_messages m JOIN research_tasks t ON t.id=m.task_id WHERE m.task_id=? AND m.id=?", (task_id, message_id)).fetchone()
        if row is None or row["role"] != "user":
            return False
        prior_user = conn.execute("SELECT 1 FROM conversation_messages WHERE task_id=? AND role='user' AND id<? LIMIT 1", (task_id, message_id)).fetchone()
        # Web task creation stores exactly the same text as goal and first message.
        # A first web message on a saved CLI task can instead follow its saved goal.
        return prior_user is not None or row["content"].strip() != row["goal"].strip()

    def complete_with_answer(
        self,
        operation_id: int,
        content: str,
        candidate_ids: list[int],
        *, expected_preference_revision_id: int | None = None,
        research=None, research_request=None,
        comparison=None, review_id: int | None = None,
        check_suggestions=(),
    ) -> MessageRecord:
        with self._transaction() as conn:
            operation = self._require_running_operation(conn, operation_id)
            task_id = int(operation["task_id"])
            self._check_preference_revision(conn, task_id, expected_preference_revision_id)
            if research_request is not None:
                require_current_checks(conn, task_id, research_request.check_context_signature)
            self._validate_listing_scope(conn, task_id, candidate_ids, maximum=4)
            now = utc_now_iso()
            if comparison is not None:
                review = conn.execute("SELECT * FROM history_reviews WHERE id=? AND operation_id=? AND task_id=?", (review_id, operation_id, task_id)).fetchone()
                if review is None or research_request is None or research is not None:
                    raise InvalidActionRequestError("Comparison requires its local review and input snapshot.")
                try:
                    comparison_id = save_comparison(conn, review=review, request=research_request, result=comparison, now=now)
                except ReviewInputChangedError:
                    raise
                except ValueError as exc:
                    raise InvalidActionRequestError(str(exc)) from exc
                self._insert_event(conn, operation_id, task_id, "comparison_saved",
                                   self._dump_json_object({"comparison_id": comparison_id}))
            if research is not None:
                if research_request is None:
                    raise InvalidActionRequestError("Research requires its server input snapshot.")
                self._check_preference_revision(conn, task_id, research_request.task.preference_revision_id)
                self._validate_listing_scope(conn, task_id, [a.listing_id for a in research.assessments], maximum=20)
                try:
                    standard_id = save_research(conn, operation_id=operation_id, task_id=task_id,
                        research=research, request=research_request, now=now, candidate_ids=candidate_ids)
                except ValueError as exc:
                    raise InvalidActionRequestError(str(exc)) from exc
                self._insert_event(conn, operation_id, task_id, "assessments_saved",
                    self._dump_json_object({"standard_id": standard_id, "assessed_count": len(research.assessments)}))
            cursor = conn.execute(
                """
                INSERT INTO conversation_messages (
                  task_id, role, content, operation_id, candidate_ids_json, created_at
                ) VALUES (?, 'assistant', ?, ?, ?, ?)
                """,
                (task_id, content, operation_id, self._dump_int_list(candidate_ids), now),
            )
            message_id = int(cursor.lastrowid)
            from shopping_agent.check_suggestions import save_suggestions
            save_suggestions(conn, task_id=task_id, operation_id=operation_id, message_id=message_id,
                request=research_request, suggestions=comparison.check_suggestions if comparison is not None else check_suggestions, now=now)
            self._transition_operation(
                conn,
                operation_id,
                {"running"},
                "completed",
                {"completed_at": now},
            )
            self._insert_event(
                conn,
                operation_id,
                task_id,
                "completed",
                self._dump_json_object({"message_id": message_id}),
            )
            row = conn.execute(
                "SELECT * FROM conversation_messages WHERE id = ?", (message_id,)
            ).fetchone()
        return self._message_from_row(row)

    def begin_history_review(self, operation_id, request, result):
        with self._transaction() as conn:
            operation = self._require_running_operation(conn, operation_id)
            task_id = int(operation["task_id"])
            if request.task.id != task_id:
                raise InvalidActionRequestError("Review belongs to another task.")
            self._check_preference_revision(conn, task_id, request.task.preference_revision_id)
            try:
                review_id = begin_review(conn, operation_id=operation_id, request=request, result=result, now=utc_now_iso())
            except ReviewInputChangedError:
                raise
            except ValueError as exc:
                raise InvalidActionRequestError(str(exc)) from exc
            review = conn.execute("SELECT * FROM history_reviews WHERE id=?", (review_id,)).fetchone()
            self._insert_event(conn, operation_id, task_id, "review_progress",
                               self._dump_json_object({"review_id": review_id, **coverage(conn, review)}))
        return review_id

    def save_history_batch(self, operation_id, review_id, request, answer):
        with self._transaction() as conn:
            operation = self._require_running_operation(conn, operation_id)
            task_id = int(operation["task_id"])
            self._check_preference_revision(conn, task_id, request.task.preference_revision_id)
            review = conn.execute("SELECT * FROM history_reviews WHERE id=? AND operation_id=? AND task_id=?", (review_id, operation_id, task_id)).fetchone()
            if review is None:
                raise InvalidActionRequestError("Review belongs to another operation.")
            try:
                assessment_id, created = save_batch(conn, review=review, request=request, answer=answer, now=utc_now_iso())
            except ReviewInputChangedError:
                raise
            except ValueError as exc:
                raise InvalidActionRequestError(str(exc)) from exc
            if created:
                self._insert_event(conn, operation_id, task_id, "review_progress", self._dump_json_object(
                    {"review_id": review_id, "assessment_id": assessment_id, **coverage(conn, review)}))
        return assessment_id

    def save_history_nomination(self, operation_id, review_id, request, result):
        with self._transaction() as conn:
            operation = self._require_running_operation(conn, operation_id)
            task_id = int(operation["task_id"])
            self._check_preference_revision(conn, task_id, request.task.preference_revision_id)
            review = conn.execute("SELECT * FROM history_reviews WHERE id=? AND operation_id=? AND task_id=?", (review_id, operation_id, task_id)).fetchone()
            if review is None:
                raise InvalidActionRequestError("Review belongs to another operation.")
            try:
                nomination_id, created = save_nomination(conn, review=review, request=request, result=result, now=utc_now_iso())
            except ReviewInputChangedError:
                raise
            except ValueError as exc:
                raise InvalidActionRequestError(str(exc)) from exc
            if created:
                self._insert_event(conn, operation_id, task_id, "review_progress", self._dump_json_object(
                    {"review_id": review_id, "nomination_id": nomination_id, "nomination_progress": nomination_progress(conn, review), **coverage(conn, review)}))
        return nomination_id

    def complete_with_action_request(
        self,
        operation_id: int,
        result: ActionRequestInput,
        *, expected_preference_revision_id: int | None = None,
        expected_check_signature: str = "",
    ) -> ActionRequestRecord:
        with self._transaction() as conn:
            operation = self._require_running_operation(conn, operation_id)
            task_id = int(operation["task_id"])
            self._check_preference_revision(conn, task_id, expected_preference_revision_id)
            require_current_checks(conn, task_id, expected_check_signature)
            self._validate_action_request(conn, task_id, result)
            now = utc_now_iso()
            cursor = conn.execute(
                """
                INSERT INTO action_requests (
                  operation_id, task_id, summary, risk, listing_ids_json,
                  actions_json, state, created_at, search_query, max_pages
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    operation_id,
                    task_id,
                    result.summary,
                    result.risk,
                    self._dump_int_list(result.listing_ids),
                    self._dump_string_list(result.actions),
                    now,
                    result.search_query,
                    result.max_pages,
                ),
            )
            request_id = int(cursor.lastrowid)
            if result.analysis.strip():
                conn.execute("""INSERT INTO conversation_messages(task_id,role,content,operation_id,candidate_ids_json,created_at)
                    VALUES(?,'assistant',?,?,?,?)""", (task_id, result.analysis, operation_id,
                    self._dump_int_list(result.listing_ids[:4]), now))
            self._transition_operation(
                conn,
                operation_id,
                {"running"},
                "waiting_confirmation",
                {},
            )
            self._insert_event(
                conn,
                operation_id,
                task_id,
                "waiting_confirmation",
                self._dump_json_object({"action_request_id": request_id}),
            )
            row = conn.execute(
                "SELECT * FROM action_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return self._action_request_from_row(row)

    def decide_action_request(
        self,
        request_id: int,
        decision: Literal["approved", "rejected"],
    ) -> ActionRequestRecord:
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM action_requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                raise RecordNotFoundError(f"Action request not found: {request_id}")
            from shopping_agent.project_investigations import linked
            if linked(conn, request_id):
                raise ActionDecisionConflictError('请在项目调查面板审阅并确认此调查，不能从旧会话更改范围。')
            if row["state"] == decision:
                return self._action_request_from_row(row)
            if row["state"] != "pending":
                raise ActionDecisionConflictError(
                    f"Action request {request_id} was already {row['state']}"
                )
            if decision == "approved":
                self._validate_listing_scope(
                    conn,
                    int(row["task_id"]),
                    self._load_int_list(row["listing_ids_json"]),
                )
            now = utc_now_iso()
            conn.execute(
                "UPDATE action_requests SET state = ?, decided_at = ? WHERE id = ?",
                (decision, now, request_id),
            )
            self._transition_operation(
                conn,
                int(row["operation_id"]),
                {"waiting_confirmation"},
                "completed",
                {"completed_at": now},
            )
            self._insert_event(
                conn,
                int(row["operation_id"]),
                int(row["task_id"]),
                "completed",
                self._dump_json_object(
                    {"action_request_id": request_id, "decision": decision}
                ),
            )
            saved = conn.execute(
                "SELECT * FROM action_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return self._action_request_from_row(saved)

    def _create_message_operation(
        self,
        conn: sqlite3.Connection,
        task_id: int,
        message: str,
        role: Literal["user", "system"] = "user",
        candidate_statement=None,
    ) -> CreatedMessageOperation:
        if conn.execute("SELECT 1 FROM browser_jobs WHERE task_id=? AND state IN ('queued','running')", (task_id,)).fetchone():
            raise OperationConflictError("This task has an active collection. Stop it or wait for completion.")
        now = utc_now_iso()
        message_cursor = conn.execute(
            """
            INSERT INTO conversation_messages (task_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, role, message, now),
        )
        message_id = int(message_cursor.lastrowid)
        if candidate_statement is not None:
            conn.execute("INSERT INTO candidate_statements(task_id,listing_id,source_message_id,kind,created_at) VALUES (?,?,?,?,?)",
                         (task_id, candidate_statement["listing_id"], message_id, candidate_statement["kind"], now))
        operation_cursor = conn.execute(
            """
            INSERT INTO operations (
              task_id, user_message_id, kind, state, created_at
            ) VALUES (?, ?, 'codex_message', 'queued', ?)
            """,
            (task_id, message_id, now),
        )
        operation_id = int(operation_cursor.lastrowid)
        conn.execute(
            "UPDATE conversation_messages SET operation_id = ? WHERE id = ?",
            (operation_id, message_id),
        )
        conn.execute(
            "UPDATE research_tasks SET updated_at = ? WHERE id = ?", (now, task_id)
        )
        self._insert_event(
            conn,
            operation_id,
            task_id,
            "queued",
            self._dump_json_object({"state": "queued"}),
        )
        message_row = conn.execute(
            "SELECT m.*,s.id AS statement_id,s.listing_id AS statement_listing_id,s.kind AS statement_kind,s.status AS statement_status,s.revision_id AS statement_revision_id,s.original_listing_id AS statement_original_listing_id FROM conversation_messages m LEFT JOIN candidate_statement_current s ON s.source_message_id=m.id AND s.task_id=m.task_id WHERE m.id = ?", (message_id,)
        ).fetchone()
        operation_row = conn.execute(
            "SELECT * FROM operations WHERE id = ?", (operation_id,)
        ).fetchone()
        return CreatedMessageOperation(
            self._message_from_row(message_row),
            self._operation_from_row(operation_row),
        )

    def _transition_operation(
        self,
        conn: sqlite3.Connection,
        operation_id: int,
        expected: set[str],
        target: str,
        fields: dict[str, object],
    ) -> sqlite3.Row:
        assignments = ["state = ?", *(f"{name} = ?" for name in fields)]
        placeholders = ", ".join("?" for _ in expected)
        parameters = [target, *fields.values(), operation_id, *sorted(expected)]
        cursor = conn.execute(
            f"""
            UPDATE operations SET {', '.join(assignments)}
            WHERE id = ? AND state IN ({placeholders})
            """,
            parameters,
        )
        if cursor.rowcount != 1:
            row = conn.execute("SELECT state FROM operations WHERE id = ?", (operation_id,)).fetchone()
            if row is None:
                raise RecordNotFoundError(f"Operation not found: {operation_id}")
            raise OperationStateError(
                f"Operation {operation_id} is {row['state']}, expected {sorted(expected)}"
            )
        return conn.execute("SELECT * FROM operations WHERE id = ?", (operation_id,)).fetchone()

    def _require_running_operation(
        self,
        conn: sqlite3.Connection,
        operation_id: int,
    ) -> sqlite3.Row:
        row = self._require_operation(conn, operation_id)
        if row["state"] != "running":
            raise OperationStateError(
                f"Operation {operation_id} is {row['state']}, expected running"
            )
        return row

    @staticmethod
    def _require_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM research_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise RecordNotFoundError(f"Research task not found: {task_id}")
        return row

    @staticmethod
    def _require_operation(conn: sqlite3.Connection, operation_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM operations WHERE id = ?", (operation_id,)).fetchone()
        if row is None:
            raise RecordNotFoundError(f"Operation not found: {operation_id}")
        return row

    def _validate_action_request(
        self,
        conn: sqlite3.Connection,
        task_id: int,
        result: ActionRequestInput,
    ) -> None:
        if not result.summary.strip() or not result.risk.strip():
            raise InvalidActionRequestError("Action request summary and risk are required")
        if not result.actions or any(action not in ALLOWED_ACTIONS for action in result.actions):
            raise InvalidActionRequestError("Action request contains unsupported actions")
        if len(set(result.actions)) != len(result.actions):
            raise InvalidActionRequestError("Action request actions must be unique")
        if type(result.max_pages) is not int or not 1 <= result.max_pages <= 3:
            raise InvalidActionRequestError("Invalid suggested page limit")
        if result.search_query is not None and (not isinstance(result.search_query, str) or
                not result.search_query.strip() or len(result.search_query) > 120 or "search" not in result.actions):
            raise InvalidActionRequestError("Invalid suggested search query")
        self._validate_listing_scope(conn, task_id, result.listing_ids)

    @staticmethod
    def _validate_listing_scope(
        conn: sqlite3.Connection,
        task_id: int,
        listing_ids: list[int],
        maximum: int | None = None,
    ) -> None:
        if maximum is not None and len(listing_ids) > maximum:
            raise InvalidActionRequestError(f"At most {maximum} listing IDs are allowed")
        if any(type(listing_id) is not int or listing_id <= 0 for listing_id in listing_ids):
            raise InvalidActionRequestError("Listing IDs must be positive integers")
        if len(set(listing_ids)) != len(listing_ids):
            raise InvalidActionRequestError("Listing IDs must be unique")
        if not listing_ids:
            return
        placeholders = ", ".join("?" for _ in listing_ids)
        rows = conn.execute(
            f"""
            SELECT DISTINCT snapshots.listing_id
            FROM task_runs AS task_runs
            JOIN listing_snapshots AS snapshots ON snapshots.run_id = task_runs.run_id
            WHERE task_runs.task_id = ? AND snapshots.listing_id IN ({placeholders})
            """,
            (task_id, *listing_ids),
        ).fetchall()
        found = {int(row["listing_id"]) for row in rows}
        if found != set(listing_ids):
            raise InvalidActionRequestError("Listing IDs must belong to the operation task")

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        operation_id: int,
        task_id: int,
        event_type: str,
        payload_json: str,
    ) -> sqlite3.Row:
        cursor = conn.execute(
            """
            INSERT INTO operation_events (
              operation_id, task_id, event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (operation_id, task_id, event_type, payload_json, utc_now_iso()),
        )
        return conn.execute(
            "SELECT * FROM operation_events WHERE id = ?", (int(cursor.lastrowid),)
        ).fetchone()

    @staticmethod
    def _validate_page(limit: int, before_id: int | None) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if before_id is not None and before_id <= 0:
            raise ValueError("before_id must be positive")

    @staticmethod
    def _dump_json_object(value: dict[str, object]) -> str:
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Payload must be valid JSON") from exc

    @staticmethod
    def _dump_int_list(value: list[int]) -> str:
        if any(type(item) is not int for item in value):
            raise ValueError("Expected a list of integers")
        return json.dumps(value, separators=(",", ":"))

    @staticmethod
    def _dump_string_list(value: list[str]) -> str:
        if any(not isinstance(item, str) for item in value):
            raise ValueError("Expected a list of strings")
        return json.dumps(value, separators=(",", ":"))

    @staticmethod
    def _load_int_list(value: str) -> list[int]:
        loaded = json.loads(value)
        if not isinstance(loaded, list) or any(type(item) is not int for item in loaded):
            raise ValueError("Stored JSON is not an integer list")
        return loaded

    @staticmethod
    def _load_string_list(value: str) -> list[str]:
        loaded = json.loads(value)
        if not isinstance(loaded, list) or any(not isinstance(item, str) for item in loaded):
            raise ValueError("Stored JSON is not a string list")
        return loaded

    @classmethod
    def _message_from_row(cls, row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            id=int(row["id"]),
            task_id=int(row["task_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            operation_id=int(row["operation_id"]) if row["operation_id"] is not None else None,
            candidate_ids=cls._load_int_list(row["candidate_ids_json"]),
            created_at=str(row["created_at"]),
            candidate_statement=(dict(id=row["statement_id"], listing_id=row["statement_listing_id"], kind=row["statement_kind"],
                                      status=row["statement_status"], revision_id=row["statement_revision_id"], original_listing_id=row["statement_original_listing_id"])
                                 if "statement_id" in row.keys() and row["statement_id"] is not None else None),
        )

    @staticmethod
    def _operation_from_row(row: sqlite3.Row) -> OperationRecord:
        return OperationRecord(
            id=int(row["id"]),
            task_id=int(row["task_id"]),
            user_message_id=int(row["user_message_id"]),
            kind=str(row["kind"]),
            state=str(row["state"]),
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            created_at=str(row["created_at"]),
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    @classmethod
    def _event_from_row(cls, row: sqlite3.Row) -> OperationEventRecord:
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            raise ValueError("Stored event payload is not an object")
        return OperationEventRecord(
            id=int(row["id"]),
            operation_id=int(row["operation_id"]),
            task_id=int(row["task_id"]),
            event_type=str(row["event_type"]),
            payload=payload,
            created_at=str(row["created_at"]),
        )

    @classmethod
    def _action_request_from_row(cls, row: sqlite3.Row) -> ActionRequestRecord:
        return ActionRequestRecord(
            id=int(row["id"]),
            operation_id=int(row["operation_id"]),
            task_id=int(row["task_id"]),
            summary=str(row["summary"]),
            risk=str(row["risk"]),
            listing_ids=cls._load_int_list(row["listing_ids_json"]),
            actions=cls._load_string_list(row["actions_json"]),
            state=str(row["state"]),
            created_at=str(row["created_at"]),
            decided_at=row["decided_at"],
            search_query=row["search_query"],
            max_pages=int(row["max_pages"]),
        )
