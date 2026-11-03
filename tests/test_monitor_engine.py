import json
import os
from pathlib import Path
import sys
import threading
import shutil

import pytest

from shopping_agent.config import AppConfig, MonitorEngineConfig
from shopping_agent.db import connect, create_research_task, initialize
from shopping_agent.candidate_context import build_candidate_index
from shopping_agent.monitor_engine import GoofishEngine, EngineError, run_process


@pytest.fixture
def engine(tmp_path, monkeypatch):
    root = tmp_path / "fake-reference"
    (root / "src").mkdir(parents=True)
    (root / "src/__init__.py").write_text("")
    fixtures = Path(__file__).parent / "fixtures/goofish_upstream/src"
    shutil.copytree(fixtures / "services", root / "src/services")
    shutil.copyfile(fixtures / "keyword_rule_engine.py", root / "src/keyword_rule_engine.py")
    (root / "dotenv.py").write_text('def load_dotenv(*a, **kw): raise AssertionError("must disable dotenv")\n')
    (root / "src/scraper.py").write_text('''
import os
import asyncio
from pathlib import Path
from types import SimpleNamespace
from src.services.item_analysis_dispatcher import ItemAnalysisDispatcher, ItemAnalysisJob
from src.services.seller_profile_cache import SellerProfileCache
def trap(*a, **kw):
    Path("forbidden-callback").write_text("called")
    raise AssertionError("forbidden callback")
def get_link_unique_key(link): return link.split("&", 1)[0]
def async_playwright(): return trap()
def _parse_search_results_json(data): return []
def safe_get(data, *keys, default=None):
    for key in keys:
        if not isinstance(data, dict): return default
        data = data.get(key)
    return default if data is None else data

class RiskControlError(Exception): pass
class LoginRequiredError(Exception): pass
class PlaywrightTimeoutError(Exception): pass
def _is_login_url(url): return "passport.goofish.com" in url
async def random_sleep(low, high): pass

class DetailPage:
    def __init__(self, keyword, number):
        self.keyword, self.number, self.url = keyword, number, "about:blank"
    def expect_response(self, *args, **kwargs): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def goto(self, link, **kwargs):
        self.url = link
        with Path("detail-visits").open("a") as stream: stream.write(str(self.number) + "\\n")
        if self.number == 101 and self.keyword == "login-detail":
            self.url = "https://passport.goofish.com/mini_login"
        if self.number == 101 and self.keyword in ("timeout-detail", "login-timeout"):
            if self.keyword == "login-timeout": self.url = "https://passport.goofish.com/mini_login"
            raise PlaywrightTimeoutError("synthetic timeout")
    def locator(self, selector):
        visible = self.number == 101 and self.keyword == "dialog-detail"
        async def is_visible(): return visible
        return SimpleNamespace(is_visible=is_visible)
    @property
    def value(self):
        async def response(): return self
        return response()
    async def json(self):
        return {"ret": ["FAIL_SYS_USER_VALIDATE"] if self.number == 101 and self.keyword in ("risk-detail", "risk-close") else ["SUCCESS"]}
    async def close(self):
        with Path("detail-closed").open("a") as stream: stream.write(str(self.number) + "\\n")
        if self.number == 101 and self.keyword == "risk-close":
            raise RuntimeError("synthetic cleanup failure with private text")
def record_market_snapshots(**kwargs):
    # Native recorder contract: save normalized price records and return them.
    Path("native-prices-saved").write_text("saved")
    return [dict(keyword=kwargs["keyword"], task_name=kwargs["task_name"],
        run_id=kwargs["run_id"], snapshot_time="2026-10-20T09:00:00",
        item_id=item["商品ID"], title=item["商品标题"], price=float(item["当前售价"]),
        price_display=item["当前售价"], link=item["商品链接"]) for item in kwargs["items"]]
async def scrape_xianyu(task, debug_limit):
    decision = FAILURE_GUARD.should_skip_start(task["task_name"], cookie_path=task["account_state_file"])
    if decision.skip: return 0
    assert os.environ["RUN_HEADLESS"] == "true"
    assert "OPENAI_API_KEY" not in os.environ
    assert "NTFY_TOPIC_URL" not in os.environ
    assert task["account_rotation"]["enabled"] is False
    assert task["proxy_rotation"]["enabled"] is False
    assert input("must not block") == ""
    assert Path(task["account_state_file"]).read_text() == "{}"
    cache = SellerProfileCache()
    async def load_seller(key):
        with Path("seller-calls").open("a") as stream: stream.write("called\\n")
        await asyncio.sleep(.01)
        return {"卖家昵称": "来源昵称", "作为卖家的好评率": "99%"}
    dispatcher = ItemAnalysisDispatcher(concurrency=2, skip_ai_analysis=True,
        seller_loader=lambda key: cache.get_or_load(key, load_seller),
        ai_analyzer=trap, image_downloader=trap, notifier=trap, saver=trap)
    seen = load_processed_link_keys(task["keyword"])
    price = Path("next-price").read_text() if Path("next-price").exists() else "399"
    record_market_snapshots(keyword=task["keyword"], task_name=task["task_name"], run_id="same-second",
        items=[{"商品ID": str(n), "商品标题": "手柄", "当前售价": price,
                "商品链接": "https://www.goofish.com/item?id=" + str(n)}
               for n in range(100,100+(405 if task["keyword"] == "wide-pool" else debug_limit))])
    if task["keyword"] == "prices-only":
        await asyncio.sleep(30)
    try:
        for number in range(100, 100 + debug_limit):
            link = "https://www.goofish.com/item?id=" + str(number)
            if link in seen: continue
            detail_page = DetailPage(task["keyword"], number)
            try:
                async with detail_page.expect_response(lambda r: True, timeout=25000) as detail_info:
                    await detail_page.goto(link, wait_until="domcontentloaded", timeout=25000)
                detail_response = await detail_info.value
                detail_json = await detail_response.json()
                ret_string = str(detail_json["ret"])
                if "FAIL_SYS_USER_VALIDATE" in ret_string:
                    await random_sleep(3, 60)
                    raise RiskControlError("FAIL_SYS_USER_VALIDATE")
                record = {"任务名称": task["task_name"], "搜索关键字": task["keyword"],
                          "爬取时间": "2026-10-20T09:00:00", "商品信息": {
                            "商品ID": str(number), "商品标题": "手柄", "商品链接": link, "当前售价": "399"}}
                dispatcher.submit(ItemAnalysisJob(final_record=record, keyword=task["keyword"], task_name=task["task_name"],
                    keyword_rules=(), seller_id="same-seller", zhima_credit_text=None,
                    registration_duration_text=None, decision_mode="ai", prompt_text="", analyze_images=False))
            except PlaywrightTimeoutError:
                pass  # Same native policy: an ordinary single-item timeout may continue.
            except Exception:
                pass  # Reproduces the native swallowed verification exception.
            finally:
                await detail_page.close()
                await random_sleep(2, 4)
        Path("next-page-visited").write_text("normal completion")
    except (RiskControlError, LoginRequiredError) as exc:
        await dispatcher.join()
        await _notify_task_failure(task, str(exc), cookie_path=task["account_state_file"])
        return
    await dispatcher.join()
    if task["keyword"] == "slow" and not Path("allow-completion").exists():
        await asyncio.sleep(30)
    await send_ntfy_notification({}, "should be disabled")
    if task["keyword"] == "login":
        await _notify_task_failure(task, "Login required private-cookie", cookie_path=task["account_state_file"])
    else:
        FAILURE_GUARD.record_success(task["task_name"])
''' + (Path(__file__).parent / "fixtures/goofish_failure_handler.py").read_text(encoding="utf-8"), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"cookies": [{"name": "test", "value": "pipe-only-secret",
        "domain": ".goofish.com", "path": "/", "expires": -1}]}))
    config = AppConfig(database_path=tmp_path / "db.sqlite", monitor_engine=MonitorEngineConfig(
        enabled=True, root=root, python=Path(sys.executable), state_file=state, work_dir=tmp_path / "work"))
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task_id = create_research_task(conn, "手柄", "NS2 Pro", "上海")
    value = GoofishEngine(config)
    monkeypatch.setattr(value, "preflight", lambda: root)
    monkeypatch.setenv("OPENAI_API_KEY", "never-inherit-this")
    monkeypatch.setenv("NTFY_TOPIC_URL", "never-send-this")
    return value, dict(id=1, task_id=task_id, keyword="NS2 Pro", max_pages=3, max_items=3)


