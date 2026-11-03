"""Bounded history reads with independent keyset positions and fixed watermarks."""
from __future__ import annotations

import base64
import json

from shopping_agent.assessment import evidence_state, serialize_assessment
from shopping_agent.history_review import serialize_review, serialize_comparison


TABLES = {"assessment_batches": "research_assessments", "reviews": "history_reviews", "comparisons": "comparison_snapshots"}


def require_task(conn, task_id):
    if not conn.execute("SELECT 1 FROM research_tasks WHERE id=?", (task_id,)).fetchone():
        raise ValueError(f"Research task not found: {task_id}")


def revision_id(conn, task_id):
    return conn.execute("SELECT COALESCE(MAX(id),0) FROM task_preference_revisions WHERE task_id=?", (task_id,)).fetchone()[0]


def decode_cursor(cursor, task_id):
    try:
        if len(cursor) > 4096:
            raise ValueError
        data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if set(data) != {"v", "task_id", "upper", "before"} or type(data["v"]) is not int or data["v"] != 1 or type(data["task_id"]) is not int or data["task_id"] != task_id:
            raise ValueError
        if set(data["upper"]) != set(TABLES) or set(data["before"]) != set(TABLES):
            raise ValueError
        for key in TABLES:
            upper, before = data["upper"][key], data["before"][key]
            if type(upper) is not int or type(before) is not int or not 0 <= upper < 2**63-1 or not 0 <= before <= upper+1:
                raise ValueError
        return data
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise ValueError("Invalid research history cursor for this task.") from exc


def page_rows(conn, task_id, table, upper, before, limit):
    # Table names originate only from TABLES above, never from the cursor.
    rows = conn.execute(f"SELECT * FROM {table} WHERE task_id=? AND id<=? AND id<? ORDER BY id DESC LIMIT ?",
                        (task_id, upper, before, limit+1)).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return rows, rows[-1]["id"] if has_more else 0


def research_page(conn, task_id, limit=10, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Research history limit must be between 1 and 20.")
    require_task(conn, task_id)
    if cursor is None:
        upper = {key: conn.execute(f"SELECT COALESCE(MAX(id),0) FROM {table} WHERE task_id=?", (task_id,)).fetchone()[0] for key, table in TABLES.items()}
        data = dict(v=1, task_id=task_id, upper=upper, before={key: value+1 for key, value in upper.items()})
    else:
        data = decode_cursor(cursor, task_id)
    revision = revision_id(conn, task_id)
    current_signature, dependencies = evidence_state(conn, task_id)
    output = {}
    standard_ids = set()
    totals, returned = {}, {}
    next_before = {}
    for key, table in TABLES.items():
        rows, next_before[key] = page_rows(conn, task_id, table, data["upper"][key], data["before"][key], limit)
        totals[key] = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE task_id=? AND id<=?", (task_id, data["upper"][key])).fetchone()[0]
        returned[key] = len(rows)
        output[key] = []
        for row in reversed(rows):
            standard_ids.add(row["standard_id"])
            if key == "assessment_batches":
                record = dict(row)
                record["preference_revision_id"] = conn.execute("SELECT preference_revision_id FROM requirement_standards WHERE id=? AND task_id=?", (row["standard_id"], task_id)).fetchone()[0]
                output[key].append(serialize_assessment(record, revision, current_signature, dependencies))
            elif key == "reviews":
                operation = conn.execute("SELECT state,error_detail FROM operations WHERE id=? AND task_id=?", (row["operation_id"], task_id)).fetchone()
                output[key].append(serialize_review(conn, {**dict(row), **dict(operation)}, revision, current_signature))
            else:
                output[key].append(serialize_comparison(row, revision, current_signature))
    current_standard = conn.execute("SELECT id FROM requirement_standards WHERE task_id=? AND preference_revision_id=?", (task_id, revision)).fetchone()
    if current_standard:
        standard_ids.add(current_standard[0])
    output["standards"] = []
    for standard_id in sorted(standard_ids):
        row = conn.execute("SELECT * FROM requirement_standards WHERE id=? AND task_id=?", (standard_id, task_id)).fetchone()
        if row:
            standard = dict(row)
            standard["criteria"] = json.loads(standard.pop("criteria_json"))
            standard["stale"] = standard["preference_revision_id"] != revision
            output["standards"].append(standard)
    has_more = any(next_before.values())
    next_cursor = base64.urlsafe_b64encode(json.dumps({**data, "before": next_before}, separators=(",", ":")).encode()).decode() if has_more else None
    output["page"] = dict(limit=limit, has_more=has_more, next_cursor=next_cursor, total_counts=totals, returned_counts=returned,
                          preference_revision_id=revision, evidence_signature=current_signature)
    return output


def assessment_detail(conn, task_id, assessment_id):
    require_task(conn, task_id)
    row = conn.execute("SELECT a.*,s.preference_revision_id FROM research_assessments a JOIN requirement_standards s ON s.id=a.standard_id AND s.task_id=a.task_id WHERE a.id=? AND a.task_id=?", (assessment_id, task_id)).fetchone()
    if row is None:
        return None
    current_signature, dependencies = evidence_state(conn, task_id)
    return serialize_assessment(row, revision_id(conn, task_id), current_signature, dependencies)
