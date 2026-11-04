"""Standalone process entry: uses the external engine's Python environment.

No imports from shopping_agent: engine dependencies remain in that environment.
The supported upstream contract is checked by the parent before launching.
"""
import asyncio
import builtins
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if __package__:
    from .image_capture_audit import ImageCaptureAudit
    from .goofish_evidence import DetailEvidenceTap, retain_search_images
    from .goofish_failure_guard import FailureGuard
    from .goofish_pipeline import EvidenceJournal, collection_dispatcher, price_recorder
    from .goofish_status import WorkerStatus
    from .goofish_control_flow import CompatibilityError, repair_detail_control_flow
    from .goofish_browser import CredentialError, monitor_cookies, protected_playwright, MAX_CREDENTIAL_BYTES
else:
    from image_capture_audit import ImageCaptureAudit
    from goofish_evidence import DetailEvidenceTap, retain_search_images
    from goofish_failure_guard import FailureGuard
    from goofish_pipeline import EvidenceJournal, collection_dispatcher, price_recorder
    from goofish_status import WorkerStatus
    from goofish_control_flow import CompatibilityError, repair_detail_control_flow
    from goofish_browser import CredentialError, monitor_cookies, protected_playwright, MAX_CREDENTIAL_BYTES


async def collect(root, directory, *, status=None):
    status = status or WorkerStatus(directory)
    job = json.loads((directory / "job.json").read_text(encoding="utf-8"))
    status.round_id = job.get("round_id")
    status.update("timezone_check")
    # Fail before importing/starting the browser when the engine environment
    # lacks the timezone data used by upstream's daily pause/notification rules.
    ZoneInfo("Asia/Shanghai")
    if job.get("credential_transport") != "stdin":
        raise CredentialError("Monitor login required")
    try:
        payload = sys.stdin.buffer.read(MAX_CREDENTIAL_BYTES + 1)
        if len(payload) > MAX_CREDENTIAL_BYTES:
            raise CredentialError("Invalid monitor credential")
        credentials = monitor_cookies(json.loads(payload))
    except (ValueError, TypeError, RecursionError):
        raise CredentialError("Monitor login required") from None
    status.update("engine_import")
    sys.path.insert(0, str(root))
    import dotenv
    # Do not inherit the reference checkout's account/model/notification settings.
    dotenv.load_dotenv = lambda *a, **kw: False
    dotenv.dotenv_values = lambda *a, **kw: {}
    from src import scraper
    outcome = {"error_code": None}
    failure_recorded = False

    def control_failure(code):
        # Latch before finally/dispatcher cleanup, so cleanup errors cannot
        # turn a detected login/verification failure into an apparent success.
        if outcome["error_code"] not in {"login_required", "verification_required"}:
            outcome["error_code"] = code
        status.update("collecting", outcome["error_code"])

    repair_detail_control_flow(scraper, on_control_failure=control_failure)
    scraper.async_playwright = protected_playwright(scraper.async_playwright, credentials,
        browser_channel=job.get('browser_channel'))

    class ObservedGuard(FailureGuard):
        def record_failure(self, task_key, reason, **kwargs):
            nonlocal failure_recorded
            message = str(reason).lower()
            code = (
                "login_required" if any(s in message for s in ("login", "登录", "passport")) else
                "verification_required" if any(s in message for s in ("validate", "verification", "baxia", "middleware_frame_widget", "风控", "验证")) else
                "engine_failed"
            )
            if outcome["error_code"] in {"login_required", "verification_required"}:
                code = outcome["error_code"]
            # Keep upstream's state transition, immediate-pause override and
            # cookie mtime. Persist a fixed category instead of raw exceptions.
            result = super().record_failure(task_key, code, **kwargs)
            failure_recorded = True
            outcome["error_code"] = code
            return result

        def should_skip_start(self, *args, **kwargs):
            decision = super().should_skip_start(*args, **kwargs)
            if decision.skip:
                outcome["error_code"] = "engine_paused"
            return decision

    guard = ObservedGuard(path=str(directory / "failure-guard.json"))
    # Replace the persistence dependency, not the failure-handler function.
    # The original _notify_task_failure still records failures before notifying.
    scraper.FAILURE_GUARD = guard
    output = directory / "products.jsonl"
    def pipeline_error(code):
        if outcome["error_code"] is None:
            outcome["error_code"] = code

    stats = {}
    # Observe only the detail JSON already fetched by upstream. No browser,
    # request, retry, concurrency or failure-control behavior is changed.
    try:
        image_audit=ImageCaptureAudit(directory/'logs',job['round_id'])
        import hashlib
        files={'worker':Path(__file__),'evidence':Path(__file__).with_name('goofish_evidence.py'),
               'pipeline':Path(__file__).with_name('goofish_pipeline.py'),'upstream_parser':root/'src/parsers.py','upstream_scraper':root/'src/scraper.py'}
        image_audit.installed({k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in files.items()})
    except (OSError,ValueError):image_audit=None
    detail_evidence = DetailEvidenceTap(image_audit=image_audit)
    scraper._parse_search_results_json = retain_search_images(scraper._parse_search_results_json,image_audit=image_audit)
    scraper.safe_get = detail_evidence.wrap(scraper.safe_get)
    scraper.record_market_snapshots = price_recorder(scraper.record_market_snapshots,
        EvidenceJournal(directory / "prices.jsonl"), job["round_id"], pipeline_error,
        cards_journal=EvidenceJournal(directory / "cards.jsonl",image_audit=image_audit))
    dispatcher = collection_dispatcher(scraper.ItemAnalysisDispatcher, EvidenceJournal(output,image_audit=image_audit),
        collect_seller_profiles=job.get("collect_seller_profiles") is True, on_error=pipeline_error, stats=stats,
        detail_evidence=detail_evidence)

    async def no_notification(*args, **kwargs):
        pass

    def processed(keyword):
        seen = set()
        if output.exists():
            with output.open("rb") as stream:
                for line in stream:
                    try:
                        record = json.loads(line)
                        seen.add(scraper.get_link_unique_key(record["商品信息"]["商品链接"]))
                    except (ValueError, KeyError, TypeError):
                        continue
        return seen

    scraper.ItemAnalysisDispatcher = dispatcher
    scraper.send_ntfy_notification = no_notification
    scraper.load_processed_link_keys = processed
    # Upstream debug_limit is the item cap, but also invokes input() on exit.
    builtins.input = lambda *args: ""
    status.update("collecting")
    task = {
        "task_name": job["source_task"], "keyword": job["keyword"],
        "max_pages": job["max_pages"], "account_state_file": job["state_file"],
        "account_rotation": {"enabled": False, "retry_limit": 1},
        "proxy_rotation": {"enabled": False, "retry_limit": 1},
        "analyze_images": False,
    }
    try:
        await scraper.scrape_xianyu(task, debug_limit=job["max_items"])
    except Exception:
        if outcome["error_code"] not in {"login_required", "verification_required"}:
            raise
        # A close/join error must not erase the already detected control failure.
    if outcome["error_code"] in {"login_required", "verification_required"} and not failure_recorded:
        guard.record_failure(job["source_task"], outcome["error_code"], cookie_path=job["state_file"])
    state = guard._load().get("tasks", {}).get(job["source_task"], {})
    outcome["failure_guard"] = {
        "consecutive_failures": state.get("consecutive_failures", 0),
        "paused_until": state.get("paused_until"),
    }
    outcome["collection"] = stats
    status.update("completed", outcome["error_code"])
    return outcome


def main():
    root, directory = map(lambda s: Path(s).resolve(), sys.argv[1:3])
    outcome = {"error_code": "engine_failed"}
    status = WorkerStatus(directory)
    try:
        outcome = asyncio.run(collect(root, directory, status=status))
    except ModuleNotFoundError:
        outcome = {"error_code": "engine_dependencies_missing"}
    except ZoneInfoNotFoundError:
        outcome = {"error_code": "engine_timezone_missing"}
    except CredentialError:
        outcome = {"error_code": "login_required"}
    except CompatibilityError:
        outcome = {"error_code": "engine_version_unsupported"}
    except Exception:
        # A diagnostic/cleanup failure after detection cannot hide verification.
        if status.error_code in {"login_required", "verification_required"}:
            outcome = {"error_code": status.error_code}
        # Never export raw engine exceptions, URLs, cookies or local paths.
    status.update(status.phase, outcome["error_code"])
    pending = directory / "outcome.tmp"
    pending.write_text(json.dumps(outcome), encoding="utf-8")
    pending.replace(directory / "outcome.json")


if __name__ == "__main__":
    main()