def test_standalone_worker_collects_without_models_or_notifications_then_imports(engine):
    value, monitor = engine
    result = value.run(monitor, threading.Event())
    assert result["error_code"] is None and result["imported"] == 3
    assert result["search_cards"]["imported"] == 3
    assert build_candidate_index(value.config, task_id=monitor["task_id"])["deduplicated_count"] == 3
    # Repeated round deduplicates before submitting jobs and again on import.
    second = value.run(monitor, threading.Event())
    assert second["imported"] == 0 and second["duplicates"] == 0
    assert second["bytes_read"] == 0
    assert second["search_cards"]["imported"] == 3
    assert not list(value.config.monitor_engine.work_dir.glob("*/monitor-1/forbidden-callback"))
    assert not list(value.config.monitor_engine.work_dir.glob("*/monitor-1/seller-calls"))


def test_worker_collects_search_pool_beyond_detail_limit_without_extra_detail_work(engine):
    from shopping_agent.web.services import WorkbenchService
    value, monitor = engine
    monitor["keyword"] = "wide-pool"
    result = value.run(monitor, threading.Event())
    assert result["error_code"] is None
    assert result["imported"] == 3 and result["collection"]["raw_saved"] == 3
    assert result["search_cards"]["imported"] == 405
    assert result["candidate_pool_count"] == 405
    assert result["price_observations"]["imported"] == 405
    index = build_candidate_index(value.config, task_id=monitor["task_id"])
    assert index["deduplicated_count"] == 405
    assert index["candidates"][0]["external_source"]["evidence_stage"] == "product_record"
    assert index["candidates"][-1]["external_source"]["evidence_stage"] == "search_card"
    page = WorkbenchService(value.config).get_candidates(monitor["task_id"], limit=100, cursor=None)
    assert page.deduplicated_count == 405 and page.page.has_more
    assert not list(value.config.monitor_engine.work_dir.glob("*/monitor-1/forbidden-callback"))
    assert not list(value.config.monitor_engine.work_dir.glob("*/monitor-1/seller-calls"))


