from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import threading
import sys
from pathlib import Path

import uvicorn

from shopping_agent.db import (
    add_detail_snapshot,
    add_listing_snapshot,
    attach_run_to_task,
    connect,
    create_query,
    create_research_task,
    create_search_run,
    initialize,
    upsert_listing,
)
from shopping_agent.user_settings import UserSettings, save_user_settings
from shopping_agent.web.app import create_app
from shopping_agent.codex_runtime import CodexRuntime, AnswerResult, ActionRequestResult, InvalidCodexResult, CodexCancelledError
from shopping_agent.codex_runtime import PreferenceUpdateResult
from shopping_agent.assessment import ResearchResult, input_refs
from shopping_agent.history_review import HistoryReviewResult, ComparisonResult, NominationResult
from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.browser_jobs import BrowserJobError


class DemoBrowser:
    """Offline browser boundary: persist realistic data without platform traffic."""
    async def run(self, job, store, config):
        if job["kind"] == "login":
            store.update(job["id"], stage="waiting_login")
            while not store.get(job["id"])["verify_requested"]:
                await asyncio.sleep(.05)
            store.set_auth("verified")
            return {"authenticated": True, "run_ids": [], "listing_count": 0}
        if "detail" in job["actions"]:
            store.update(job["id"], stage="waiting_verification", verify_requested=False)
            while not store.get(job["id"])["verify_requested"]:
                await asyncio.sleep(.05)
            store.update(job["id"], stage="verifying_detail", verify_requested=False)
            await asyncio.sleep(.25)
            return {"run_ids": [], "listing_count": len(job["listing_ids"])}
        store.update(job["id"], stage="searching")
        if "block" in job["query"] and job["retry_of"] is None:
            await asyncio.sleep(60)
        if "cooldown" in job["query"]:
            raise BrowserJobError("search_cooldown", "搜索冷却中，还需等待 30 秒。")
        await asyncio.sleep(.25)
        with connect(config.database_path) as conn:
            run_id = create_search_run(conn, goal=job["query"], city="上海")
            attach_run_to_task(conn, task_id=job["task_id"], run_id=run_id)
            listing_id = upsert_listing(conn, platform="xianyu", url=f"https://www.goofish.com/item?id={job['id']}")
            add_listing_snapshot(conn, listing_id=listing_id, run_id=run_id, title=f"采集样例 {job['query']}", price_text="3200", location="上海")
        return {"run_ids": [run_id], "listing_count": 1}


