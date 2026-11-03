import asyncio
import importlib
import json
from pathlib import Path

import pytest

from shopping_agent.goofish_pipeline import EvidenceJournal, collection_dispatcher


@pytest.fixture
def upstream(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parent / "fixtures/goofish_upstream"))
    dispatcher = importlib.import_module("src.services.item_analysis_dispatcher")
    cache = importlib.import_module("src.services.seller_profile_cache")
    return dispatcher.ItemAnalysisDispatcher, dispatcher.ItemAnalysisJob, cache.SellerProfileCache


def job(upstream, number=123, seller="same"):
    return upstream[1](keyword="NS2 Pro", task_name="monitor", decision_mode="keyword", analyze_images=True,
        prompt_text="must not analyze", keyword_rules=("手柄",), seller_id=seller,
        zhima_credit_text="优秀", registration_duration_text="来闲鱼1年", final_record={
            "任务名称": "monitor", "搜索关键字": "NS2 Pro", "爬取时间": "2026-10-20T10:00:00",
            "商品信息": {"商品ID": str(number), "商品链接": f"https://www.goofish.com/item?id={number}",
                       "商品标题": "手柄", "当前售价": "399", "secret": "must-not-store"},
            "ai_analysis": {"reason": "must-not-store"}})


def build(upstream, path, loader, *, enabled=True, timeout=30, journal=None):
    errors, stats, forbidden = [], {}, []

    async def trap(*args):
        forbidden.append(True)
        raise AssertionError("Forbidden analysis/image/notification callback")

    cls = collection_dispatcher(upstream[0], journal or EvidenceJournal(path), collect_seller_profiles=enabled,
                               on_error=errors.append, stats=stats, profile_timeout=timeout)
    dispatcher = cls(concurrency=2, skip_ai_analysis=True, seller_loader=loader,
                     ai_analyzer=trap, image_downloader=trap, notifier=trap, saver=trap)
    return dispatcher, errors, stats, forbidden


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_public_seller_id_survives_without_visiting_profile(upstream,tmp_path):
    path=tmp_path/'seller-id.jsonl'
    calls=[]
    async def loader(key):
        calls.append(key)
        return {}
    async def run():
        dispatcher,errors,_,forbidden=build(upstream,path,loader,enabled=False)
        dispatcher.submit(job(upstream,seller='123456'))
        await dispatcher.join()
        assert not calls and not errors and not forbidden
    asyncio.run(run())
    assert all(row['卖家信息']['卖家ID']=='123456' for row in rows(path))


def test_existing_detail_response_reaches_journal_through_real_dispatcher(upstream, tmp_path):
    from shopping_agent.goofish_evidence import DetailEvidenceTap
    tap = DetailEvidenceTap()
    path = tmp_path / 'detail.jsonl'
    calls = []

    async def getter(data, *keys, **kwargs):
        calls.append(keys)
        for key in keys:
            data = data.get(key, {})
        return data

    async def forbidden(*args):
        pytest.fail('No image, AI, notification or additional seller request')

    async def run():
        data = {'ret': ['SUCCESS::ok'], 'data': {'itemDO': {'itemId': '123', 'desc': 'Full description from existing response',
            'itemLabelExtList': [{'propertyText': '型号', 'text': 'NS2 Pro'}]}}}
        await tap.wrap(getter)(data, 'data', 'itemDO')
        cls = collection_dispatcher(upstream[0], EvidenceJournal(path), collect_seller_profiles=False,
                                   on_error=lambda code: pytest.fail(code), detail_evidence=tap)
        dispatcher = cls(concurrency=1, skip_ai_analysis=True, seller_loader=forbidden,
                         ai_analyzer=forbidden, image_downloader=forbidden, notifier=forbidden, saver=forbidden)
        dispatcher.submit(job(upstream))
        await dispatcher.join()
    asyncio.run(run())
    assert calls == [('data', 'itemDO')]
    assert all(r['商品信息']['商品描述'] == 'Full description from existing response' for r in rows(path))
    assert all(r['商品信息']['商品属性'] == {'型号': 'NS2 Pro'} for r in rows(path))