@pytest.mark.parametrize("keyword,code", [("risk-detail", "verification_required"),
    ("risk-close", "verification_required"),
    ("dialog-detail", "verification_required"), ("login-detail", "login_required"),
    ("login-timeout", "login_required")])
def test_detail_control_failure_preserves_pool_and_requires_explicit_resume(engine, keyword, code):
    from shopping_agent.monitoring import MonitorStore
    value, monitor = engine
    store = MonitorStore(value.config)
    created = store.create(monitor["task_id"], keyword=keyword, max_pages=3, max_items=3, max_rounds=3, confirmed=True)
    claimed = store.claim_due()
    assert claimed["id"] == created["id"] == monitor["id"]
    result = value.run(claimed, threading.Event())
    assert result["error_code"] == code
    assert result["imported"] == 1 and result["search_cards"]["imported"] == 3
    assert result["candidate_pool_count"] == 3
    assert result["failure_guard"]["consecutive_failures"] == 1
    directory = next(value.config.monitor_engine.work_dir.glob("*/monitor-1"))
    assert (directory / "detail-visits").read_text().splitlines() == ["100", "101"]
    assert (directory / "detail-closed").read_text().splitlines() == ["100", "101"]
    assert not (directory / "next-page-visited").exists()
    store.finish(created["id"], result)
    current = store.list(monitor["task_id"])[0]
    assert current["state"] == "needs_attention" and current["error_code"] == code
    assert current["imported"] == 1 and store.claim_due() is None
    resumed = store.control(monitor["task_id"], created["id"], "resume")
    assert resumed["state"] == "waiting" and resumed["rounds"] == 1
    assert resumed["keyword"] == keyword and resumed["max_pages"] == 3


