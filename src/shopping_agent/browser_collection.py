from __future__ import annotations

import asyncio
import re
import random
from urllib.parse import urlsplit, parse_qs

from playwright.async_api import async_playwright

from shopping_agent.browser_jobs import BrowserJobError
from shopping_agent.browser.session import _is_access_blocked, _is_login_required, _visible_frame_urls
from shopping_agent.browser.auth_state import restore_session_cookies, save_session_cookies
from shopping_agent.browser.monitor_auth import save_monitor_login
from shopping_agent.config import ensure_runtime_dirs
from shopping_agent.db import connect, attach_run_to_task
from shopping_agent.detail import browser_profile_lock, capture_detail_url
from shopping_agent.safety import SafetyError, enforce_browser_collection_safety
from shopping_agent.spike import capture_search_spike, SearchSpikeSafetyError


def safe_listing_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in {"www.goofish.com", "goofish.com"}
                and parsed.port in {None,443} and not parsed.username and not parsed.password
                and parsed.path in {"/item", "/item/"} and bool(parse_qs(parsed.query).get("id")))
    except ValueError:
        return False


def verified_login(visible_text: str, frame_urls: list[str]) -> bool:
    if _is_access_blocked(visible_text, frame_urls) or _is_login_required("xianyu",frame_urls):
        return False
    if re.search(r"(?:^|\s)(?:登录|登录/注册|请登录)(?:\s|$)", visible_text):
        return False
    return "退出登录" in visible_text or ("我买到的" in visible_text and "我卖出的" in visible_text)


