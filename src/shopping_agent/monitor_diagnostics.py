"""Bounded diagnostic events with no free-text payloads or evidence deletion."""
from datetime import datetime, timedelta, timezone
import json
import re
import sqlite3

from shopping_agent.db import connect, utc_now_iso

MAX_EVENTS = 200
MAX_DAYS = 30
EVIDENCE_WARNING_BYTES = 64 * 1024 * 1024
PHASES = {"preflight", "process", "sync", "retention", "finished"}
CODES = {"round_started", "worker_bootstrap", "worker_timezone_check", "worker_engine_import", "worker_collecting", "worker_completed",
         "sync_progress", "sync_pending", "evidence_retained",
         "round_finished", "engine_not_configured", "engine_version_unsupported", "login_required",
         "verification_required", "engine_failed", "engine_dependencies_missing", "engine_save_failed",
         "engine_paused", "engine_timezone_missing", "engine_pipeline_failed", "engine_sync_failed",
         "engine_timeout", "cancelled"}
COUNTS = {"imported", "search_cards", "price_observations", "candidate_pool_count", "invalid", "duplicates", "evidence_bytes"}


def safe_counts(values):
    return {key: value for key, value in values.items()
            if key in COUNTS and type(value) is int and 0 <= value <= 2**63 - 1}


def retention_status(directory):
    size = sum((directory / f"{name}.jsonl").stat().st_size for name in ("products", "cards", "prices")
               if (directory / f"{name}.jsonl").is_file())
    return dict(policy="preserve_evidence", evidence_bytes=size, warning=size >= EVIDENCE_WARNING_BYTES,
                diagnostics_max_events=MAX_EVENTS, diagnostics_max_days=MAX_DAYS)


class MonitorDiagnostics:
    def __init__(self, config, monitor, round_id):
        if not re.fullmatch(r"[0-9a-f]{32}", round_id):
            raise ValueError("Invalid diagnostic round")
        self.config, self.monitor, self.round_id = config, monitor, round_id
        self.available = True

    def emit(self, phase, code, **counts):
        if phase not in PHASES or code not in CODES:
            raise ValueError("Invalid diagnostic category")
        try:
            if not self.config.database_path.is_file():
                self.available = False
                return False
            with connect(self.config.database_path, timeout=.25) as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute("""INSERT INTO monitor_diagnostic_events
                    (task_id,monitor_id,round_id,phase,code,counts_json,created_at)
                    SELECT task_id,id,?,?,?,?,? FROM monitors WHERE id=? AND task_id=?""",
                    (self.round_id, phase, code, json.dumps(safe_counts(counts)), utc_now_iso(),
                     self.monitor["id"], self.monitor["task_id"]))
                if cursor.rowcount == 0:
                    self.available = False
                    return False
                cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_DAYS)).isoformat()
                conn.execute("DELETE FROM monitor_diagnostic_events WHERE created_at<?", (cutoff,))
                conn.execute("""DELETE FROM monitor_diagnostic_events WHERE monitor_id=? AND id NOT IN (
                    SELECT id FROM monitor_diagnostic_events WHERE monitor_id=? ORDER BY id DESC LIMIT ?)""",
                    (self.monitor["id"], self.monitor["id"], MAX_EVENTS))
            return True
        except (OSError, sqlite3.Error):
            self.available = False
            return False  # Diagnostic failure cannot discard collected evidence.


def diagnostic_events(config, task_id, monitor_id, *, before_id=None, limit=50):
    if type(limit) is not int or not 1 <= limit <= 100 or before_id is not None and (type(before_id) is not int or before_id < 1):
        raise ValueError("Invalid diagnostic page")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_DAYS)).isoformat()
    with connect(config.database_path) as conn:
        if not conn.execute("SELECT 1 FROM monitors WHERE id=? AND task_id=?", (monitor_id, task_id)).fetchone():
            raise ValueError("监控不属于当前任务。")
        rows = conn.execute("""SELECT id,round_id,phase,code,counts_json,created_at FROM monitor_diagnostic_events
            WHERE task_id=? AND monitor_id=? AND created_at>=? AND (? IS NULL OR id<?)
            ORDER BY id DESC LIMIT ?""", (task_id, monitor_id, cutoff, before_id, before_id, limit + 1)).fetchall()
    items = []
    for row in rows[:limit]:
        item = dict(row)
        try:
            values = json.loads(item.pop("counts_json"))
            item["counts"] = safe_counts(values) if isinstance(values, dict) else {}
        except (ValueError, TypeError, RecursionError):
            item["counts"] = {}
        if item["phase"] not in PHASES or item["code"] not in CODES or not re.fullmatch(r"[0-9a-f]{32}", item["round_id"]):
            continue
        items.append(item)
    more = len(rows) > limit
    return dict(items=items, has_more=more, next_before_id=rows[limit - 1]["id"] if more else None,
                retention=dict(max_events=MAX_EVENTS, max_days=MAX_DAYS))
