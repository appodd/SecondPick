"""Opt-in checklist chat probes; default only lists the plan."""
import argparse
import gc
import json
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from shopping_agent.assessment import PROMPT_VERSION, SCHEMA_VERSION
from shopping_agent.check_context_replay import CASE_NAMES, build_check_probes, check_check_probe
from shopping_agent.statement_correction_replay import correction_manifest
from shopping_agent.conversation_replay import CapturingCodexRuntime, TracedRuntime
from shopping_agent.codex_runtime import CodexRuntimeError
from shopping_agent.runtime_telemetry import summarize_telemetry
from shopping_agent.setup_status import check_codex_availability


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--reviews", action="store_true", help="Probe user review provenance and expiry instead of plain checklists")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    cases, build, check_probe = CASE_NAMES, build_check_probes, check_check_probe
    if args.reviews:
        from shopping_agent.check_review_replay import CASE_NAMES as REVIEW_CASES, build_review_probes, check_review_probe
        cases, build, check_probe = REVIEW_CASES, build_review_probes, check_review_probe
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not args.run:
        print(json.dumps(dict(mode="plan_only", calls=0, cases=cases)))
        return 0
    if not args.output:
        parser.error("--run requires --output")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        report = dict(mode="real_model_check_review_probes" if args.reviews else "real_model_check_context_probes", suite_version="check-review-v1" if args.reviews else "check-context-v1",
            prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION, seed=args.seed,
            started_at=datetime.now(timezone.utc).isoformat(), calls=[], cases=[], state="initializing",
            quality_verified=False, manual_review="pending", model_identity="CLI configured default; unresolved",
            cost=None, tool_calls=None, max_calls=3, timeout_seconds=args.timeout,
            excluded=["model result persistence", "HTTP/browser", "platform collection", "raw vision"])
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
        with tempfile.TemporaryDirectory(prefix="check-context-probes-") as directory:
            root = Path(directory)
            analysis = root / "analysis"
            analysis.mkdir()
            subprocess.run(["git", "init", "--quiet", str(analysis)], check=True, capture_output=True)
            probes = build(root, args.seed)
            runtime = TracedRuntime(CapturingCodexRuntime(analysis, timeout_seconds=args.timeout, capture_telemetry=True), report["calls"], save, max_calls=3)
            try:
                for number, probe in enumerate(probes, 1):
                    row = dict(correction_manifest(probe), state="running")
                    report["cases"].append(row)
                    save()
                    print(f"{number}/3 {probe.name}: running", flush=True)
                    try:
                        result = runtime.run(probe.request, run_id=number)
                        errors = check_probe(probe, result)
                        row.update(state="checks_failed" if errors else "checks_passed", checks=errors, result=result.model_dump(mode="json"))
                    except CodexRuntimeError as exc:
                        row.update(state="execution_error", error_type=type(exc).__name__)
                        save()
                        break
                    save()
                    print(f"{probe.name}: {row['state']}", flush=True)
            finally:
                del runtime
                gc.collect()
        passed = sum(row["state"] == "checks_passed" for row in report["cases"])
        report.update(checks_passed=passed, calls_count=len(report["calls"]),
            state="checks_passed_manual_review_pending" if passed == 3 else "incomplete_or_failed")
        save()
        return 0 if passed == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