class BrowserCollectionBackend:
    async def run(self,job,store,config):
        if "xianyu" not in config.platforms:
            raise BrowserJobError("platform_disabled","请先在设置中启用闲鱼。",400)
        ensure_runtime_dirs(config)
        if job["kind"] == "login":
            try:
                return await self._login(job,store,config)
            except SafetyError as exc:
                raise BrowserJobError("browser_busy","浏览器资料正在被其他操作使用，请先关闭该操作。") from exc
        if store.status()["auth_status"] != "verified":
            raise BrowserJobError("login_required","请先到设置中打开并验证闲鱼登录。")
        # Safety settings remain authoritative, even after explicit Web approval.
        try:
            enforce_browser_collection_safety(config,"xianyu",headless=False,acknowledged_risk=True,
                detail_limit=len(job["listing_ids"]) if "detail" in job["actions"] else None)
            result = {"run_ids": [], "listing_count": 0}
            if "search" in job["actions"]:
                store.update(job["id"],stage="searching")
                store.record_attempt(job["id"], {"operation": "search", "requested_pages": job["max_pages"]})
                task_city = self._task_city(config,job["task_id"])
                job_config = config.model_copy(update={"default_city": task_city,
                    "screenshots_dir": config.screenshots_dir / f"web-job-{job['id']}"})
                try:
                    with browser_profile_lock(config.browser_profile_dir,timeout_seconds=0,stale_after_seconds=float("inf")):
                        captured = await capture_search_spike(config=job_config,platform="xianyu",query=job["query"],
                            headless=False,max_pages=job["max_pages"])
                except SearchSpikeSafetyError as exc:
                    store.record_event(job["id"], "search_completed", {"captured_pages": getattr(exc.result.snapshot, "api_page_count", 0), "stop_reason": exc.result.snapshot.stop_reason})
                    if exc.result.snapshot.stop_reason == "access_blocked":
                        store.record_event(job["id"], "verification_required", {"operation": "search", "captured_pages": getattr(exc.result.snapshot, "api_page_count", 0)})
                    self._attach_search(exc.result,job,store,config,result)
                    if exc.result.snapshot.stop_reason == "login_required":
                        store.set_auth("invalid")
                        raise BrowserJobError("login_required","登录已失效，请重新登录。已保存的部分证据仍保留。") from exc
                    raise BrowserJobError("collection_stopped","搜索提前停止，已保存部分证据；请检查覆盖范围后再决定是否重试。") from exc
                self._attach_search(captured,job,store,config,result)
                store.record_event(job["id"], "search_completed", {"captured_pages": getattr(captured.snapshot, "api_page_count", 0), "stop_reason": captured.snapshot.stop_reason})
            if "detail" in job["actions"]:
                for index,listing_id in enumerate(job["listing_ids"]):
                    # Resolve the URL from current task ownership, never from an HTTP body.
                    with connect(config.database_path) as conn:
                        row = conn.execute("""SELECT l.url,l.platform,s.run_id FROM listings l
                            JOIN listing_snapshots s ON s.listing_id=l.id JOIN task_runs t ON t.run_id=s.run_id
                            WHERE t.task_id=? AND l.id=? ORDER BY s.id DESC LIMIT 1""",(job["task_id"],listing_id)).fetchone()
                        from shopping_agent.project_investigations import linked
                        project_investigation = linked(conn, job['request_id']) is not None
                    if row is None or row["platform"] != "xianyu" or not safe_listing_url(row["url"]):
                        raise BrowserJobError("invalid_scope","商品不属于当前任务或不是有效闲鱼商品链接。",400)
                    store.update(job["id"],stage="capturing_detail")
                    delay_ms = 0
                    if index or "search" in job["actions"] or project_investigation:
                        lower, upper = sorted((config.safety.xianyu_min_delay_ms, config.safety.xianyu_max_delay_ms))
                        delay_ms = max(0, round(random.uniform(lower, upper)))
                        await asyncio.sleep(delay_ms / 1000)
                    audit = {"operation": "detail", "listing_id": listing_id, "page_index": index+1,
                             "completed_pages": index, "requested_pages": len(job["listing_ids"]), "scheduled_delay_ms": delay_ms}
                    store.record_attempt(job["id"], audit)
                    async def record_check(cleared):
                        store.record_event(job["id"], "verification_check", {**audit, "cleared": cleared})
                    detail_config = config.model_copy(update={"screenshots_dir":config.screenshots_dir / f"web-job-{job['id']}"})
                    captured = await capture_detail_url(detail_config,row["url"],platform="xianyu",run_id=row["run_id"],
                        **(dict(source_type='project_investigation', source_label='项目调查详情（平台信息与卖家自述，非独立核验）') if project_investigation else {}),
                        headless=False,profile_lock_timeout_seconds=0,profile_lock_stale_after_seconds=float("inf"),
                        verification_callback=lambda page: self._wait_for_detail_verification(page, job, store, audit),
                        verification_result_callback=record_check)
                    store.record_event(job["id"], "page_completed", {**audit, "completed_pages": index+1})
                    if captured.run_id not in result["run_ids"]:
                        result["run_ids"].append(captured.run_id)
                    result["listing_count"] += 1
                    store.update(job["id"],result=result)
            return result
        except SafetyError as exc:
            message = str(exc)
            if "cooldown" in message.lower():
                seconds = re.search(r"(\d+) seconds remaining",message)
                remaining = seconds.group(1) if seconds else "若干"
                raise BrowserJobError("search_cooldown",f"搜索冷却中，还需等待 {remaining} 秒。可继续使用已有证据。") from exc
            if "profile" in message.lower():
                raise BrowserJobError("browser_busy","浏览器资料正在被其他操作使用，请先关闭该操作。") from exc
            if "detail content unavailable" in message.lower():
                raise BrowserJobError("detail_unavailable","未读取到目标商品详情，采集已停止；已有搜索信息仍保留。") from exc
            store.set_auth("invalid")
            if "login required" in message.lower():
                raise BrowserJobError("login_required","登录已失效，请在设置中重新登录并验证。") from exc
            raise BrowserJobError("access_blocked","平台出现访问限制或验证提示，采集已停止，请在浏览器中自行检查。") from exc

    @staticmethod
    async def _wait_for_detail_verification(page, job, store, audit=None):
        store.record_event(job["id"], "verification_required", audit or {"operation": "detail"})
        store.update(job["id"], stage="waiting_verification", verify_requested=False)
        while not store.get(job["id"])["verify_requested"]:
            if page.is_closed():
                raise BrowserJobError("verification_closed", "验证窗口已关闭，采集未继续。可重新尝试。")
            await asyncio.sleep(.3)
        if page.is_closed():
            raise BrowserJobError("verification_closed", "验证窗口已关闭，采集未继续。可重新尝试。")
        store.update(job["id"], stage="verifying_detail", verify_requested=False)
        await page.wait_for_timeout(1500)

    @staticmethod
    def _task_city(config,task_id):
        with connect(config.database_path) as conn:
            return conn.execute("SELECT city FROM research_tasks WHERE id=?",(task_id,)).fetchone()["city"]

    @staticmethod
    def _attach_search(captured,job,store,config,result):
        with connect(config.database_path) as conn:
            attach_run_to_task(conn,task_id=job["task_id"],run_id=captured.run_id,role="search")
        result["run_ids"].append(captured.run_id)
        result["listing_count"] += captured.parsed_listings
        store.update(job["id"],result=result)

    async def _login(self,job,store,config):
        if not config.allow_login:
            raise BrowserJobError("login_disabled","配置已禁用登录。",400)
        with browser_profile_lock(config.browser_profile_dir,timeout_seconds=0,stale_after_seconds=float("inf")):
            async with async_playwright() as playwright:
                context = await playwright.chromium.launch_persistent_context(str(config.browser_profile_dir),
                    headless=False,viewport={"width":1440,"height":1000},locale="zh-CN")
                try:
                    await restore_session_cookies(context, config.browser_profile_dir)
                    page = context.pages[0] if context.pages else await context.new_page()
                    store.record_attempt(job["id"], {"operation": "login", "page_kind": "home"})
                    await page.goto("https://www.goofish.com/",wait_until="domcontentloaded")
                    store.set_auth("unknown")
                    store.update(job["id"],stage="waiting_login")
                    while True:
                        if page.is_closed():
                            raise BrowserJobError("login_closed","登录窗口已关闭，尚未验证。")
                        if store.get(job["id"])["verify_requested"]:
                            store.update(job["id"],verify_requested=False,stage="verifying_login")
                            # Open the account page only after the user signals sign-in completion.
                            store.record_attempt(job["id"], {"operation": "login", "page_kind": "account"})
                            await page.goto("https://www.goofish.com/personal",wait_until="domcontentloaded")
                            await page.wait_for_timeout(1500)
                            text = await page.locator("body").inner_text()
                            frames = await _visible_frame_urls(page)
                            store.record_event(job["id"], "login_check", {"cleared": verified_login(text, frames)})
                            if verified_login(text,frames):
                                # Complete the durable handoff before reporting
                                # authentication success to the Web UI.
                                await save_session_cookies(context, config.browser_profile_dir)
                                await save_monitor_login(context, config.browser_profile_dir)
                                store.set_auth("verified")
                                return {"authenticated":True,"run_ids":[],"listing_count":0}
                            store.set_auth("invalid")
                            store.update(job["id"],stage="login_not_verified")
                        await asyncio.sleep(.3)
                finally:
                    await context.close()
