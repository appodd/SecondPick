"""Model proposals are inert until the user explicitly saves one."""
import re
import unicodedata
from uuid import uuid4

from shopping_agent.assessment import CheckSuggestion, evidence_signature
from shopping_agent.candidate_checks import CandidateChecks
from shopping_agent.conversation_store import InvalidActionRequestError, OperationConflictError, RecordNotFoundError
from shopping_agent.db import utc_now_iso


def question_key(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def save_suggestions(conn, *, task_id, operation_id, message_id, request, suggestions, now):
    if not suggestions:
        return
    if request is None or request.task.id != task_id or request.phase not in {"chat", "comparison"}:
        raise InvalidActionRequestError("核实建议需要本轮聊天或比较输入。")
    if len(suggestions) > 8 or evidence_signature(conn, task_id) != request.evidence_signature:
        raise InvalidActionRequestError("建议输入证据已变化，请重试分析。")
    revision = conn.execute("SELECT COALESCE(MAX(id),0) FROM task_preference_revisions WHERE task_id=?", (task_id,)).fetchone()[0]
    if revision != request.task.preference_revision_id:
        raise InvalidActionRequestError("建议输入的购买要求已变化，请重试分析。")
    seen = set()
    for value in suggestions:
        item = CheckSuggestion.model_validate(value.model_dump())
        if item.listing_id not in request.allowed_listing_ids:
            raise InvalidActionRequestError("建议商品不在本轮输入范围内。")
        CandidateChecks.scope(conn, task_id, item.listing_id)
        key = (item.listing_id, question_key(item.question))
        if key in seen:
            continue
        seen.add(key)
        conn.execute("INSERT INTO candidate_check_suggestions(task_id,listing_id,operation_id,source_message_id,question,reason,preference_revision_id,evidence_signature,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (task_id, item.listing_id, operation_id, message_id, item.question, item.reason,
             request.task.preference_revision_id, request.evidence_signature, now))


class CheckSuggestions(CandidateChecks):
    @staticmethod
    def basis(conn, task_id):
        revision = conn.execute("SELECT COALESCE(MAX(id),0) FROM task_preference_revisions WHERE task_id=?", (task_id,)).fetchone()[0]
        return revision, evidence_signature(conn, task_id)

    @staticmethod
    def suggestion_dto(row, basis):
        return dict(**{k: row[k] for k in ("id", "task_id", "listing_id", "operation_id", "source_message_id", "question", "reason", "created_at", "check_id", "accepted_at")},
            reused_existing=bool(row["reused_existing"]), stale=(row["preference_revision_id"], row["evidence_signature"]) != basis)

    def page(self, task_id, listing_id, *, limit=20, before_id=None):
        if type(limit) is not int or not 1 <= limit <= 50 or (before_id is not None and (type(before_id) is not int or not 0 < before_id <= 2**63-1)):
            raise InvalidActionRequestError("Invalid suggestion page")
        with self.connection() as conn:
            self.scope(conn, task_id, listing_id)
            basis = self.basis(conn, task_id)
            count = conn.execute("SELECT COUNT(*) FROM candidate_check_suggestions WHERE task_id=? AND listing_id=?", (task_id, listing_id)).fetchone()[0]
            clause = " AND id<?" if before_id is not None else ""
            rows = list(conn.execute(f"SELECT * FROM candidate_check_suggestions WHERE task_id=? AND listing_id=?{clause} ORDER BY id DESC LIMIT ?",
                (task_id, listing_id, *([before_id] if before_id is not None else []), limit+1)))
            return dict(items=[self.suggestion_dto(r, basis) for r in rows[:limit]], total_count=count,
                has_more=len(rows)>limit, next_before_id=rows[limit-1]["id"] if len(rows)>limit else None)

    def accept(self, task_id, listing_id, suggestion_id):
        with self.connection(write=True) as conn:
            self.scope(conn, task_id, listing_id)
            row = conn.execute("SELECT * FROM candidate_check_suggestions WHERE task_id=? AND listing_id=? AND id=?", (task_id, listing_id, suggestion_id)).fetchone()
            if row is None:
                raise RecordNotFoundError("核实建议不在当前商品内。")
            if row["check_id"] is not None:
                return dict(suggestion_id=suggestion_id, check=self.dto(self.item(conn, task_id, listing_id, row["check_id"])), reused_existing=bool(row["reused_existing"]))
            if (row["preference_revision_id"], row["evidence_signature"]) != self.basis(conn, task_id):
                raise OperationConflictError("建议依据的要求或证据已变化，请重新分析后核对建议。")
            key = question_key(row["question"])
            existing = next((r for r in conn.execute("SELECT id,question FROM candidate_check_current WHERE task_id=? AND listing_id=? ORDER BY (effective_state='dismissed'),id", (task_id, listing_id)) if question_key(r["question"]) == key), None)
            now = utc_now_iso()
            check_id = existing["id"] if existing else conn.execute(
                "INSERT INTO candidate_checks(task_id,listing_id,question,request_key,created_at) VALUES (?,?,?,?,?)",
                (task_id, listing_id, row["question"], f"suggestion_{uuid4().hex}", now)).lastrowid
            conn.execute("UPDATE candidate_check_suggestions SET check_id=?,accepted_at=?,reused_existing=? WHERE id=?",
                (check_id, now, int(existing is not None), suggestion_id))
            return dict(suggestion_id=suggestion_id, check=self.dto(self.item(conn, task_id, listing_id, check_id)), reused_existing=existing is not None)
