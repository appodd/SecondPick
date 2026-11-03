from __future__ import annotations

import asyncio
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

from shopping_agent.config import AppConfig
from shopping_agent.conversation_store import ConversationStore
from shopping_agent.db import connect, initialize, utc_now_iso

ACTIVE = {"queued", "running"}
AUDIT_FIELDS = {"operation", "listing_id", "page_index", "completed_pages", "requested_pages",
    "scheduled_delay_ms", "since_previous_attempt_ms", "recent_attempt_count_30m", "cleared",
    "state", "error_code", "page_kind", "captured_pages", "stop_reason"}
AUDIT_EVENTS = {"page_attempt", "verification_required", "manual_continue", "verification_check",
    "page_completed", "search_completed", "job_finished", "login_check"}


class BrowserJobError(RuntimeError):
    def __init__(self, code: str, detail: str, status: int = 409):
        super().__init__(detail)
        self.code, self.status = code, status


class BrowserJobStore:
    def __init__(self, config: AppConfig):
        self.config = config
        initialize(config.database_path)
        self.conversations = ConversationStore(config)

    @contextmanager
    def transaction(self):
        connection = connect(self.config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _record(row):
        if row is None:
            raise BrowserJobError("not_found", "Browser job not found.", 404)
        value = dict(row)
        for name in ("actions", "listing_ids", "result"):
            value[name] = json.loads(value.pop(f"{name}_json"))
        value["verify_requested"] = bool(value["verify_requested"])
        value["stop_requested"] = bool(value["stop_requested"])
        return value

    def get(self, job_id):
        with self.transaction() as conn:
            return self._record(conn.execute("SELECT * FROM browser_jobs WHERE id=?", (job_id,)).fetchone())

    @staticmethod
    def _append_event(conn, job_id, event_type, metadata, now=None):
        if event_type not in AUDIT_EVENTS or set(metadata) - AUDIT_FIELDS:
            raise ValueError("Unsupported browser audit event or metadata")
        if any(value is not None and type(value) not in {str, int, bool} for value in metadata.values()):
            raise ValueError("Unsupported browser audit value")
        conn.execute("INSERT INTO browser_job_events(job_id,event_type,metadata_json,created_at) VALUES(?,?,?,?)",
                     (job_id, event_type, json.dumps(metadata, ensure_ascii=False), now or utc_now_iso()))

    def record_event(self, job_id, event_type, metadata):
        with self.transaction() as conn:
            self._record(conn.execute("SELECT * FROM browser_jobs WHERE id=?", (job_id,)).fetchone())
            self._append_event(conn, job_id, event_type, metadata)

    def record_attempt(self, job_id, metadata):
        with self.transaction() as conn:
            now = datetime.now(timezone.utc)
            previous = conn.execute("SELECT created_at FROM browser_job_events WHERE event_type='page_attempt' ORDER BY id DESC LIMIT 1").fetchone()
            count = conn.execute("SELECT COUNT(*) FROM browser_job_events WHERE event_type='page_attempt' AND created_at>=?",
                                 ((now - timedelta(minutes=30)).isoformat(),)).fetchone()[0]
            self._append_event(conn, job_id, "page_attempt", {**metadata,
                "since_previous_attempt_ms": max(0, round((now - datetime.fromisoformat(previous["created_at"])).total_seconds()*1000)) if previous else None,
                "recent_attempt_count_30m": count + 1}, now.isoformat())

    def events(self, job_id, limit=100):
        with self.transaction() as conn:
            self._record(conn.execute("SELECT * FROM browser_jobs WHERE id=?", (job_id,)).fetchone())
            rows = conn.execute("SELECT * FROM browser_job_events WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, limit + 1)).fetchall()
            return {"job_id": job_id, "has_more": len(rows) > limit, "items": [
                {"id": row["id"], "event_type": row["event_type"], "metadata": json.loads(row["metadata_json"]), "created_at": row["created_at"]}
                for row in reversed(rows[:limit])]}

    def latest_for_request(self, task_id, request_id):
        with self.transaction() as conn:
            request = conn.execute("SELECT * FROM action_requests WHERE id=? AND task_id=?", (request_id, task_id)).fetchone()
            if request is None:
                raise BrowserJobError("not_found", "Action request not found in this task.", 404)
            row = conn.execute("SELECT * FROM browser_jobs WHERE request_id=? ORDER BY id DESC LIMIT 1", (request_id,)).fetchone()
            return self._record(row) if row else None

    def status(self):
        with self.transaction() as conn:
            active = conn.execute("SELECT * FROM browser_jobs WHERE state IN ('queued','running') LIMIT 1").fetchone()
            login = conn.execute("SELECT * FROM browser_jobs WHERE kind='login' ORDER BY id DESC LIMIT 1").fetchone()
            auth = conn.execute("SELECT state FROM browser_auth WHERE id=1").fetchone()["state"]
        return {"auth_status": auth, "active_job": self._record(active) if active else None,
                "login_job": self._record(login) if login else None}

    def set_auth(self, state):
        if state not in {"unknown", "verified", "invalid"}:
            raise ValueError("Invalid authentication state")
        with self.transaction() as conn:
            conn.execute("UPDATE browser_auth SET state=? WHERE id=1", (state,))

    @staticmethod
    def _ensure_free(conn):
        if conn.execute("SELECT 1 FROM monitors WHERE state='running'").fetchone():
            raise BrowserJobError("browser_busy", "监控正在采集，请先暂停监控并等待采集退出。")
        if conn.execute("SELECT 1 FROM browser_jobs WHERE state IN ('queued','running')").fetchone():
            raise BrowserJobError("browser_busy", "浏览器正在登录或采集，请等待完成或先停止。")

    def create_login(self):
        if not self.config.allow_login or "xianyu" not in self.config.platforms:
            raise BrowserJobError("login_disabled", "配置未启用闲鱼登录。", 400)
        with self.transaction() as conn:
            active = conn.execute("SELECT * FROM browser_jobs WHERE kind='login' AND state IN ('queued','running')").fetchone()
            if active:
                return self._record(active)
            self._ensure_free(conn)
            cursor = conn.execute("INSERT INTO browser_jobs(kind,state,created_at) VALUES('login','queued',?)", (utc_now_iso(),))
            return self._record(conn.execute("SELECT * FROM browser_jobs WHERE id=?", (cursor.lastrowid,)).fetchone())

    def create_collection(self, task_id, request_id, query, max_pages, retry_of=None, *, investigation_id=None):
        if type(max_pages) is not int or not 1 <= max_pages <= min(3, self.config.max_pages_per_platform):
            raise BrowserJobError("invalid_scope", "采集页数超出配置范围。", 400)
        if not isinstance(query, str) or len(query.strip()) > 120:
            raise BrowserJobError("invalid_scope", "搜索词不能超过 120 字。", 400)
        query = query.strip()
        with self.transaction() as conn:
            request = conn.execute("SELECT * FROM action_requests WHERE id=? AND task_id=?", (request_id, task_id)).fetchone()
            if request is None:
                raise BrowserJobError("not_found", "请求不属于当前任务。", 404)
            if request["state"] != "approved":
                raise BrowserJobError("approval_required", "请先确认采集请求。")
            from shopping_agent.project_investigations import linked, validate_execution
            investigation = linked(conn, request_id)
            if investigation and (investigation_id != investigation['id'] or retry_of is not None or query or max_pages != 1):
                raise BrowserJobError('project_investigation_scope', '项目调查仅可从项目内按已确认范围执行一次。')
            actions = json.loads(request["actions_json"])
            listing_ids = json.loads(request["listing_ids_json"])
            if not actions or not set(actions) <= {"search", "detail"}:
                raise BrowserJobError("unsupported_action", "网页目前只支持搜索和详情采集，图片下载与 OCR 尚未接入。", 400)
            if "search" in actions and not query:
                raise BrowserJobError("invalid_scope", "请填写具体搜索词。", 400)
            if "detail" in actions and (not listing_ids or len(listing_ids) > self.config.safety.xianyu_max_detail_pages_per_run):
                raise BrowserJobError("invalid_scope", "详情商品范围为空或超出安全上限。", 400)
            ConversationStore._validate_listing_scope(conn, task_id, listing_ids)
            previous = conn.execute("SELECT * FROM browser_jobs WHERE request_id=? ORDER BY id DESC LIMIT 1", (request_id,)).fetchone()
            if previous:
                if previous["query"] != query or previous["max_pages"] != max_pages:
                    raise BrowserJobError("execution_conflict", "已保存的执行范围不可更改，请创建新的采集请求。")
                if retry_of is None or previous["retry_of"] == retry_of:
                    return self._record(previous)
                if previous["id"] != retry_of or previous["state"] not in {"failed", "cancelled", "interrupted"}:
                    raise BrowserJobError("execution_conflict", "此执行不能重试。")
            elif retry_of is not None:
                raise BrowserJobError("execution_conflict", "重试来源不存在。")
            if investigation:
                validate_execution(conn, self.config, investigation, investigation_id)
            self._ensure_free(conn)
            if conn.execute("SELECT 1 FROM operations WHERE task_id=? AND state IN ('queued','running','waiting_confirmation')", (task_id,)).fetchone():
                raise BrowserJobError("operation_conflict", "当前任务有未完成的分析或确认，请先处理。")
            cursor = conn.execute("""INSERT INTO browser_jobs(kind,task_id,request_id,retry_of,query,max_pages,
                actions_json,listing_ids_json,state,created_at) VALUES('collection',?,?,?,?,?,?,?,'queued',?)""",
                (task_id, request_id, retry_of, query, max_pages, request["actions_json"], request["listing_ids_json"], utc_now_iso()))
            return self._record(conn.execute("SELECT * FROM browser_jobs WHERE id=?", (cursor.lastrowid,)).fetchone())

    def update(self, job_id, *, stage=None, result=None, verify_requested=None, stop_requested=None):
        values = {}
        if stage is not None:
            values["stage"] = stage
        if result is not None:
            values["result_json"] = json.dumps(result, ensure_ascii=False)
        if verify_requested is not None:
            values["verify_requested"] = int(verify_requested)
        if stop_requested is not None:
            values["stop_requested"] = int(stop_requested)
        if not values:
            return
        with self.transaction() as conn:
            conn.execute(f"UPDATE browser_jobs SET {','.join(f'{key}=?' for key in values)} WHERE id=? AND state IN ('queued','running')", (*values.values(), job_id))

    def claim(self, job_id):
        with self.transaction() as conn:
            row = conn.execute('SELECT * FROM browser_jobs WHERE id=?', (job_id,)).fetchone()
            if row is None or row['state'] != 'queued':
                return False
            from shopping_agent.project_investigations import linked, validate_execution, finish_investigation
            owner = linked(conn, row['request_id'])
            if owner:
                try:
                    validate_execution(conn, self.config, owner, owner['id'])
                except BrowserJobError as exc:
                    conn.execute("UPDATE browser_jobs SET state='failed',stage='failed',error_code=?,error_detail=?,completed_at=? WHERE id=?",
                                 (exc.code,str(exc),utc_now_iso(),job_id))
                    self._append_event(conn,job_id,'job_finished',dict(state='failed',error_code=exc.code))
                    finish_investigation(conn, row)
                    return False
            return conn.execute("UPDATE browser_jobs SET state='running',stage='starting_browser' WHERE id=? AND state='queued'", (job_id,)).rowcount == 1

    def finish(self, job_id, state, result=None, error_code=None, error_detail=None, *, continue_research=False):
        if state not in {"completed", "failed", "cancelled", "interrupted"}:
            raise ValueError("Invalid terminal state")
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM browser_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["state"] not in ACTIVE:
                return
            if state == "completed" and row["stop_requested"]:
                state = "cancelled"
            now = utc_now_iso()
            final_result = result if result is not None else json.loads(row["result_json"])
            conn.execute("UPDATE browser_jobs SET state=?,stage=?,result_json=?,error_code=?,error_detail=?,completed_at=? WHERE id=?",
                         (state,state,json.dumps(final_result),error_code,error_detail,now,job_id))
            self._append_event(conn, job_id, "job_finished", {"state": state, "error_code": error_code}, now)
            from shopping_agent.project_investigations import finish_investigation
            if finish_investigation(conn, row):
                return  # P1 never starts legacy analysis or a project AgentRun.
            if row["task_id"] and not (continue_research and state == "completed" and row["kind"] == "collection"):
                count = final_result.get("listing_count", 0)
                text = f"采集{'完成' if state == 'completed' else '已停止或未完成'}：本次已保存 {count} 条商品记录。可查看候选与证据，或继续询问。"
                if state != "completed":
                    reason = {
                        "search_cooldown": "搜索仍在冷却，本次未进入平台搜索。",
                        "login_required": "登录已失效，需要重新登录。",
                        "verification_closed": "验证窗口已关闭，采集未继续。",
                        "access_blocked": "平台出现访问限制或验证提示。",
                        "service_restarted": "服务重启，采集已中断。",
                        "detail_unavailable": "未读取到目标商品详情。",
                        "collection_stopped": "搜索提前停止，请检查已保存证据的覆盖范围。",
                    }.get(error_code)
                    if error_code == "search_cooldown":
                        remaining = re.search(r"等待 ([0-9]{1,8}) 秒", error_detail or "")
                        if remaining:
                            reason += f"当时还需等待 {remaining.group(1)} 秒。"
                    if reason:
                        text += f" 原因：{reason}已有商品记录仍保留。"
                conn.execute("INSERT INTO conversation_messages(task_id,role,content,created_at) VALUES(?,'system',?,?)", (row["task_id"],text,now))
                conn.execute("UPDATE research_tasks SET updated_at=? WHERE id=?", (now,row["task_id"]))
            if continue_research and state == "completed" and row["kind"] == "collection":
                return self._create_collection_analysis(conn, job_id)

    def _create_collection_analysis(self, conn, job_id):
        job = conn.execute("SELECT * FROM browser_jobs WHERE id=?", (job_id,)).fetchone()
        if job is None:
            raise BrowserJobError("not_found", "Collection job not found.", 404)
        from shopping_agent.project_investigations import linked
        if linked(conn, job['request_id']):
            raise BrowserJobError('project_investigation_analysis_disabled', '调查证据已保存到项目；P1 不自动复评或启动旧版分析。')
        if job["kind"] != "collection" or job["state"] != "completed":
            raise BrowserJobError("analysis_unavailable", "只有已完成的采集可以继续分析。")
        if job["analysis_operation_id"] is not None:
            return job["analysis_operation_id"]
        if conn.execute("SELECT 1 FROM operations WHERE task_id=? AND state IN ('queued','running','waiting_confirmation')", (job["task_id"],)).fetchone():
            raise BrowserJobError("operation_conflict", "当前任务有未完成的分析或确认，请先处理。")
        result = json.loads(job["result_json"])
        count = result.get("listing_count", 0)
        message = f"采集完成：本次已保存 {count} 条商品记录。正在结合你的需求比较候选、说明理由与风险，并判断是否还需要核实详情。"
        created = self.conversations._create_message_operation(conn, job["task_id"], message, role="system")
        conn.execute("UPDATE browser_jobs SET analysis_operation_id=? WHERE id=?", (created.operation.id, job_id))
        return created.operation.id

    def analyze(self, job_id):
        with self.transaction() as conn:
            return self._create_collection_analysis(conn, job_id)

    def recover_interrupted(self):
        with self.transaction() as conn:
            for row in conn.execute("SELECT id FROM browser_jobs WHERE state IN ('queued','running')").fetchall():
                self._append_event(conn, row["id"], "job_finished", {"state": "interrupted", "error_code": "service_restarted"})
            conn.execute("UPDATE browser_jobs SET state='interrupted',stage='interrupted',error_code='service_restarted',error_detail='服务重启，采集未自动重试。',completed_at=? WHERE state IN ('queued','running')", (utc_now_iso(),))
            conn.execute("UPDATE browser_auth SET state='unknown' WHERE id=1")
            from shopping_agent.project_investigations import linked, finish_investigation
            for row in conn.execute("SELECT * FROM browser_jobs WHERE state='interrupted'").fetchall():
                owner = linked(conn, row['request_id'])
                if owner and owner['outcome_json'] == '{}':
                    finish_investigation(conn, row)


class BrowserJobCoordinator:
    def __init__(self, store: BrowserJobStore, backend, analysis_coordinator=None):
        self.store, self.backend = store, backend
        self.analysis_coordinator = analysis_coordinator
        self._lock = threading.RLock()
        self._workers = {}
        self._closed = False

    def start(self, job_id, *, config=None):
        with self._lock:
            if self._closed:
                raise BrowserJobError("shutting_down", "服务正在关闭。")
            if job_id in self._workers or self.store.get(job_id)["state"] != "queued":
                return
            holder = {"loop": None, "task": None, "stop": False, "config": config or self.store.config}
            thread = threading.Thread(target=self._run, args=(job_id,holder), daemon=True)
            holder["thread"] = thread
            self._workers[job_id] = holder
            thread.start()

    def _run(self, job_id, holder):
        async def run():
            with self._lock:
                holder["loop"] = asyncio.get_running_loop()
                holder["task"] = asyncio.current_task()
                if not self.store.claim(job_id):
                    return
                stopped = holder["stop"]
            try:
                if stopped:
                    raise asyncio.CancelledError()
                result = await asyncio.wait_for(self.backend.run(self.store.get(job_id), self.store, holder["config"]), timeout=600)
                if holder["stop"]:
                    self.store.finish(job_id,"cancelled",result)
                else:
                    operation_id = self.store.finish(job_id,"completed",result,
                        continue_research=self.analysis_coordinator is not None)
                    if operation_id is not None:
                        self.analysis_coordinator.start(operation_id)
            except asyncio.CancelledError:
                self.store.finish(job_id,"cancelled")
            except BrowserJobError as exc:
                self.store.finish(job_id,"failed",error_code=exc.code,error_detail=str(exc))
            except asyncio.TimeoutError:
                self.store.finish(job_id,"failed",error_code="browser_timeout",error_detail="操作超时，请检查浏览器或重试。")
            except Exception:
                self.store.finish(job_id,"failed",error_code="browser_failed",error_detail="浏览器操作失败，请检查本地 Chromium 安装和登录状态。")
        try:
            asyncio.run(run())
        finally:
            with self._lock:
                self._workers.pop(job_id,None)

    def cancel(self, job_id):
        with self._lock:
            job = self.store.get(job_id)
            if job["state"] not in ACTIVE:
                return job
            self.store.update(job_id,stage="stopping",stop_requested=True)
            holder = self._workers.get(job_id)
            if holder:
                if not holder["stop"]:
                    holder["stop"] = True
                    if holder["loop"] and holder["task"]:
                        holder["loop"].call_soon_threadsafe(holder["task"].cancel)
            else:
                self.store.finish(job_id,"cancelled")
        return self.store.get(job_id)

    def verify_login(self, job_id):
        job = self.store.get(job_id)
        if job["kind"] != "login" or job["state"] != "running":
            raise BrowserJobError("login_not_running", "请先打开登录窗口。")
        self.store.update(job_id,verify_requested=True)
        return self.store.get(job_id)

    def resume_verification(self, job_id):
        with self.store.transaction() as conn:
            row = conn.execute("SELECT * FROM browser_jobs WHERE id=?", (job_id,)).fetchone()
            job = self.store._record(row)
            if (job["kind"] != "collection" or "detail" not in job["actions"]
                    or job["state"] != "running" or job["stage"] != "waiting_verification"
                    or job["stop_requested"]):
                raise BrowserJobError("verification_not_waiting", "当前采集没有等待手动验证。")
            conn.execute("UPDATE browser_jobs SET verify_requested=1 WHERE id=?", (job_id,))
            if not job["verify_requested"]:
                previous = conn.execute("SELECT metadata_json FROM browser_job_events WHERE job_id=? AND event_type='verification_required' ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
                self.store._append_event(conn, job_id, "manual_continue", json.loads(previous["metadata_json"]) if previous else {})
        return self.store.get(job_id)

    def shutdown(self):
        with self._lock:
            self._closed = True
            workers = list(self._workers.items())
        for job_id, _ in workers:
            self.cancel(job_id)
        for _, holder in workers:
            holder["thread"].join(timeout=20)
