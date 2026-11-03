"""Bounded web task metadata; CLI exports retain their complete history contract."""
import base64
import json

from shopping_agent.task_coverage import build_search_coverage


TABLES = {"preference_revisions": "task_preference_revisions", "runs": "task_runs", "reports": "saved_reports"}


def cursor_data(cursor, task_id):
    try:
        if len(cursor) > 4096:
            raise ValueError
        data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if set(data) != {"v", "task_id", "upper", "before"} or type(data["v"]) is not int or data["v"] != 1 or type(data["task_id"]) is not int or data["task_id"] != task_id:
            raise ValueError
        for key in ("upper", "before"):
            if set(data[key]) != set(TABLES):
                raise ValueError
        for key in TABLES:
            upper, before = data["upper"][key], data["before"][key]
            if type(upper) is not int or type(before) is not int or not 0 <= upper < 2**63-1 or not 0 <= before <= upper+1:
                raise ValueError
        return data
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise ValueError("Invalid task history cursor for this task.") from exc


def revision_record(row):
    item = dict(row)
    item["added_preferences"] = json.loads(item.pop("added_preferences_json"))
    item["removed_preferences"] = json.loads(item.pop("removed_preferences_json"))
    return item


def run_record(conn, row):
    run_id = row["run_id"]
    run = conn.execute("SELECT goal,city,created_at FROM search_runs WHERE id=?", (run_id,)).fetchone()
    queries = [r[0] for r in conn.execute("SELECT query_text FROM queries WHERE run_id=? GROUP BY query_text ORDER BY MIN(id) LIMIT 21", (run_id,))]
    return dict(run_id=run_id, role=row["role"], notes=row["notes"], goal=run["goal"], city=run["city"],
        run_created_at=run["created_at"], attached_at=row["created_at"], source_queries=queries[:20], source_queries_truncated=len(queries) > 20,
        query_count=conn.execute("SELECT COUNT(*) FROM queries WHERE run_id=?", (run_id,)).fetchone()[0], **{f"{kind}_snapshot_count": conn.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,)).fetchone()[0]
                                   for kind, table in (("page", "page_snapshots"), ("listing", "listing_snapshots"))})


def coverage(conn, task_id, selected_runs):
    # Aggregate the full saved scope, but hydrate query texts only for this page.
    # This avoids the full summary's per-run joins and historical text loading.
    run_ids = [r[0] for r in conn.execute("SELECT run_id FROM task_runs WHERE task_id=? ORDER BY id", (task_id,))]
    listings = {}
    for row in conn.execute("SELECT DISTINCT s.run_id,s.listing_id FROM listing_snapshots s JOIN task_runs t ON t.run_id=s.run_id WHERE t.task_id=?", (task_id,)):
        listings.setdefault(row["run_id"], set()).add(row["listing_id"])
    selected = {r["run_id"]: r["source_queries"] for r in selected_runs}
    result = build_search_coverage([dict(run_id=i, source_queries=selected.get(i, [])) for i in run_ids], listings)
    result["runs"] = [r for r in result["runs"] if r["run_id"] in selected]
    return result


def history_page(conn, task_id, limit=10, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Task history limit must be between 1 and 20.")
    if not conn.execute("SELECT 1 FROM research_tasks WHERE id=?", (task_id,)).fetchone():
        raise ValueError(f"Research task not found: {task_id}")
    if cursor is None:
        upper = {key: conn.execute(f"SELECT COALESCE(MAX(id),0) FROM {table} WHERE task_id=?", (task_id,)).fetchone()[0] for key, table in TABLES.items()}
        data = dict(v=1, task_id=task_id, upper=upper, before={key: value+1 for key, value in upper.items()})
    else:
        data = cursor_data(cursor, task_id)
    result, totals, next_before = {}, {}, {}
    for key, table in TABLES.items():
        rows = conn.execute(f"SELECT * FROM {table} WHERE task_id=? AND id<=? AND id<? ORDER BY id DESC LIMIT ?",
                            (task_id, data["upper"][key], data["before"][key], limit+1)).fetchall()
        next_before[key] = rows[limit-1]["id"] if len(rows) > limit else 0
        totals[key] = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE task_id=? AND id<=?", (task_id, data["upper"][key])).fetchone()[0]
        rows = list(reversed(rows[:limit]))
        if key == "preference_revisions":
            result[key] = [revision_record(row) for row in rows]
        elif key == "runs":
            result[key] = [run_record(conn, row) for row in rows]
        else:
            result[key] = [{k: v for k, v in dict(row).items() if k not in {"task_id", "path"}} for row in rows]
    result["search_coverage"] = coverage(conn, task_id, result["runs"])
    has_more = any(next_before.values())
    next_cursor = base64.urlsafe_b64encode(json.dumps({**data, "before": next_before}, separators=(",", ":")).encode()).decode() if has_more else None
    result["history_page"] = dict(limit=limit, has_more=has_more, next_cursor=next_cursor, total_counts=totals)
    return result


def task_summary(conn, task_id, limit=10):
    result = history_page(conn, task_id, limit)
    task = dict(conn.execute("SELECT * FROM research_tasks WHERE id=?", (task_id,)).fetchone())
    current = conn.execute("SELECT id,effective_goal FROM task_preference_revisions WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    task.update(original_goal=task["goal"], effective_goal=current["effective_goal"] if current else task["goal"])
    result["task"] = task
    result["preference_revision_id"] = current["id"] if current else 0
    # Preserve the overview's delta-list semantics even when earlier revisions
    # are off-page. The authoritative current goal is read independently above.
    preferences = {}
    for row in conn.execute("SELECT added_preferences_json,removed_preferences_json FROM task_preference_revisions WHERE task_id=? ORDER BY id", (task_id,)):
        for text in json.loads(row["removed_preferences_json"]):
            preferences.pop(text, None)
        for text in json.loads(row["added_preferences_json"]):
            preferences[text] = None
    result["current_preferences"] = list(preferences)[-50:]
    result["current_preferences_truncated"] = len(preferences) > 50
    return result