def test_ordinary_detail_timeout_keeps_collecting_without_false_verification(engine):
    value, monitor = engine
    monitor["keyword"] = "timeout-detail"
    result = value.run(monitor, threading.Event())
    assert result["error_code"] is None and result["imported"] == 2
    directory = next(value.config.monitor_engine.work_dir.glob("*/monitor-1"))
    assert (directory / "detail-visits").read_text().splitlines() == ["100", "101", "102"]
    assert (directory / "next-page-visited").exists()


def test_changed_upstream_detail_contract_fails_before_collection(engine):
    value, monitor = engine
    source = value.config.monitor_engine.root / "src/scraper.py"
    source.write_text(source.read_text(encoding="utf-8").replace('"FAIL_SYS_USER_VALIDATE" in ret_string',
        '"UNSUPPORTED_VENDOR_CODE" in ret_string'), encoding="utf-8")
    result = value.run(monitor, threading.Event())
    assert result["error_code"] == "engine_version_unsupported"
    assert result["imported"] == result["search_cards"]["imported"] == 0
    directory = next(value.config.monitor_engine.work_dir.glob("*/monitor-1"))
    assert not (directory / "detail-visits").exists()
    assert not (directory / "native-prices-saved").exists()


def test_candidates_and_progress_visible_while_child_is_still_running_then_cancel(engine):
    import time
    from shopping_agent.monitoring import MonitorStore
    from shopping_agent.web.services import WorkbenchService
    value, monitor = engine
    monitor["keyword"] = "slow"
    store = MonitorStore(value.config)
    created = store.create(monitor["task_id"], keyword="slow", max_items=3, confirmed=True)
    assert store.claim_due()["id"] == created["id"] == monitor["id"]
    stop, results = threading.Event(), []
    thread = threading.Thread(target=lambda: results.append(value.run(monitor, stop)), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            progress = store.list(monitor["task_id"])[0]
            if progress["result"].get("candidate_pool_count") == 3:
                break
            time.sleep(.05)
        assert thread.is_alive() and not results
        assert progress["state"] == "running"
        assert progress["result"]["candidate_pool_count"] == 3
        assert progress["result"]["imported"] == 3
        assert progress["imported"] == 0  # Final accounting happens once, on finish.
        page = WorkbenchService(value.config).get_candidates(monitor["task_id"], limit=20, cursor=None)
        assert page.deduplicated_count == 3
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert results[0]["error_code"] == "cancelled" and results[0]["imported"] == 3
    store.finish(monitor["id"], results[0])
    assert store.list(monitor["task_id"])[0]["imported"] == 3


def test_sync_failure_stops_child_keeps_other_streams_and_can_resume(engine, monkeypatch):
    import shopping_agent.monitor_engine as module
    value, monitor = engine
    monitor["keyword"] = "slow"
    original = module.import_goofish_jsonl
    def fail_cards(*args, **kwargs):
        if kwargs["path"].name == "cards.jsonl":
            raise OSError("private source path must not escape")
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "import_goofish_jsonl", fail_cards)
    result = value.run(monitor, threading.Event())
    assert result["error_code"] == "engine_sync_failed"
    assert result["imported"] == result["price_observations"]["imported"] == 3
    assert result["sync_failed_streams"] == ["cards"] and result["sync_pending"]
    assert "private" not in json.dumps(result)
    monkeypatch.setattr(module, "import_goofish_jsonl", original)
    directory = next(value.config.monitor_engine.work_dir.glob("*/monitor-1"))
    (directory / "allow-completion").write_text("fixture permits completion")
    restored = value.run(monitor, threading.Event())
    assert restored["error_code"] is None
    assert restored["candidate_pool_count"] == 3
    assert restored["search_cards"]["imported"] == 6  # Failed batch plus the new round.
    assert restored["bytes_read"] == 0 and not restored["sync_pending"]