class DemoRuntime(CodexRuntime):
    """Deterministic E2E adapter. Never starts any external process."""
    def __init__(self, database_path=None):
        super().__init__(Path.cwd())
        self.database_path = database_path
        self.stops = {}

    def run(self, request, *, run_id, stage_callback):
        stop = threading.Event()
        self.stops[run_id] = stop
        try:
            stage_callback("analyzing_evidence")
            # Review batches carry conversation history; inspect this operation's
            # trigger, not a possibly later assistant/history message.
            message = next((m.content for m in request.messages if m.id == request.trigger_message_id),
                           request.messages[-1].content if request.messages else "")
            if request.phase == "chat" and "check-suggestion-fixture" in message:
                return AnswerResult(type="answer", content="请在商品证据的待核实清单中核对并确认保存建议。", candidate_ids=[min(request.allowed_listing_ids)],
                    check_suggestions=[dict(listing_id=min(request.allowed_listing_ids), question="能否核对屏幕维修记录？", reason="保存的商品证据未提供维修记录。")])
            if request.phase == "chat" and "partial-change-fixture" in message:
                with connect(self.database_path) as conn:
                    conn.execute("UPDATE listing_snapshots SET price_text=CAST(CAST(price_text AS INTEGER)+1 AS TEXT) WHERE listing_id=? AND run_id IN (SELECT run_id FROM task_runs WHERE task_id=?)", (min(request.allowed_listing_ids), request.task.id))
                return AnswerResult(type="answer", content="离线夹具已更新一件商品证据", candidate_ids=[])
            if request.phase == "nomination":
                return NominationResult(type="nomination", candidates=[dict(listing_id=a["listing_id"], assessment_id=a["assessment_id"],
                    reason="按保存判断重新提名，继续核实实物", uncertainties=["内存与实物待核实"]) for a in request.review_context["assessments"] if a["conclusion"] != "not_met"][:2])
            if request.phase == "review_batch":
                if "history-fail-fixture" in message and min(request.allowed_listing_ids) > 20:
                    raise InvalidCodexResult("Offline second-batch failure fixture")
                refs = input_refs(request)
                assessments = []
                for item in request.candidates:
                    ref = next(ref for ref, data in refs.items() if data["listing_id"] == item.listing_id)
                    judgments = [dict(criterion_id=c.criterion_id, status="UNKNOWN" if c.criterion_id == "memory" else "MET",
                        source_type="missing" if c.criterion_id == "memory" else "platform_display",
                        reason="内存尚需核实" if c.criterion_id == "memory" else "搜索卡片标注该型号，未经独立验机",
                        evidence_refs=[] if c.criterion_id == "memory" else [ref]) for c in request.current_criteria]
                    for judgment in judgments:
                        if judgment["criterion_id"] == "originality":
                            statement_refs = [key for key, data in refs.items() if key.startswith("statement:") and data["listing_id"] == item.listing_id]
                            judgment.update(status="CONFLICT" if len(statement_refs) >= 2 else "MET" if statement_refs else "UNKNOWN",
                                source_type="seller_claim" if statement_refs else "missing",
                                reason="用户转述卖家声明，未经独立核实；矛盾原文保留" if statement_refs else "没有原装证据",
                                evidence_refs=statement_refs)
                    assessments.append(dict(listing_id=item.listing_id, judgments=judgments, conclusion="conditional", summary="卡片支持型号，实物仍需核实"))
                return AnswerResult(type="answer", content="离线批次已评估", candidate_ids=[a["listing_id"] for a in assessments[:2]],
                    research=ResearchResult.model_validate(dict(criteria=[c.model_dump() for c in request.current_criteria], assessments=assessments)))
            if request.phase == "comparison":
                candidates = request.review_context["assessments"][:2]
                previous = request.review_context["previous_comparison"]
                before = {c["listing_id"] for c in previous["ranked_candidates"]} if previous else set()
                after = {c["listing_id"] for c in candidates}
                inputs = {a["listing_id"]: a for a in request.review_context["assessments"]}
                return ComparisonResult.model_validate(dict(type="comparison", content="已按保存的逐项评估完成本轮比较，仍需核实实物。",
                    ranked_candidates=[dict(listing_id=a["listing_id"], assessment_id=a["assessment_id"], reason="型号有卡片支持，继续核实内存与实物", uncertainties=["内存与实物待核实"]) for a in candidates],
                    changes=[dict(listing_id=i, assessment_id=inputs[i]["assessment_id"], kind=kind, reason="依据本轮保存的评估调整")
                             for ids, kind in ((after-before,"entered"),(before-after,"exited")) for i in ids]))
            if "legacy-goal-fixture" in message:
                return HistoryReviewResult(type="history_review", summary="从旧任务目标初始化标准并重评", criteria=[dict(
                    criterion_id="model", description="ThinkPad X1 Carbon 型号", priority="hard",
                    source_message_ids=[], source_refs=["task_goal"])])
            if "seller-evidence-fixture" in message:
                return HistoryReviewResult(type="history_review", summary="依据明确绑定的用户转述重评", criteria=list(request.current_criteria) or [dict(
                    criterion_id="originality", description="尽量原装", priority="soft", source_message_ids=[], source_refs=["task_goal"])])
            if any(flag in message for flag in ("history-review-fixture", "history-fail-fixture", "history-change-fixture")):
                if "history-change-fixture" in message and request.allow_preference_update:
                    return PreferenceUpdateResult(type="preference_update", source_message_id=request.trigger_message_id,
                        base_revision_id=request.task.preference_revision_id, effective_goal=request.task.effective_goal+"，内存至少16GB",
                        added_preferences=["内存至少16GB"], removed_preferences=[])
                criteria = [c.model_dump() for c in request.current_criteria] or [dict(criterion_id="model", description="ThinkPad X1 Carbon 型号",
                    priority="hard", source_message_ids=[next(m.id for m in request.messages if m.role == "user")])]
                if "16GB" in request.task.effective_goal and not request.current_criteria:
                    criteria.append(dict(criterion_id="memory", description="内存至少16GB", priority="hard", source_message_ids=[request.trigger_message_id]))
                return HistoryReviewResult(type="history_review", summary="本地重评全部已保存候选", criteria=criteria)
            if "structured-fixture" in message and request.allowed_listing_ids:
                listing_id = sorted(request.allowed_listing_ids)[0]
                criteria = [c.model_dump() for c in request.current_criteria] or [dict(
                    criterion_id="model", description="ThinkPad X1 Carbon 型号",
                    priority="hard", source_message_ids=[request.trigger_message_id])]
                ref = next(ref for ref, data in input_refs(request).items() if data["listing_id"] == listing_id)
                return AnswerResult(type="answer", content="按已保存卡片核对型号，仍需核实机器实物。", candidate_ids=[listing_id],
                    research=ResearchResult.model_validate(dict(criteria=criteria, assessments=[dict(
                        listing_id=listing_id, conclusion="conditional", summary="卡片型号符合，实物未核实",
                        judgments=[dict(criterion_id=c["criterion_id"], status="MET",
                            reason="搜索卡片标注该型号，不等于独立验机", source_type="platform_display",
                            evidence_refs=[ref]) for c in criteria])])) )
            if "preference-fixture" in message:
                if request.allow_preference_update:
                    return PreferenceUpdateResult(
                        type="preference_update", source_message_id=request.trigger_message_id,
                        base_revision_id=request.task.preference_revision_id,
                        effective_goal=request.task.effective_goal.replace("预算3800", "预算4300").replace("88%", "90%"),
                        added_preferences=["预算4300", "电池至少90%"],
                        removed_preferences=["预算3800", "电池至少88%"],
                    )
                return AnswerResult(type="answer", content="购买要求已保存，正在按新要求比较已有证据。", candidate_ids=[])
            if "block" in message:
                stop.wait(30)
                raise CodexCancelledError("Stopped")
            if "delay" in message:
                if stop.wait(2):
                    raise CodexCancelledError("Stopped")
            if "invalid" in message:
                raise InvalidCodexResult("Invalid fixture")
            if "verify-detail" in message and request.allowed_listing_ids:
                return ActionRequestResult(type="action_request", summary="核实商品详情", risk="可能需要手动验证。",
                    listing_ids=sorted(request.allowed_listing_ids)[:1], actions=["detail"])
            if "compare-cards" in message and request.allowed_listing_ids:
                ids = sorted(request.allowed_listing_ids)[:2]
                sections = [f"{index+1}. {listing_id}：预算备选。容量与所在地描述完整。待核实维修史及交易地点。" for index, listing_id in enumerate(ids)]
                return AnswerResult(type="answer", content="已有两条可比较候选，卖家陈述尚未独立核实。\n\n" + "\n\n".join(sections), candidate_ids=ids)
            if "action" in message:
                return ActionRequestResult(type="action_request", summary="补充搜索商品证据", risk="后续采集将访问商品页面；请确认范围。", listing_ids=[], actions=["search"], search_query="iPhone 15 Pro", max_pages=1)
            return AnswerResult(type="answer", content="已根据保存的证据整理回答。建议核实成色、保修和交易方式。", candidate_ids=sorted(request.allowed_listing_ids)[:2])
        finally:
            self.stops.pop(run_id, None)

    def cancel(self, run_id):
        stop = self.stops.get(run_id)
        if stop:
            stop.set()


