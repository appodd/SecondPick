"""Append-only user records about questions, never independent certification."""
import json
import re

from shopping_agent.assessment import evidence_state, signature
from shopping_agent.candidate_checks import CandidateChecks
from shopping_agent.conversation_store import InvalidActionRequestError, OperationConflictError
from shopping_agent.db import utc_now_iso


def review_basis(conn, task_id):
    revision = conn.execute("SELECT COALESCE(MAX(id),0) FROM task_preference_revisions WHERE task_id=?", (task_id,)).fetchone()[0]
    return revision, evidence_state(conn, task_id)[1]


def basis_token(basis, listing_id):
    return signature([basis[0], basis[1].get(str(listing_id))])


def latest_review(conn, check_id):
    return conn.execute("SELECT * FROM candidate_check_reviews WHERE check_id=? ORDER BY id DESC LIMIT 1", (check_id,)).fetchone()


def review_dto(conn, row, check, basis, *, superseded=False):
    if row is None:
        return None
    sources = []
    valid = True
    for source in json.loads(row["sources_json"]):
        current = conn.execute("SELECT s.*,m.content,m.role FROM candidate_statement_current s JOIN conversation_messages m ON m.id=s.source_message_id AND m.task_id=s.task_id WHERE s.id=? AND s.task_id=?", (source["statement_id"], check["task_id"])).fetchone()
        active = bool(current and current["status"] == "active" and current["role"] == "user" and current["listing_id"] == check["listing_id"] and current["revision_id"] == source["revision_id"])
        valid = valid and active
        sources.append(dict(**source, statement_text=current["content"] if current else None, current=active))
    valid = (valid and row["check_revision_id"] == check["revision_id"] and check["effective_state"] != "dismissed"
             and row["preference_revision_id"] == basis[0] and row["dependency_signature"] == basis[1].get(str(check["listing_id"])))
    status = "superseded" if superseded else "withdrawn" if row["action"] == "withdraw" else "current" if valid else "needs_recheck"
    return dict(**{key: row[key] for key in ("id", "check_id", "check_revision_id", "action", "outcome", "summary", "created_at")},
        sources=sources, status=status, independently_verified=False)


class CheckReviews(CandidateChecks):
    def page(self, task_id, listing_id, check_id, *, limit=20, before_id=None):
        if type(limit) is not int or not 1 <= limit <= 50 or (before_id is not None and (type(before_id) is not int or not 0 < before_id <= 2**63-1)):
            raise InvalidActionRequestError("Invalid review page")
        with self.connection() as conn:
            self.scope(conn, task_id, listing_id)
            check = self.item(conn, task_id, listing_id, check_id)
            basis = review_basis(conn, task_id)
            latest = latest_review(conn, check_id)
            clause = " AND id<?" if before_id is not None else ""
            rows = list(conn.execute(f"SELECT * FROM candidate_check_reviews WHERE check_id=?{clause} ORDER BY id DESC LIMIT ?", (check_id, *([before_id] if before_id is not None else []), limit+1)))
            count = conn.execute("SELECT COUNT(*) FROM candidate_check_reviews WHERE check_id=?", (check_id,)).fetchone()[0]
            return dict(items=[review_dto(conn, r, check, basis, superseded=r["id"] != latest["id"]) for r in rows[:limit]],
                current_review=review_dto(conn, latest, check, basis), latest_review_id=latest["id"] if latest else 0,
                basis_token=basis_token(basis, listing_id), check_revision_id=check["revision_id"], total_count=count,
                has_more=len(rows)>limit, next_before_id=rows[limit-1]["id"] if len(rows)>limit else None)

    def change(self, task_id, listing_id, check_id, *, expected_review_id, expected_check_revision_id,
               expected_basis_token, action, outcome=None, summary=None, sources=()):
        integer = lambda v, minimum=0: type(v) is int and minimum <= v <= 2**63-1
        if (not integer(expected_review_id) or not integer(expected_check_revision_id) or not isinstance(expected_basis_token, str)
                or not re.fullmatch(r"[a-f0-9]{64}", expected_basis_token) or action not in ("record", "withdraw")):
            raise InvalidActionRequestError("无效的核实记录请求。")
        if not isinstance(sources, (list, tuple)) or len(sources)>5 or any(not isinstance(s, dict) or set(s)!={"statement_id", "revision_id"} or not integer(s["statement_id"], 1) or not integer(s["revision_id"]) for s in sources):
            raise InvalidActionRequestError("请选择最多 5 条当前有效的补充原文。")
        sources = sorted(sources, key=lambda s: s["statement_id"])
        if len({s["statement_id"] for s in sources}) != len(sources):
            raise InvalidActionRequestError("来源不能重复。")
        if action == "record":
            if (outcome not in ("answered", "uncertain", "conflict") or not isinstance(summary, str) or not summary.strip() or len(summary)>2000
                    or len(sources) < (2 if outcome == "conflict" else 1)):
                raise InvalidActionRequestError("请填写记录说明并选择来源；冲突至少需要两条不同原文。")
        elif outcome is not None or summary is not None or sources:
            raise InvalidActionRequestError("撤回不携带新的结论或来源。")
        with self.connection(write=True) as conn:
            self.scope(conn, task_id, listing_id)
            check = self.item(conn, task_id, listing_id, check_id)
            last = latest_review(conn, check_id)
            basis = review_basis(conn, task_id)
            last_sources = [{k: s[k] for k in ("statement_id", "revision_id")} for s in json.loads(last["sources_json"])] if last else []
            same = bool(last and (last["action"], last["outcome"], last["summary"], last["check_revision_id"], last["basis_token"], last_sources) ==
                (action, outcome, summary, expected_check_revision_id, expected_basis_token, sources))
            if expected_review_id != (last["id"] if last else 0):
                if same and last["previous_review_id"] == expected_review_id:
                    return review_dto(conn, last, check, basis)
                raise OperationConflictError("核实记录已更新，请刷新后核对再保存。")
            if same:
                return review_dto(conn, last, check, basis)
            if check["revision_id"] != expected_check_revision_id or expected_basis_token != basis_token(basis, listing_id):
                raise OperationConflictError("问题、要求或商品证据已变化，请刷新后重新核对。")
            if action == "record" and check["effective_state"] == "dismissed":
                raise OperationConflictError("此问题已暂不跟进，请先重新核实。")
            if action == "withdraw" and (last is None or last["action"] == "withdraw"):
                raise InvalidActionRequestError("没有可撤回的核实记录。")
            stored = []
            for source in sources:
                current = conn.execute("SELECT s.* FROM candidate_statement_current s JOIN conversation_messages m ON m.id=s.source_message_id AND m.task_id=s.task_id AND m.role='user' WHERE s.id=? AND s.task_id=? AND s.listing_id=? AND s.status='active'", (source["statement_id"], task_id, listing_id)).fetchone()
                if current is None or current["revision_id"] != source["revision_id"]:
                    raise OperationConflictError("补充已撤回或归属/类型已变，请重新选择来源。")
                stored.append(dict(**source, kind=current["kind"]))
            row_id = conn.execute("INSERT INTO candidate_check_reviews(check_id,previous_review_id,check_revision_id,action,outcome,summary,sources_json,preference_revision_id,dependency_signature,basis_token,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (check_id, expected_review_id, expected_check_revision_id, action, outcome, summary, json.dumps(stored, ensure_ascii=False),
                 basis[0], basis[1][str(listing_id)], expected_basis_token, utc_now_iso())).lastrowid
            row = conn.execute("SELECT * FROM candidate_check_reviews WHERE id=?", (row_id,)).fetchone()
            return review_dto(conn, row, check, basis)