def test_bounded_final_drain_marks_backlog_and_next_round_resumes_it(engine, monkeypatch):
    import shopping_agent.goofish_journal as journal
    value, monitor = engine
    monitor["keyword"] = "wide-pool"
    monkeypatch.setattr(journal, "MAX_BATCH_LINES", 1)
    first = value.run(monitor, threading.Event())
    assert first["error_code"] is None and first["sync_pending"]
    assert 0 < first["search_cards"]["imported"] < 405
    monkeypatch.setattr(journal, "MAX_BATCH_LINES", 500)
    second = value.run(monitor, threading.Event())
    assert second["error_code"] is None and not second["sync_pending"]
    assert first["search_cards"]["imported"] + second["search_cards"]["imported"] == 810
    assert first["price_observations"]["imported"] + second["price_observations"]["imported"] == 810
    assert second["candidate_pool_count"] == 405


def test_fixed_diagnostics_report_child_stage_and_preserve_evidence_logs(engine, monkeypatch):
    import shopping_agent.monitor_diagnostics as diagnostic_module
    from shopping_agent.monitor_diagnostics import diagnostic_events
    from shopping_agent.monitoring import MonitorStore
    value, monitor = engine
    store = MonitorStore(value.config)
    assert store.create(monitor["task_id"], keyword=monitor["keyword"], confirmed=True)["id"] == monitor["id"]
    monkeypatch.setattr(diagnostic_module, "EVIDENCE_WARNING_BYTES", 1)
    result = value.run(monitor, threading.Event())
    assert result["error_code"] is None and result["diagnostics_available"]
    assert result["scheduler_owner"] == "shopping_agent"
    assert result["worker_status"] == dict(phase="completed", error_code=None)
    assert result["retention"]["warning"] and result["retention"]["policy"] == "preserve_evidence"
    events = diagnostic_events(value.config, monitor["task_id"], monitor["id"])["items"]
    assert {item["code"] for item in events} >= {"round_started", "round_finished", "worker_completed", "evidence_retained"}
    directory = next(value.config.monitor_engine.work_dir.glob("*/monitor-1"))
    assert all((directory / f"{name}.jsonl").is_file() for name in ("products", "cards", "prices"))
    assert not list(directory.glob("*.log"))


def test_preflight_failure_has_safe_diagnostic_without_launching_worker(engine, monkeypatch):
    from shopping_agent.monitor_diagnostics import diagnostic_events
    from shopping_agent.monitoring import MonitorStore
    value, monitor = engine
    MonitorStore(value.config).create(monitor["task_id"], keyword=monitor["keyword"], confirmed=True)
    def fail():
        raise EngineError("login_required")
    monkeypatch.setattr(value, "preflight", fail)
    with pytest.raises(EngineError, match="login_required"):
        value.run(monitor, threading.Event())
    events = diagnostic_events(value.config, monitor["task_id"], monitor["id"])["items"]
    assert [(item["phase"], item["code"]) for item in events] == [("preflight", "login_required")]
    assert not list(value.config.monitor_engine.work_dir.glob("*/monitor-1/job.json"))


@pytest.mark.skipif(os.name != "nt", reason="Existing credential provider uses Windows DPAPI")
def test_shared_dpapi_login_crosses_pipe_without_plaintext_files_and_invalidates_on_login_failure(engine, tmp_path):
    import asyncio
    from shopping_agent.browser.monitor_auth import save_monitor_login
    from shopping_agent.browser_jobs import BrowserJobStore
    from test_goofish_browser import cookie
    value, monitor = engine
    value.config.browser_profile_dir = tmp_path / "profile"
    value.config.browser_profile_dir.mkdir()
    value.config.monitor_engine.state_file = None
    class Context:
        async def cookies(self):
            return [cookie(value="pipe-only-secret")]
    asyncio.run(save_monitor_login(Context(), value.config.browser_profile_dir))
    store = BrowserJobStore(value.config)
    store.set_auth("verified")
    first = value.run(monitor, threading.Event())
    assert first["error_code"] is None and first["imported"] == 3
    directory = next(value.config.monitor_engine.work_dir.glob("*/monitor-1"))
    assert (directory / "session.marker").read_bytes() == b"{}"
    assert all(b"pipe-only-secret" not in path.read_bytes() for path in directory.iterdir() if path.is_file())
    assert str(value.config.browser_profile_dir) not in (directory / "job.json").read_text()
    monitor["keyword"] = "login"
    failed = value.run(monitor, threading.Event())
    assert failed["error_code"] == "login_required" and store.status()["auth_status"] == "invalid"