def seed_database(database_path: Path, artifact_dir: Path) -> None:
    initialize(database_path)
    with connect(database_path) as conn:
        task_id = create_research_task(
            conn,
            title="ThinkPad X1 Carbon 调研",
            goal="查找上海的 ThinkPad X1 Carbon",
            city="上海",
        )
        run_id = create_search_run(conn, goal="ThinkPad X1 Carbon", city="上海")
        create_query(
            conn,
            run_id=run_id,
            platform="xianyu",
            query_text="ThinkPad X1 Carbon",
        )
        attach_run_to_task(conn, task_id=task_id, run_id=run_id)

        for index in range(1, 56):
            listing_id = upsert_listing(
                conn,
                platform="xianyu",
                url=f"https://example.test/thinkpad-{index:02d}",
            )
            add_listing_snapshot(
                conn,
                listing_id=listing_id,
                run_id=run_id,
                title=f"ThinkPad X1 Carbon #{index:02d}",
                description=f"本地候选 {index:02d}，已保存搜索卡片证据。",
                price_text=str(5100 + index),
                location="上海",
                seller_name=f"卖家 {index:02d}",
                search_condition="九成新",
                seller_credit_level="信用良好" if index <= 2 else None,
            )
            if index <= 2:
                detail_text = artifact_dir / f"detail-{index}.txt"
                detail_text.write_text(
                    f"ThinkPad X1 Carbon #{index:02d} 详情证据",
                    encoding="utf-8",
                )
                add_detail_snapshot(
                    conn,
                    listing_id,
                    run_id,
                    f"https://example.test/thinkpad-{index:02d}",
                    f"ThinkPad X1 Carbon #{index:02d}",
                    artifact_dir / f"detail-{index}.png",
                    artifact_dir / f"detail-{index}.html",
                    detail_text,
                    artifact_dir / f"detail-{index}.links.txt",
                    artifact_dir / f"detail-{index}.images.txt",
                    0,
                    0,
                    False,
                    attributes_json=json.dumps(
                        {"内存": "16GB", "硬盘": "512GB"},
                        ensure_ascii=False,
                    ),
                    attributes_source="xianyu_api_item_labels",
                )

        second_task_id = create_research_task(
            conn,
            title="Pocket 3 调研",
            goal="查找上海的 Pocket 3",
            city="上海",
        )
        second_run_id = create_search_run(conn, goal="Pocket 3", city="上海")
        attach_run_to_task(conn, task_id=second_task_id, run_id=second_run_id)
        second_listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://example.test/pocket-3",
        )
        add_listing_snapshot(
            conn,
            listing_id=second_listing_id,
            run_id=second_run_id,
            title="Pocket 3 套装",
            description="本地候选",
            price_text="2800",
            location="上海",
            seller_name="卖家 P3",
        )
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8876)
    args = parser.parse_args()

    # Import asyncio above before the Windows subprocess boundary is wrapped.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from devtools.p4_offline_test_guard import pytest_configure
    pytest_configure(None)

    with tempfile.TemporaryDirectory(prefix="shopping-agent-web-e2e-") as raw_dir:
        temp_dir = Path(raw_dir)
        database_path = temp_dir / "workbench.sqlite"
        config_path = temp_dir / "config.toml"
        settings_path = temp_dir / "settings.json"
        config_path.write_text(
            "\n".join(
                [
                    'default_city = "上海"',
                    f'database_path = "{database_path.as_posix()}"',
                    f'browser_profile_dir = "{(temp_dir / "browser-profile").as_posix()}"',
                    f'reports_dir = "{(temp_dir / "reports").as_posix()}"',
                    f'screenshots_dir = "{(temp_dir / "screenshots").as_posix()}"',
                    f'media_dir = "{(temp_dir / "media").as_posix()}"',
                    '[monitor_engine]',
                    'enabled = true',  # Only the isolated offline DemoMonitor below.
                ]
            ),
            encoding="utf-8",
        )
        save_user_settings(
            settings_path,
            UserSettings(
                setup_completed=True,
                default_city="上海",
                platforms=["xianyu"],
                allow_ocr=True,
                preferred_view="research",
            ),
        )
        seed_database(database_path, temp_dir)
        service = ConversationService(AppConfig(database_path=database_path))
        interrupted = service.create_task("服务重启恢复示例")
        service.store.transition_operation(interrupted.operation.id, {"queued"}, "running")
        for label in ("桌面历史重评夹具", "窄屏历史重评夹具"):
            task = service.create_task(f"ThinkPad X1 Carbon，{label}")
            service.store.transition_operation(task.operation.id, {"queued"}, "completed")
            with connect(database_path) as conn:
                attach_run_to_task(conn, task_id=task.task.id, run_id=1)
        with connect(database_path) as conn:
            for label in ("桌面旧任务分页夹具", "窄屏旧任务分页夹具"):
                legacy_id = create_research_task(conn, title=label, goal="ThinkPad X1 Carbon 原始CLI研究目标", city="上海")
                attach_run_to_task(conn, task_id=legacy_id, run_id=1)
        from shopping_agent.tasks import update_task_preferences
        for label in ("桌面长任务摘要夹具", "窄屏长任务摘要夹具"):
            with connect(database_path) as conn:
                history_id = create_research_task(conn, title=label, goal="长任务原始目标", city="上海")
            for index in range(23):
                update_task_preferences(service.config, history_id, f"长任务需求修订{index}", f"长任务当前目标{index}",
                                        added_preferences=["早期保留偏好"] if index == 0 else [])
                with connect(database_path) as conn:
                    run_id = create_search_run(conn, goal=f"长任务采集轮次{index}", city="上海")
                    attach_run_to_task(conn, task_id=history_id, run_id=run_id)
                    conn.execute("INSERT INTO saved_reports(task_id,run_id,title,format,path,created_at) VALUES (?,?,?,'md','fixture','fixture')",
                                 (history_id, run_id, f"长任务报告{index}"))
        for label in ("桌面拆批复用夹具", "窄屏拆批复用夹具"):
            created = service.create_task(label)
            service.store.transition_operation(created.operation.id, {"queued"}, "completed")
            with connect(database_path) as conn:
                run_id = create_search_run(conn, goal=label, city="上海")
                attach_run_to_task(conn, task_id=created.task.id, run_id=run_id)
                for index in range(1, 56):
                    listing_id = upsert_listing(conn, platform="xianyu", url=f"https://example.test/partial-{created.task.id}-{index}")
                    add_listing_snapshot(conn, listing_id=listing_id, run_id=run_id,
                        title=f"独立 ThinkPad X1 Carbon #{index:02d}", price_text=str(5100+index),
                        location="上海", description="拆批复用独立候选夹具")
        for label in ("桌面卖家答复夹具", "窄屏卖家答复夹具", "桌面核实建议夹具", "窄屏核实建议夹具"):
            created = service.create_task(f"ThinkPad X1 Carbon，尽量原装，{label}")
            service.store.transition_operation(created.operation.id, {"queued"}, "completed")
            with connect(database_path) as conn:
                run_id = create_search_run(conn, goal=label, city="上海")
                attach_run_to_task(conn, task_id=created.task.id, run_id=run_id)
                for index in range(4):
                    listing_id = upsert_listing(conn, platform="xianyu", url=f"https://example.test/statements-{created.task.id}-{index}")
                    add_listing_snapshot(conn, listing_id=listing_id, run_id=run_id,
                        title=f"ThinkPad 答复候选 {index}", price_text="5000", location="上海", description="维修史未知")
        if os.environ.get('SECONDPICK_E2E_STATIC'):
            import shopping_agent.web.app as web_app
            web_app.STATIC_DIR = Path(os.environ['SECONDPICK_E2E_STATIC']).resolve()
        app = create_app(config_path, settings_path)
        # Isolated UI tests must not even invoke a real CLI login diagnostic.
        # Research itself already uses DemoRuntime; setup reads share this guard.
        from shopping_agent import setup_status
        setup_status.check_codex_availability = lambda: setup_status.CodexStatus(
            cli_available=False, auth_available=False, detail='Isolated E2E: CLI checks disabled')
        app.state.codex_runtime = DemoRuntime(database_path)
        app.state.browser_backend = DemoBrowser()
        from monitor_fixture import DemoMonitor
        app.state.monitor_engine = DemoMonitor(database_path, temp_dir)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=args.port,
            log_level="warning",
        )


if __name__ == "__main__":
    main()
