"""Persistent monitoring scopes and one global collection worker."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import threading
import sqlite3

from shopping_agent.db import connect, initialize
from shopping_agent.monitor_engine import EngineError


class MonitorError(ValueError):
    pass


class MonitorStore:
    def __init__(self, config, *, clock=None):
        self.config = config
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        initialize(config.database_path)

    @contextmanager
    def transaction(self):
        with connect(self.config.database_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    @staticmethod
    def record(row):
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json"))
        result["collect_seller_profiles"] = bool(result["collect_seller_profiles"])
        return result

    def list(self, task_id):
        with connect(self.config.database_path) as conn:
            if not conn.execute("SELECT 1 FROM research_tasks WHERE id=?", (task_id,)).fetchone():
                raise MonitorError("研究任务不存在。")
            return [self.record(r) for r in conn.execute("SELECT * FROM monitors WHERE task_id=? ORDER BY id DESC LIMIT 50", (task_id,))]

    def create(self, task_id, *, keyword, max_pages=10, max_items=100,
               interval_seconds=1800, max_rounds=24, confirmed=False, collect_seller_profiles=False, reuse_active=True):
        if confirmed is not True:
            raise MonitorError("请确认本次监控的关键词、采集范围和频率。")
        if type(collect_seller_profiles) is not bool:
            raise MonitorError("请明确是否允许访问卖家主页及其商品和评价列表。")
        if not isinstance(keyword, str) or not 1 <= len(keyword.strip()) <= 120:
            raise MonitorError("关键词须为1至120字。")
        for value, low, high in ((max_pages, 1, 50), (max_items, 1, 1000),
                                 (interval_seconds, 60, 86400), (max_rounds, 1, 1000)):
            if type(value) is not int or not low <= value <= high:
                raise MonitorError("监控范围超出上限。")
        with self.transaction() as conn:
            if not conn.execute("SELECT 1 FROM research_tasks WHERE id=?", (task_id,)).fetchone():
                raise MonitorError("研究任务不存在。")
            # Repeated submissions of the currently authorized scope are idempotent.
            existing = conn.execute("""SELECT * FROM monitors WHERE task_id=? AND keyword=? AND
                max_pages=? AND max_items=? AND interval_seconds=? AND max_rounds=?
                AND collect_seller_profiles=? AND state IN ('waiting','running') ORDER BY id DESC LIMIT 1""",
                (task_id, keyword.strip(), max_pages, max_items, interval_seconds, max_rounds, int(collect_seller_profiles))).fetchone()
            if existing and reuse_active:
                return self.record(existing)
            now = self.clock().isoformat()
            cursor = conn.execute("""INSERT INTO monitors
                (task_id,keyword,max_pages,max_items,interval_seconds,max_rounds,collect_seller_profiles,state,next_run_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,'waiting',?,?,?)""",
                (task_id, keyword.strip(), max_pages, max_items, interval_seconds, max_rounds, int(collect_seller_profiles), now, now, now))
            return self.record(conn.execute("SELECT * FROM monitors WHERE id=?", (cursor.lastrowid,)).fetchone())

    def control(self, task_id, monitor_id, action):
        if action not in {"pause", "resume", "stop"}:
            raise MonitorError("未知监控操作。")
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM monitors WHERE id=? AND task_id=?", (monitor_id, task_id)).fetchone()
            if row is None:
                raise MonitorError("监控不属于当前任务。")
            now = self.clock().isoformat()
            if action == "resume":
                if row["rounds"] >= row["max_rounds"]:
                    raise MonitorError("已用完确认的轮次，请创建新的监控范围。")
                if row["state"] == "running" and row["desired_state"]:
                    raise MonitorError("正在停止采集，请等待退出。")
                if row["state"] in {"paused", "needs_attention", "stopped"}:
                    conn.execute("UPDATE monitors SET state='waiting',desired_state=NULL,next_run_at=?,error_code=NULL,updated_at=? WHERE id=?",
                                 (now, now, monitor_id))
            else:
                target = "stopped" if action == "stop" else "paused"
                if row["state"] != "stopped":
                    # Keep ownership until the process tree has actually exited.
                    if row["state"] == "running":
                        if row["desired_state"] != "stopped":
                            conn.execute("UPDATE monitors SET desired_state=?,updated_at=? WHERE id=?", (target, now, monitor_id))
                    else:
                        conn.execute("UPDATE monitors SET state=?,next_run_at=NULL,updated_at=? WHERE id=?", (target, now, monitor_id))
            return self.record(conn.execute("SELECT * FROM monitors WHERE id=?", (monitor_id,)).fetchone())

    def claim_due(self):
        guard = getattr(self, 'window_guard', None)
        if guard:
            guard()
        with self.transaction() as conn:
            if conn.execute("SELECT 1 FROM monitors WHERE state='running'").fetchone() or conn.execute(
                    "SELECT 1 FROM browser_jobs WHERE state IN ('queued','running')").fetchone():
                return None
            row = conn.execute("SELECT * FROM monitors WHERE state='waiting' AND next_run_at<=? ORDER BY next_run_at,id LIMIT 1", (self.clock().isoformat(),)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE monitors SET state='running',desired_state=NULL,updated_at=? WHERE id=?", (self.clock().isoformat(), row["id"]))
            return self.record(conn.execute("SELECT * FROM monitors WHERE id=?", (row["id"],)).fetchone())

    def finish(self, monitor_id, result):
        continuation = getattr(self, 'continue_window', None)
        continuous_window = bool(continuation and continuation(monitor_id))
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM monitors WHERE id=? AND state='running'", (monitor_id,)).fetchone()
            if row is None:
                return
            error = result.get("error_code")
            rounds = row["rounds"] + 1
            max_rounds = row['max_rounds']
            # Only explicitly confirmed SecondPick ongoing/timed windows roll
            # this internal counter. Legacy monitors keep their original quota.
            if continuous_window and not error and rounds >= max_rounds:
                max_rounds = rounds + 1000
            state = row["desired_state"] or ("needs_attention" if error else "stopped" if rounds >= max_rounds else "waiting")
            now = self.clock()
            next_run = (now + timedelta(seconds=row["interval_seconds"])).isoformat() if state == "waiting" else None
            conn.execute("""UPDATE monitors SET state=?,desired_state=NULL,rounds=?,imported=imported+?,
                result_json=?,error_code=?,next_run_at=?,updated_at=?,max_rounds=? WHERE id=?""",
                (state, rounds, result.get("imported", 0), json.dumps(result), error, next_run, now.isoformat(), max_rounds, monitor_id))

    def requested_stop(self, monitor_id):
        guard = getattr(self, 'window_guard', None)
        if guard:
            guard()
        with connect(self.config.database_path) as conn:
            return bool(conn.execute("SELECT desired_state FROM monitors WHERE id=?", (monitor_id,)).fetchone()[0])

    def recover_interrupted(self):
        with self.transaction() as conn:
            # A crash can happen after evidence/checkpoint commit but before
            # publishing progress or finish accounting. Recover saved totals
            # from this monitor's own product records, without counting cards.
            conn.execute("""UPDATE monitors SET imported=MAX(imported, (
                SELECT COUNT(*) FROM monitor_import_records mi WHERE mi.task_id=monitors.task_id
                AND mi.source_task='shopping-monitor-' || monitors.id AND mi.evidence_stage='product_record')),
                state='paused',desired_state=NULL,next_run_at=NULL,
                error_code='service_restarted',updated_at=? WHERE state IN ('running','waiting')""", (self.clock().isoformat(),))


def _database_busy(exc):
    code = getattr(exc, "sqlite_errorcode", None)
    return (isinstance(code, int) and code & 255 in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}) or str(exc).lower() in {"database is locked", "database table is locked"}


class MonitorCoordinator:
    def __init__(self, store, engine, *, poll_interval=.5):
        self.store, self.engine = store, engine
        self.poll_interval = poll_interval
        self.closed = threading.Event()
        self.thread = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, daemon=True, name="shopping-monitor")
            self.thread.start()

    def _loop(self):
        while not self.closed.is_set():
            try:
                monitor = self.store.claim_due()
            except sqlite3.OperationalError as exc:
                if not _database_busy(exc):
                    raise
                self.closed.wait(self.poll_interval)
                continue
            if monitor is None:
                self.closed.wait(self.poll_interval)
                continue
            stop = threading.Event()
            done = threading.Event()
            control_failed = threading.Event()

            def watch():
                while not done.wait(.1):
                    try:
                        requested = self.closed.is_set() or self.store.requested_stop(monitor["id"])
                    except sqlite3.Error:
                        control_failed.set()
                        requested = True  # Lost control channel: stop collection.
                    if requested:
                        stop.set()
                        return

            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
            try:
                result = self.engine.run(monitor, stop)
            except EngineError as exc:
                result = dict(imported=0, error_code=exc.code)
            except Exception:
                result = dict(imported=0, error_code="engine_failed")
            finally:
                done.set()
                watcher.join(timeout=2)
            if control_failed.is_set() and result.get("error_code") not in {"login_required", "verification_required"}:
                result["error_code"] = "engine_sync_failed"
            while True:
                try:
                    if self.closed.is_set():
                        self.store.control(monitor["task_id"], monitor["id"], "pause")
                    self.store.finish(monitor["id"], result)
                    break
                except sqlite3.OperationalError as exc:
                    if not _database_busy(exc):
                        raise
                    # Retry settlement, never rerun the platform round. Retain
                    # service ownership until this accounting is durable.
                    threading.Event().wait(self.poll_interval)

    def shutdown(self):
        self.closed.set()
        if self.thread is not None:
            self.thread.join(timeout=55)
            if self.thread.is_alive():
                raise RuntimeError("监控进程尚未完成清理。")