def test_raw_saved_before_enrichment_and_model_image_notifications_never_run(upstream, tmp_path):
    path = tmp_path / "evidence.jsonl"

    async def loader(key):
        assert rows(path)[0]["_collection_stage"] == "card"
        return {"卖家昵称": "来源卖家", "cookie": "must-not-store"}

    async def run():
        dispatcher, errors, stats, forbidden = build(upstream, path, loader)
        item = job(upstream)
        dispatcher.submit(item)
        item.final_record["商品信息"]["商品标题"] = "changed by caller"
        assert len(rows(path)) == 1
        await dispatcher.join()
        assert dispatcher.completed_count == 1
        assert not errors and not forbidden
        assert stats == dict(raw_saved=1, seller_records_saved=1, seller_profile_failures=0)

    asyncio.run(run())
    saved = rows(path)
    assert len(saved) == 2
    assert saved[-1]["商品信息"]["商品标题"] == "手柄"
    assert saved[-1]["卖家信息"]["卖家昵称"] == "来源卖家"
    assert saved[-1]["卖家信息"]["卖家注册时长"] == "来闲鱼1年"
    assert "must-not-store" not in path.read_text(encoding="utf-8")
    assert "ai_analysis" not in saved[-1]


def test_native_cache_coalesces_profiles_and_native_dispatcher_bounds_concurrency(upstream, tmp_path):
    path = tmp_path / "evidence.jsonl"
    calls, active, maximum = [], [], []

    async def run():
        cache = upstream[2]()

        async def network(key):
            calls.append(key)
            active.append(key)
            maximum.append(len(active))
            await asyncio.sleep(.02)
            active.remove(key)
            return {"卖家昵称": key}

        dispatcher, errors, _, forbidden = build(upstream, path, lambda key: cache.get_or_load(key, network))
        for number, key in enumerate(("a", "a", "b", "c", "a", "d")):
            dispatcher.submit(job(upstream, number, key))
        await dispatcher.join()
        assert len(calls) == 4 and max(maximum) == 2
        assert dispatcher.completed_count == 6
        assert not errors and not forbidden

    asyncio.run(run())


@pytest.mark.parametrize("timeout", [False, True])
def test_profile_error_or_timeout_keeps_base_evidence_and_detail_credit(upstream, tmp_path, timeout):
    path = tmp_path / "evidence.jsonl"

    async def loader(key):
        if timeout:
            await asyncio.sleep(30)
        raise RuntimeError("secret failure")

    async def run():
        dispatcher, errors, stats, forbidden = build(upstream, path, loader, timeout=.01)
        dispatcher.submit(job(upstream))
        await dispatcher.join()
        assert stats["seller_profile_failures"] == 1
        assert not errors and not forbidden

    asyncio.run(run())
    assert rows(path)[-1]["卖家信息"]["卖家芝麻信用"] == "优秀"
    assert "secret failure" not in path.read_text(encoding="utf-8")


def test_profile_permission_off_does_not_call_loader(upstream, tmp_path):
    async def denied(key):
        pytest.fail("Profile access was not authorized")

    async def run():
        dispatcher, _, stats, forbidden = build(upstream, tmp_path / "evidence", denied, enabled=False)
        dispatcher.submit(job(upstream))
        await dispatcher.join()
        assert not forbidden and stats["seller_profile_failures"] == 0

    asyncio.run(run())


def test_cancelled_enrichment_leaves_durable_card(upstream, tmp_path):
    path = tmp_path / "evidence"

    async def run():
        started = asyncio.Event()

        async def loader(key):
            started.set()
            await asyncio.sleep(30)

        dispatcher, _, _, _ = build(upstream, path, loader)
        dispatcher.submit(job(upstream))
        await started.wait()
        for task in tuple(dispatcher._tasks):
            task.cancel()
        await dispatcher.join()

    asyncio.run(run())
    assert [r["_collection_stage"] for r in rows(path)] == ["card"]
    assert rows(path)[0]["卖家信息"]["卖家芝麻信用"] == "优秀"
    assert rows(path)[0]["卖家信息"]["卖家注册时长"] == "来闲鱼1年"


def test_background_save_failure_is_observed_even_before_join(upstream, tmp_path):
    path = tmp_path / "evidence"

    class BrokenJournal(EvidenceJournal):
        def append(self, record, stage):
            if stage == "seller_enriched":
                raise OSError("private disk path")
            super().append(record, stage)

    async def loader(key):
        return {}

    async def run():
        dispatcher, errors, stats, _ = build(upstream, path, loader, journal=BrokenJournal(path))
        dispatcher.submit(job(upstream))
        await asyncio.sleep(.03)
        await dispatcher.join()
        assert "engine_save_failed" in errors and "engine_pipeline_failed" in errors
        assert stats["raw_saved"] == 1 and stats["seller_records_saved"] == 0

    asyncio.run(run())
    assert len(rows(path)) == 1
