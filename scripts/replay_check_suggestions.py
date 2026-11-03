"""Opt-in two-turn saved suggestion journey with simulated user confirmation."""
import argparse
import gc
import json
import subprocess
import tempfile
import time
from dataclasses import asdict
from contextlib import closing
from pathlib import Path

from shopping_agent.assessment import PROMPT_VERSION, SCHEMA_VERSION, evidence_state
from shopping_agent.candidate_checks import CandidateChecks
from shopping_agent.check_suggestions import CheckSuggestions, question_key
from shopping_agent.config import AppConfig
from shopping_agent.conversation_replay import CapturingCodexRuntime, TracedRuntime
from shopping_agent.conversation_service import ConversationService
from shopping_agent.db import add_listing_snapshot, attach_run_to_task, connect, create_search_run, upsert_listing
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.runtime_telemetry import summarize_telemetry
from shopping_agent.setup_status import check_codex_availability


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not args.run:
        print(json.dumps(dict(mode="plan_only", calls=0, turns=2, simulated_user_confirmations=1)))
        return 0
    if not args.output:
        parser.error("--run requires --output")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        report = dict(mode="real_model_check_suggestion_journey", prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
            calls=[], turns=[], checks=[], state="initializing", quality_verified=False, manual_review="pending",
            model_identity=None, cost=None, tool_calls=None, max_calls=2,
            excluded=["HTTP/browser", "platform collection", "raw vision", "independent device verification"])
        def save():
            report["telemetry_summary"] = summarize_telemetry(report["calls"])
            report["tokens"] = report["telemetry_summary"]["tokens"]
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()
        save()
        status = check_codex_availability()
        if not status.cli_available or not status.auth_available:
            report.update(state="setup_unavailable", setup=status.model_dump())
            save()
            return 2
        with tempfile.TemporaryDirectory(prefix="check-suggestion-journey-") as directory:
            root = Path(directory)
            analysis = root / "analysis"
            analysis.mkdir()
            subprocess.run(["git", "init", "--quiet", str(analysis)], check=True, capture_output=True)
            config = AppConfig(database_path=root / "fixture.sqlite")
            service = ConversationService(config)
            goal = "买256GB二手手机，预算4300元，必须全原无维修。请只依据已保存证据回答，提出与屏幕及维修记录有关的具体待核实问题供我确认，不要直接保存或访问平台。"
            created = service.create_task(goal)
            task = created.task.id
            with closing(connect(config.database_path)) as conn, conn:
                run = create_search_run(conn, goal, "上海")
                attach_run_to_task(conn, task, run)
                listing = upsert_listing(conn, "xianyu", "https://example.test/suggestion-journey/phone")
                add_listing_snapshot(conn, listing, run, title="虚构手机256GB", price_text="4000", location="上海",
                    description="卖家标称256GB，未提供维修记录、部件页面或电池情况。")
                facts = evidence_state(conn, task)
            runtime = TracedRuntime(CapturingCodexRuntime(analysis, timeout_seconds=args.timeout, capture_telemetry=True), report["calls"], save, max_calls=2)
            coordinator = OperationCoordinator(service, runtime)
            store = CheckSuggestions(config)
            try:
                for turn in (1, 2):
                    operation = created.operation if turn == 1 else service.send_message(task,
                        "请再提出一项关于电池实际健康情况的待核实建议，供我确认；与已保存问题重复的不要再提。只增加跟进问题，不修改购买条件，不直接入单，不访问平台。").operation
                    coordinator.start(operation.id)
                    deadline = time.monotonic() + args.timeout + 30
                    while time.monotonic() < deadline:
                        current = service.store.get_operation(operation.id)
                        if current.state not in {"queued", "running"}:
                            break
                        time.sleep(.05)
                    else:
                        coordinator.cancel(operation.id)
                        raise RuntimeError("turn timeout")
                    proposals = store.page(task, listing)
                    checks = CandidateChecks(config).page(task, listing)
                    report["turns"].append(dict(number=turn, operation=asdict(current), proposals=proposals, checklist=checks))
                    save()
                    if current.state != "completed":
                        raise RuntimeError("model operation did not complete")
                    pending = [r for r in proposals["items"] if r["check_id"] is None]
                    if not pending or checks["total_count"] != turn-1:
                        raise RuntimeError("expected unsaved proposals and no automatic checklist writes")
                    if turn == 1:
                        chosen = pending[0]
                        accepted = store.accept(task, listing, chosen["id"])
                        retry = store.accept(task, listing, chosen["id"])
                        if accepted != retry or accepted["check"]["state"] != "pending":
                            raise RuntimeError("confirmation retry or pending state invalid")
                        report["simulated_user_confirmation"] = accepted
                        first_question = question_key(chosen["question"])
                        report["checks"].append("first proposals unsaved; simulated user confirmation creates one pending question idempotently")
                    else:
                        new = [r for r in pending if r["operation_id"] == operation.id]
                        if not new or any(question_key(r["question"]) == first_question for r in new):
                            raise RuntimeError("missing new follow-up question or repeated saved question")
                        report["checks"].append("second turn reads saved question, proposes a different unsaved follow-up without modifying requirements")
                    with closing(connect(config.database_path)) as conn, conn:
                        if evidence_state(conn, task) != facts or conn.execute("SELECT COUNT(*) FROM task_preference_revisions WHERE task_id=?", (task,)).fetchone()[0]:
                            raise RuntimeError("suggestion workflow changed evidence or requirements")
                    save()
                restarted = ConversationService(config)
                restored = CandidateChecks(restarted.config).page(task, listing)
                if restored["total_count"] != 1:
                    raise RuntimeError("confirmed question did not survive service recreation")
                report.update(state="checks_passed_manual_review_pending", restored_checklist=restored)
            except Exception as exc:
                report.update(state="execution_or_checks_failed", error_type=type(exc).__name__, error=str(exc))
                save()
            finally:
                coordinator.shutdown()
                del coordinator, runtime
                gc.collect()
        report["calls_count"] = len(report["calls"])
        report["duration_seconds"] = round(sum(c["duration_seconds"] for c in report["calls"]), 3)
        save()
        print(json.dumps(dict(state=report["state"], calls=report["calls_count"])))
        return 0 if report["state"] == "checks_passed_manual_review_pending" else 1


if __name__ == "__main__":
    raise SystemExit(main())
