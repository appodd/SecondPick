"""User-managed follow-up questions, separate from facts and model judgments."""
from contextlib import closing, contextmanager
import re

from shopping_agent.conversation_store import InvalidActionRequestError, OperationConflictError, RecordNotFoundError
from shopping_agent.db import connect, utc_now_iso


class CandidateChecks:
    def __init__(self, config):
        self.config = config

    @contextmanager
    def connection(self, *, write=False):
        with closing(connect(self.config.database_path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn

    @staticmethod
    def scope(conn, task_id, listing_id):
        if not conn.execute("SELECT 1 FROM research_tasks WHERE id=?", (task_id,)).fetchone():
            raise RecordNotFoundError("Task not found")
        if not conn.execute("SELECT 1 FROM listing_snapshots s JOIN task_runs t ON t.run_id=s.run_id WHERE t.task_id=? AND s.listing_id=? LIMIT 1",
                            (task_id, listing_id)).fetchone():
            raise RecordNotFoundError("商品不在当前任务保存范围内。")

    @staticmethod
    def item(conn, task_id, listing_id, check_id):
        row = conn.execute("SELECT * FROM candidate_check_current WHERE task_id=? AND listing_id=? AND id=?",
                           (task_id, listing_id, check_id)).fetchone()
        if row is None:
            raise RecordNotFoundError("核实事项不在当前商品内。")
        return row

    @staticmethod
    def dto(row):
        keys = ("id", "task_id", "listing_id", "question", "created_at", "revision_id", "state", "effective_state",
                "statement_id", "statement_revision_id", "statement_kind", "statement_text", "note", "changed_at")
        return dict(**{key: row[key] for key in keys}, evidence_current=bool(row["evidence_current"]),
                    needs_recheck=row["state"] == "evidence_linked" and not row["evidence_current"])

    def create(self, task_id, listing_id, *, question, request_key):
        if (not isinstance(question, str) or not question.strip() or len(question) > 1000
                or not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", request_key)):
            raise InvalidActionRequestError("请填写有效的核实问题。")
        with self.connection(write=True) as conn:
            self.scope(conn, task_id, listing_id)
            old = conn.execute("SELECT * FROM candidate_checks WHERE task_id=? AND request_key=?", (task_id, request_key)).fetchone()
            if old:
                if old["listing_id"] != listing_id or old["question"] != question:
                    raise OperationConflictError("该保存请求已用于其他核实事项。")
                check_id = old["id"]
            else:
                check_id = conn.execute("INSERT INTO candidate_checks(task_id,listing_id,question,request_key,created_at) VALUES (?,?,?,?,?)",
                    (task_id, listing_id, question, request_key, utc_now_iso())).lastrowid
            return self.dto(self.item(conn, task_id, listing_id, check_id))

    def change(self, task_id, listing_id, check_id, *, expected_revision_id, state,
               statement_id=None, statement_revision_id=None, note=None):
        integer = lambda v, minimum: type(v) is int and minimum <= v <= 2**63-1
        if (not integer(expected_revision_id, 0) or not isinstance(state, str) or state not in {"pending", "evidence_linked", "dismissed"}
                or (note is not None and (not isinstance(note, str) or not note.strip() or len(note) > 2000))):
            raise InvalidActionRequestError("无效的核实事项更新。")
        if state == "evidence_linked":
            if not integer(statement_id, 1) or not integer(statement_revision_id, 0):
                raise InvalidActionRequestError("请选择当前商品的有效补充。")
        elif statement_id is not None or statement_revision_id is not None:
            raise InvalidActionRequestError("此状态不能关联补充。")
        with self.connection(write=True) as conn:
            self.scope(conn, task_id, listing_id)
            row = self.item(conn, task_id, listing_id, check_id)
            same = (row["state"], row["statement_id"], row["statement_revision_id"], row["note"]) == (state, statement_id, statement_revision_id, note)
            if row["revision_id"] != expected_revision_id:
                last = conn.execute("SELECT previous_revision_id FROM candidate_check_changes WHERE id=?", (row["revision_id"],)).fetchone()
                if not (same and last and last[0] == expected_revision_id):
                    raise OperationConflictError("核实事项已更新，请刷新后重试。")
                return self.dto(row)
            if same:
                return self.dto(row)
            kind = None
            if statement_id is not None:
                source = conn.execute("SELECT s.* FROM candidate_statement_current s JOIN conversation_messages m ON m.id=s.source_message_id AND m.task_id=s.task_id AND m.role='user' WHERE s.id=? AND s.task_id=? AND s.listing_id=? AND s.status='active'",
                                      (statement_id, task_id, listing_id)).fetchone()
                if source is None or source["revision_id"] != statement_revision_id:
                    raise OperationConflictError("补充已撤回或归属/类型已更改，请刷新后重新选择。")
                kind = source["kind"]
            conn.execute("INSERT INTO candidate_check_changes(check_id,previous_revision_id,state,statement_id,statement_revision_id,statement_kind,note,created_at) VALUES (?,?,?,?,?,?,?,?)",
                         (check_id, expected_revision_id, state, statement_id, statement_revision_id, kind, note, utc_now_iso()))
            return self.dto(self.item(conn, task_id, listing_id, check_id))

    def page(self, task_id, listing_id, *, limit=20, before_id=None):
        if type(limit) is not int or not 1 <= limit <= 50 or (before_id is not None and (type(before_id) is not int or not 0 < before_id <= 2**63-1)):
            raise InvalidActionRequestError("Invalid checklist page")
        with self.connection() as conn:
            self.scope(conn, task_id, listing_id)
            where, args = "task_id=? AND listing_id=?", [task_id, listing_id]
            counts = {state: 0 for state in ("pending", "evidence_linked", "dismissed")}
            for row in conn.execute(f"SELECT effective_state,COUNT(*) AS n FROM candidate_check_current WHERE {where} GROUP BY effective_state", args):
                counts[row["effective_state"]] = row["n"]
            clause = " AND id<?" if before_id is not None else ""
            rows = list(conn.execute(f"SELECT * FROM candidate_check_current WHERE {where}{clause} ORDER BY id DESC LIMIT ?",
                                    (*args, *([before_id] if before_id is not None else []), limit+1)))
            sources = list(conn.execute("SELECT s.id,s.revision_id,s.kind,m.content AS statement_text FROM candidate_statement_current s JOIN conversation_messages m ON m.id=s.source_message_id AND m.task_id=s.task_id AND m.role='user' WHERE s.task_id=? AND s.listing_id=? AND s.status='active' ORDER BY s.id DESC LIMIT 20", args))
            source_count = conn.execute("SELECT COUNT(*) FROM candidate_statement_current s JOIN conversation_messages m ON m.id=s.source_message_id AND m.task_id=s.task_id AND m.role='user' WHERE s.task_id=? AND s.listing_id=? AND s.status='active'", args).fetchone()[0]
            return dict(items=[self.dto(row) for row in rows[:limit]], total_count=sum(counts.values()), counts=counts,
                        has_more=len(rows)>limit, next_before_id=rows[limit-1]["id"] if len(rows)>limit else None,
                        available_statements=[dict(row) for row in sources], statement_count=source_count,
                        statements_truncated=source_count>20)
