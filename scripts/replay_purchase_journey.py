"""Opt-in synthetic eight-turn replay through production services; no collection."""
from __future__ import annotations

import argparse
import gc
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from shopping_agent.assessment import PROMPT_VERSION, SCHEMA_VERSION
from shopping_agent.codex_runtime import CodexRuntimeError
from shopping_agent.config import AppConfig
from shopping_agent.conversation_replay import (CHECKER_VERSION, JOURNEY_VERSION, ROUND_NAMES, CapturingCodexRuntime,
    TracedRuntime, audit_saved_journey, run_journey, saved_failed_request)
from shopping_agent.setup_status import check_codex_availability
from shopping_agent.runtime_telemetry import summarize_telemetry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--audit", type=Path, help="Recheck a saved report without model calls")
    mode.add_argument("--diagnose", type=Path, help="One NEW model call for a saved failed input, not a journey retry")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--timeout", type=int, default=120, help="Per-model-call seconds")
    parser.add_argument("--turn-timeout", type=int, default=600)
    parser.add_argument("--max-calls", type=int, default=32)
    parser.add_argument("--current-prompt", action="store_true", help="Diagnose using changed current prompt; never rescore old results")
    parser.add_argument("--output", type=Path, help="New report file; never overwrite")
    args = parser.parse_args()
    if min(args.timeout, args.turn_timeout, args.max_calls) <= 0:
        parser.error("timeouts and max-calls must be positive")
    if args.current_prompt and not args.diagnose:
        parser.error("--current-prompt requires --diagnose")
    if args.audit:
        if args.output is None:
            parser.error("--audit requires --output")
        result = audit_saved_journey(json.loads(args.audit.read_text(encoding="utf-8")))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
        print(json.dumps(dict(state=result["state"], calls=0)))
        return 0 if result["state"] == "checks_passed_manual_review_pending" else 1
    if not args.run and not args.diagnose:
        print(json.dumps(dict(mode="plan_only", calls=0, rounds=ROUND_NAMES, seed=args.seed,
                              quality_verified=False)))
        return 0
    if args.output is None:
        parser.error("--run/--diagnose requires --output")
    diagnostic_request = None
    diagnostic_source = None
    if args.diagnose:
        diagnostic_source = json.loads(args.diagnose.read_text(encoding="utf-8"))
        diagnostic_request = saved_failed_request(diagnostic_source, allow_prompt_change=args.current_prompt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        report = dict(mode="diagnostic_saved_call" if args.diagnose else "real_model_service_journey", suite_version=JOURNEY_VERSION,
            checker_version=CHECKER_VERSION,
            started_at=datetime.now(timezone.utc).isoformat(), seed=args.seed,
            prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION, calls=[], rounds=[],
            quality_verified=False, manual_review="pending", model_identity="CLI configured default; unresolved",
            tokens=None, cost=None, tool_calls=None, max_calls=args.max_calls,
            timeout_seconds=args.timeout, turn_timeout_seconds=args.turn_timeout,
            excluded=["raw vision", "platform collection", "independent device verification", "HTTP/browser transport"])
        def save():
            report["telemetry_summary"] = summarize_telemetry(report["calls"])
            report["tokens"] = report["telemetry_summary"]["tokens"]
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()
        status = check_codex_availability()
        if not status.cli_available or not status.auth_available:
            report.update(state="setup_unavailable", setup=status.model_dump())
            save()
            return 2
        report["state"] = "initializing"
        save()
        # Separate working directory from the synthetic DB. Read-only CLI is
        # not an OS filesystem isolation boundary; do not claim otherwise.
        with tempfile.TemporaryDirectory(prefix="purchase-journey-") as directory:
            root = Path(directory)
            analysis_root = root / "analysis"
            analysis_root.mkdir()
            subprocess.run(["git", "init", "--quiet", str(analysis_root)], check=True, capture_output=True)
            config = AppConfig(database_path=root / "fixture.sqlite", browser_profile_dir=root / "profile",
                screenshots_dir=root / "screenshots", media_dir=root / "media", reports_dir=root / "reports")
            runtime = TracedRuntime(CapturingCodexRuntime(analysis_root, timeout_seconds=args.timeout, capture_telemetry=True), report["calls"], save,
                                    1 if args.diagnose else args.max_calls)
            try:
                if diagnostic_request is not None:
                    report["source_report"] = str(args.diagnose)
                    report["source_prompt_signature"] = diagnostic_source["calls"][-1]["prompt_signature"]
                    report["source_prompt_version"] = diagnostic_source["prompt_version"]
                    report["allow_prompt_change"] = args.current_prompt
                    try:
                        runtime.run(diagnostic_request, run_id=1)
                        report["state"] = "diagnostic_result_returned"
                    except CodexRuntimeError:
                        report["state"] = "diagnostic_execution_error"
                    save()
                else:
                    run_journey(config, runtime, seed=args.seed, report=report, save=save, turn_timeout=args.turn_timeout)
            finally:
                del runtime
                gc.collect()  # Release legacy SQLite handles before Windows cleanup.
        return 0 if report["state"] in {"checks_passed_manual_review_pending", "diagnostic_result_returned"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
