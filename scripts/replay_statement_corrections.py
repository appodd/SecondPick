"""Opt-in real-model correction probes; no platform executor or product DB."""
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
from shopping_agent.conversation_replay import CapturingCodexRuntime, TracedRuntime
from shopping_agent.setup_status import check_codex_availability
from shopping_agent.runtime_telemetry import summarize_telemetry
from shopping_agent.statement_correction_replay import (
    CASE_NAMES, build_correction_probes, check_correction_probe, correction_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not args.run:
        print(json.dumps(dict(mode="plan_only", calls=0, cases=CASE_NAMES)))
        return 0
    if args.output is None:
        parser.error("--run requires --output")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        report = dict(mode="real_model_correction_probes", suite_version="statement-corrections-v1",
                      started_at=datetime.now(timezone.utc).isoformat(), seed=args.seed,
                      prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
                      model_identity="CLI configured default; unresolved", tokens=None, cost=None, tool_calls=None,
                      timeout_seconds=args.timeout, max_calls=3, state="initializing", calls=[], cases=[],
                      quality_verified=False, manual_review="pending",
                      excluded=["model assessment persistence", "raw vision", "platform collection", "HTTP/browser"])
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
        save()
        with tempfile.TemporaryDirectory(prefix="statement-correction-probes-") as directory:
            root = Path(directory)
            analysis = root / "analysis"
            analysis.mkdir()
            subprocess.run(["git", "init", "--quiet", str(analysis)], check=True, capture_output=True)
            probes = build_correction_probes(root, args.seed)
            runtime = TracedRuntime(CapturingCodexRuntime(analysis, timeout_seconds=args.timeout, capture_telemetry=True),
                                    report["calls"], save, max_calls=3)
            try:
                for number, probe in enumerate(probes, 1):
                    row = dict(correction_manifest(probe), state="running")
                    report["cases"].append(row)
                    save()
                    print(f"{number}/3 {probe.name}: running", flush=True)
                    try:
                        result = runtime.run(probe.request, run_id=number)
                        errors = check_correction_probe(probe, result)
                        row.update(state="checks_failed" if errors else "checks_passed", checks=errors,
                                   result=result.model_dump(mode="json"))
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
                      not_run=[name for name in CASE_NAMES if name not in {c["name"] for c in report["cases"]}],
                      state="checks_passed_manual_review_pending" if passed == 3 else "incomplete_or_failed")
        save()
        return 0 if passed == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
