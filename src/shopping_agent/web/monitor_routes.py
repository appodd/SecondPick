from typing import Literal
import threading

from fastapi import FastAPI, HTTPException, Request, Query
from shopping_agent.monitor_diagnostics import diagnostic_events
from shopping_agent.db import connect
from shopping_agent.monitor_environment import check_monitor_environment
from shopping_agent.monitor_logs import read_console
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MonitorInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    keyword: str = Field(min_length=1, max_length=120)
    max_pages: int = Field(default=10, ge=1, le=50,
        description="每轮搜索页数上限；已解析的搜索卡片可进入候选池。")
    max_items: int = Field(default=100, ge=1, le=1000,
        description="每轮新增详情处理上限；搜索页卡片和报价观察数量可能更多，受页数范围限制。")
    interval_seconds: int = Field(default=1800, ge=60, le=86400)
    max_rounds: int = Field(default=24, ge=1, le=1000)
    collect_seller_profiles: bool = Field(default=False,
        description="允许访问卖家主页及其商品/评价列表；每次资料补充最多等待30秒，未开启时不访问主页。")
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation required")
        return value


def register_monitor_routes(app: FastAPI):
    check_lock = threading.Lock()

    @app.get("/api/tasks/{task_id}/monitors/{monitor_id}/logs")
    def console_logs(task_id: int, monitor_id: int, request: Request,
                     round_id: str | None = Query(default=None, pattern="^[0-9a-f]{32}$"),
                     before: int | None = Query(default=None, ge=0), limit: int = Query(default=100, ge=1, le=200)):
        return read_console(request.app.state.monitor_store.config, task_id, monitor_id,
                            round_id=round_id, before=before, limit=limit)

    def require_engine(request):
        store = request.app.state.monitor_store
        if not store.config.monitor_engine.enabled or "xianyu" not in store.config.platforms:
            raise HTTPException(409, "请先配置并启用监控采集引擎。")
        readiness = getattr(request.app.state, "monitor_environment_result", None)
        if readiness is not None and not readiness["ready"]:
            raise HTTPException(409, "采集环境检查未通过，请修复后重新检查。")
        if store.config.monitor_engine.state_file is None and request.app.state.browser_store.status()["auth_status"] != "verified":
            raise HTTPException(409, "请先到设置页登录闲鱼并验证，再启动或恢复监控。本次未开始新一轮采集。")

    @app.get("/api/monitor-engine/check")
    def environment_result(request: Request):
        return {"result": getattr(request.app.state, "monitor_environment_result", None)}

    @app.post("/api/monitor-engine/check")
    def check_environment(request: Request):
        if not check_lock.acquire(blocking=False):
            raise HTTPException(409, "采集环境检查正在进行，请稍候。")
        try:
            result = check_monitor_environment(request.app.state.monitor_store.config)
            request.app.state.monitor_environment_result = result
            return result
        finally:
            check_lock.release()

    @app.get("/api/tasks/{task_id}/monitors/{monitor_id}/events")
    def events(task_id: int, monitor_id: int, request: Request,
               before_id: int | None = Query(default=None, ge=1), limit: int = Query(default=50, ge=1, le=100)):
        return diagnostic_events(request.app.state.monitor_store.config, task_id, monitor_id,
                                 before_id=before_id, limit=limit)

    @app.get("/api/tasks/{task_id}/monitors")
    def monitors(task_id: int, request: Request):
        store = request.app.state.monitor_store
        items = store.list(task_id)
        with connect(store.config.database_path) as conn:
            count = conn.execute("""SELECT COUNT(DISTINCT ls.listing_id) FROM listing_snapshots ls
                JOIN task_runs tr ON tr.run_id=ls.run_id WHERE tr.task_id=?""", (task_id,)).fetchone()[0]
        return {"enabled": store.config.monitor_engine.enabled,
                "platform_enabled": "xianyu" in store.config.platforms,
                "candidate_pool_count": count, "items": items}

    @app.post("/api/tasks/{task_id}/monitors", status_code=202)
    def create_monitor(task_id: int, body: MonitorInput, request: Request):
        store = request.app.state.monitor_store
        require_engine(request)
        return store.create(task_id, **body.model_dump())

    @app.post("/api/tasks/{task_id}/monitors/{monitor_id}/{action}")
    def control_monitor(task_id: int, monitor_id: int, action: Literal["pause", "resume", "stop"], request: Request):
        store = request.app.state.monitor_store
        if action == "resume":
            require_engine(request)
        return store.control(task_id, monitor_id, action)