def test_blocked_credential_pipe_does_not_prevent_timeout_or_cleanup(tmp_path):
    import time
    started = time.monotonic()
    with pytest.raises(EngineError, match="engine_timeout"):
        run_process([sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path,
                    env=os.environ.copy(), stop=threading.Event(), timeout=.5, input_data=b"x" * (1024 * 1024))
    assert time.monotonic() - started < 8
    assert not any(t.name == "monitor-credentials" and t.is_alive() for t in threading.enumerate())


@pytest.mark.parametrize("payload", ['[]', 'x' * 4097, '{"error_code":"private-cookie"}'])
def test_invalid_outcome_does_not_drop_saved_evidence_or_echo_raw_errors(engine, monkeypatch, payload):
    import shopping_agent.monitor_engine as module
    value, monitor = engine
    def fake_process(command, *, cwd, **kwargs):
        job = json.loads((cwd / "job.json").read_text(encoding="utf-8"))
        record = {"任务名称": job["source_task"], "搜索关键字": job["keyword"],
                  "商品信息": {"商品ID": "123", "商品标题": "手柄", "商品链接": "https://www.goofish.com/item?id=123"}}
        (cwd / "products.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        (cwd / "outcome.json").write_text(payload, encoding="utf-8")
    monkeypatch.setattr(module, "run_process", fake_process)
    result = value.run(monitor, threading.Event())
    assert result["error_code"] == "engine_failed" and result["imported"] == 1
    assert "private-cookie" not in json.dumps(result)


def test_worker_preserves_partial_products_and_returns_only_safe_failure_code(engine):
    value, monitor = engine
    monitor["keyword"] = "login"
    result = value.run(monitor, threading.Event())
    assert result["imported"] == 3 and result["error_code"] == "login_required"
    outcome = next(value.config.monitor_engine.work_dir.glob("*/monitor-1/outcome.json"))
    assert "private" not in outcome.read_text()
    assert result["failure_guard"]["consecutive_failures"] == 1
    state = next(value.config.monitor_engine.work_dir.glob("*/monitor-1/failure-guard.json"))
    assert "private-cookie" not in state.read_text()


def test_repeated_round_prices_change_without_refetching_or_overwriting_profiles(engine):
    from shopping_agent.candidate_context import build_candidate_evidence
    from shopping_agent.web.schemas import CandidateSummary
    value, monitor = engine
    monitor["collect_seller_profiles"] = True
    first = value.run(monitor, threading.Event())
    assert first["price_observations"]["imported"] == 3
    directory = next(value.config.monitor_engine.work_dir.glob("*/monitor-1"))
    (directory / "next-price").write_text("359")
    second = value.run(monitor, threading.Event())
    assert second["imported"] == 0
    assert second["price_observations"]["imported"] == 3
    assert second["price_observations"]["duplicates"] == 0
    assert (directory / "native-prices-saved").exists()
    assert len((directory / "seller-calls").read_text().splitlines()) == 1
    candidate = build_candidate_index(value.config, task_id=monitor["task_id"])["candidates"][0]
    history = candidate["external_source"]["price_observations"]
    assert [item["price"] for item in history] == [359, 399]
    assert history[0]["round_id"] != history[1]["round_id"]
    assert history[0]["source_run_id"] == history[1]["source_run_id"]
    assert candidate["price_text"] == "359"  # Latest search-card price; both observations remain in history.
    assert candidate["external_source"]["seller_profile"]["作为卖家的好评率"] == "99%"
    CandidateSummary.model_validate(candidate)
    evidence = build_candidate_evidence(value.config, task_id=monitor["task_id"], listing_ids=[candidate["listing_id"]])
    assert evidence["candidates"][0]["external_source"]["price_observations"] == history


def test_authorized_profile_collection_uses_native_cache_and_reaches_candidate_evidence(engine):
    value, monitor = engine
    monitor["collect_seller_profiles"] = True
    result = value.run(monitor, threading.Event())
    assert result["error_code"] is None and result["imported"] == 6
    assert result["collection"] == dict(raw_saved=3, seller_records_saved=3, seller_profile_failures=0)
    calls = next(value.config.monitor_engine.work_dir.glob("*/monitor-1/seller-calls"))
    assert len(calls.read_text().splitlines()) == 1
    index = build_candidate_index(value.config, task_id=monitor["task_id"])
    assert index["deduplicated_count"] == 3
    profile = index["candidates"][0]["external_source"]
    assert profile["seller_profile"]["作为卖家的好评率"] == "99%"
    assert profile["independently_verified"] is False
    assert not list(value.config.monitor_engine.work_dir.glob("*/monitor-1/forbidden-callback"))


def test_worker_preserves_upstream_circuit_breaker_and_cookie_recovery(engine):
    value, monitor = engine
    monitor["keyword"] = "login"
    results = [value.run(monitor, threading.Event()) for _ in range(3)]
    assert [r["failure_guard"]["consecutive_failures"] for r in results] == [1, 2, 3]
    assert results[-1]["failure_guard"]["paused_until"]
    monitor["max_items"] = 4
    paused = value.run(monitor, threading.Event())
    assert paused["error_code"] == "engine_paused" and paused["imported"] == 0
    # Existing user-authorized scope cannot bypass a paused upstream guard.
    assert paused["failure_guard"]["consecutive_failures"] == 3
    state = value.config.monitor_engine.state_file
    previous = state.stat().st_mtime
    os.utime(state, (previous + 2, previous + 2))
    recovered = value.run(monitor, threading.Event())
    assert recovered["error_code"] == "login_required" and recovered["imported"] == 1
    assert recovered["failure_guard"]["consecutive_failures"] == 1


def test_unconfigured_engine_never_starts_a_process(tmp_path):
    engine = GoofishEngine(AppConfig(database_path=tmp_path / "db.sqlite"))
    with pytest.raises(EngineError, match="engine_not_configured"):
        engine.run(dict(id=1), threading.Event())


@pytest.mark.parametrize("cancel", [False, True])
def test_real_child_process_timeout_and_cancellation(tmp_path, cancel):
    stop = threading.Event()
    timer = threading.Timer(.3, stop.set) if cancel else None
    if timer:
        timer.start()
    try:
        with pytest.raises(EngineError, match="cancelled" if cancel else "engine_timeout"):
            run_process([sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path,
                        env=os.environ.copy(), stop=stop, timeout=.5)
    finally:
        if timer:
            timer.cancel()


def test_nonzero_exit_is_not_success(tmp_path):
    with pytest.raises(EngineError, match="engine_failed"):
        run_process([sys.executable, "-c", "raise SystemExit(7)"], cwd=tmp_path,
                    env=os.environ.copy(), stop=threading.Event(), timeout=5)


def test_timeout_stops_descendant_process_as_well(tmp_path):
    import time
    heartbeat = tmp_path / "heartbeat"
    child = "import pathlib,time; p=pathlib.Path(" + repr(str(heartbeat)) + ");\nwhile True: p.write_text(str(time.time())); time.sleep(.05)"
    parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(30)"
    with pytest.raises(EngineError, match="engine_timeout"):
        run_process([sys.executable, "-c", parent], cwd=tmp_path, env=os.environ.copy(),
                    stop=threading.Event(), timeout=1)
    assert heartbeat.exists()
    previous = heartbeat.read_text()
    time.sleep(.2)
    assert heartbeat.read_text() == previous


def test_pre_cancelled_round_does_not_spawn_any_process(tmp_path, monkeypatch):
    import shopping_agent.monitor_engine as module
    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not spawn"))
    with pytest.raises(EngineError, match="cancelled"):
        run_process([sys.executable], cwd=tmp_path, env={}, stop=stop, timeout=10)


@pytest.mark.parametrize("keyword,expected_products", [("slow", 3), ("prices-only", 0)])
def test_real_worker_timeout_still_imports_products_already_written(engine, monkeypatch, keyword, expected_products):
    import shopping_agent.monitor_engine as module
    value, monitor = engine
    original = module.run_process

    def short_timeout(*args, **kwargs):
        kwargs["timeout"] = 1
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "run_process", short_timeout)
    monitor["keyword"] = keyword
    result = value.run(monitor, threading.Event())
    assert result["error_code"] == "engine_timeout" and result["imported"] == expected_products
    assert result["price_observations"]["imported"] == 3
    assert result["search_cards"]["imported"] == 3
    assert result["candidate_pool_count"] == 3
    if keyword == "prices-only":
        index = build_candidate_index(value.config, task_id=monitor["task_id"])
        assert index["deduplicated_count"] == 3
        assert all(item["external_source"]["evidence_stage"] == "search_card" for item in index["candidates"])


def test_missing_state_or_unsupported_revision_never_launches_worker(tmp_path, monkeypatch):
    import shopping_agent.monitor_engine as module
    from types import SimpleNamespace
    state = tmp_path / "state.json"
    value = GoofishEngine(AppConfig(monitor_engine=MonitorEngineConfig(enabled=True, root=tmp_path, state_file=state)))
    with pytest.raises(EngineError, match="login_required"):
        value.preflight()
    state.write_text("{}")
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="unsupported"))
    with pytest.raises(EngineError, match="engine_version_unsupported"):
        value.preflight()


