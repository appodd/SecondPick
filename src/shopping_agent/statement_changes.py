"""Append-only corrections; the original statement and message are immutable."""
from shopping_agent.db import utc_now_iso


def change_statement(conn, task_id, statement_id, *, action, expected_revision_id, listing_id=None, kind=None):
    # Imported here to avoid the store/module import cycle.
    from shopping_agent.conversation_store import InvalidActionRequestError, RecordNotFoundError, OperationConflictError
    if (type(expected_revision_id) is not int or not 0 <= expected_revision_id <= 2**63-1
            or not isinstance(action, str) or action not in {"withdraw", "rebind"}):
        raise InvalidActionRequestError("Invalid statement correction")
    row = conn.execute("SELECT * FROM candidate_statement_current WHERE task_id=? AND id=?", (task_id, statement_id)).fetchone()
    if row is None:
        raise RecordNotFoundError("Statement not found in this task")
    if action == "withdraw":
        if listing_id is not None or kind is not None:
            raise InvalidActionRequestError("Withdrawal cannot change attribution")
        listing_id, kind = row["listing_id"], row["kind"]
    elif (type(listing_id) is not int or not 0 < listing_id <= 2**63-1
          or not isinstance(kind, str) or kind not in {"seller_reply", "user_observation"}):
        raise InvalidActionRequestError("Invalid new statement attribution")
    latest = conn.execute("SELECT * FROM candidate_statement_changes WHERE id=?", (row["revision_id"],)).fetchone()
    if row["revision_id"] != expected_revision_id:
        if not (latest and latest["previous_revision_id"] == expected_revision_id and latest["action"] == action
                and latest["new_listing_id"] == listing_id and latest["new_kind"] == kind):
            raise OperationConflictError("补充已被其他操作修改，请刷新后重试。")
        return dict(row)
    if row["status"] == "withdrawn":
        if action == "withdraw":
            return dict(row)
        raise OperationConflictError("已撤回的补充不能改绑或恢复，请重新发送补充。")
    if action == "rebind":
        if not conn.execute("SELECT 1 FROM listing_snapshots s JOIN task_runs t ON t.run_id=s.run_id WHERE t.task_id=? AND s.listing_id=? LIMIT 1", (task_id, listing_id)).fetchone():
            raise InvalidActionRequestError("Statement candidate is outside this task's saved scope")
        if row["listing_id"] == listing_id and row["kind"] == kind:
            return dict(row)
    conn.execute("INSERT INTO candidate_statement_changes(statement_id,previous_revision_id,action,old_listing_id,new_listing_id,new_kind,created_at) VALUES (?,?,?,?,?,?,?)",
                 (statement_id, expected_revision_id, action, row["listing_id"], listing_id, kind, utc_now_iso()))
    return dict(conn.execute("SELECT * FROM candidate_statement_current WHERE id=?", (statement_id,)).fetchone())
