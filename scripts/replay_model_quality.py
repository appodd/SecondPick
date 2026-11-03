"""Opt-in real-model offline probes; defaults to a call-free plan."""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from shopping_agent.assessment import PROMPT_VERSION, SCHEMA_VERSION
from shopping_agent.codex_runtime import CodexRuntime, CodexRuntimeError
from shopping_agent.quality_replay import SUITE_VERSION, build_probes, check_probe, probe_manifest, rescore_report
from shopping_agent.setup_status import check_codex_availability


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Actually call the configured Codex CLI")
    mode.add_argument("--rescore", type=Path, help="Recheck a saved report without model calls")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--case", action="append", choices=[p.name for p in build_probes()])
    parser.add_argument("--timeout", type=int, default=90, help="Per-call timeout seconds")
    parser.add_argument("--output", type=Path, help="New report file; existing files are never overwritten")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.rescore:
        if args.output is None:
            parser.error("--rescore requires --output (a new file)")
        report = json.loads(args.rescore.read_text(encoding="utf-8"))
        rescored = rescore_report(report, CodexRuntime(Path.cwd()))
        rescored["source_report"] = str(args.rescore)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(rescored, output, ensure_ascii=False, indent=2)
        print(json.dumps({key: rescored[key] for key in ("mode", "calls", "checks_passed", "evaluated_cases")}, ensure_ascii=False))
        return 0 if rescored["state"] == "checks_passed_manual_review_pending" else 1
    probes = [p for p in build_probes(args.seed) if not args.case or p.name in args.case]
    if not args.run:
        print(json.dumps(dict(mode="plan_only", cases=[p.name for p in probes], seed=args.seed,
                              calls=0, quality_verified=False), ensure_ascii=False))
        return 0
    if args.output is None:
        parser.error("--run requires --output to preserve reviewable results")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve before invoking the model: a typo must not spend calls and then
    # discover an existing output file. Partial reports survive interruptions.
    with args.output.open("x", encoding="utf-8") as output:
        report = dict(suite_version=SUITE_VERSION, seed=args.seed, mode="real_model",
                      started_at=datetime.now(timezone.utc).isoformat(), timeout_seconds=args.timeout,
                      prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
                      model_identity="CLI configured default; not resolved by adapter",
                      tokens=None, cost=None, tool_calls=None, selected_cases=len(probes),
                      planned_cases=[p.name for p in probes],
                      quality_verified=False, manual_review="pending",
                      excluded=["eight-turn product flow", "platform collection", "raw vision", "semantic prose scoring"],
                      cases=[])

        def save():
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()

        status = check_codex_availability()
        if not status.cli_available or not status.auth_available:
            report.update(state="setup_unavailable", setup=status.model_dump())
            save()
            return 2
        report["state"] = "running"
        save()
        with tempfile.TemporaryDirectory(prefix="shopping-quality-replay-") as directory:
            # Do not place source, oracles, reports, DBs or future turns in
            # this working directory. This is not an OS filesystem boundary.
            subprocess.run(["git", "init", "--quiet", directory], check=True, capture_output=True)
            runtime = CodexRuntime(Path(directory), timeout_seconds=args.timeout)
            for number, probe in enumerate(probes, 1):
                record = probe_manifest(probe)
                record.update(state="running", manual_review="pending")
                report["cases"].append(record)
                save()
                print(f"{number}/{len(probes)} {probe.name}: running", flush=True)
                started = time.monotonic()
                try:
                    result = runtime.run(probe.request, run_id=number)
                    errors = check_probe(probe, result)
                    record.update(state="checks_failed" if errors else "checks_passed",
                                  checks=errors, result=result.model_dump(mode="json"))
                except CodexRuntimeError as exc:
                    record.update(state="execution_error", error_type=type(exc).__name__)
                record["duration_seconds"] = round(time.monotonic() - started, 3)
                save()
                print(f"{probe.name}: {record['state']}", flush=True)
                # A broken CLI/auth/timeout is not seven model-quality failures.
                if record["state"] == "execution_error":
                    break
        report["not_run"] = [p.name for p in probes if p.name not in {r["name"] for r in report["cases"]}]
        passed = sum(r["state"] == "checks_passed" for r in report["cases"])
        report.update(state="checks_passed_manual_review_pending" if passed == len(probes) else "incomplete_or_failed",
                      checks_passed=passed, selected_cases=len(probes))
        save()
        return 0 if passed == len(probes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