def test_damaged_previous_tail_does_not_swallow_next_round_product(engine):
    value, monitor = engine
    assert value.run(monitor, threading.Event())["imported"] == 3
    output = next(value.config.monitor_engine.work_dir.glob("*/monitor-1/products.jsonl"))
    with output.open("ab") as stream:
        stream.write(b'\xff{"unfinished":')
    monitor["max_items"] = 4
    result = value.run(monitor, threading.Event())
    assert result["error_code"] is None and result["imported"] == 1
    assert result["invalid"] == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object lifecycle")
def test_windows_owner_crash_closes_job_and_stops_descendants(tmp_path):
    import subprocess
    import time
    heartbeat = tmp_path / "crash-heartbeat"
    child = "import pathlib,time; p=pathlib.Path(" + repr(str(heartbeat)) + ");\nwhile True: p.write_text(str(time.time())); time.sleep(.05)"
    owner = "import sys,threading; from shopping_agent.monitor_engine import run_process; run_process([sys.executable,'-c'," + repr(child) + "],cwd=" + repr(str(tmp_path)) + ",env=None,stop=threading.Event(),timeout=30)"
    process = subprocess.Popen([sys.executable, "-c", owner], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 5
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert heartbeat.exists()
        process.kill()
        process.wait(timeout=5)
        time.sleep(.2)
        previous = heartbeat.read_text()
        time.sleep(.2)
        assert heartbeat.read_text() == previous
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_missing_timezone_is_reported_before_engine_import(tmp_path, monkeypatch):
    import importlib
    from zoneinfo import ZoneInfoNotFoundError
    worker = importlib.import_module("shopping_agent.goofish_worker")
    directory = tmp_path / "work"
    directory.mkdir()
    (directory / "job.json").write_text("{}")

    def unavailable(*args):
        raise ZoneInfoNotFoundError("synthetic missing timezone")

    monkeypatch.setattr(worker, "ZoneInfo", unavailable)
    monkeypatch.setattr(sys, "argv", ["goofish_worker", str(tmp_path / "nonexistent-engine"), str(directory)])
    worker.main()
    assert json.loads((directory / "outcome.json").read_text()) == {"error_code": "engine_timezone_missing"}
