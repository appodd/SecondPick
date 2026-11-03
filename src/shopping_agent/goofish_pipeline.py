"""Explicit collection-only extension of the supported upstream dispatcher.

Standalone-compatible: the external engine does not install shopping_agent.
"""
import asyncio
import copy
import json
import os
from datetime import datetime

if __package__:
    from .goofish_evidence import item_fields, seller_fields
else:
    from goofish_evidence import item_fields, seller_fields


ITEM_FIELDS = ("商品ID", "商品链接", "商品标题", "当前售价", "发货地区", "卖家昵称", "发布时间")
SELLER_FIELDS = ("卖家ID", "卖家昵称", "卖家芝麻信用", "卖家注册时长", "作为卖家的好评率", "卖家在售/已售商品数")


class EvidenceJournal:
    def __init__(self, path, *, image_audit=None):
        self.path = path
        self.image_audit=image_audit
        if path.exists() and path.stat().st_size:
            with path.open("rb") as stream:
                stream.seek(-1, 2)
                incomplete = stream.read(1) != b"\n"
            if incomplete:
                with path.open("ab") as stream:
                    stream.write(b"\n")

    def append(self, record, stage, *, round_id=None):
        item = record.get("商品信息") or {}
        seller = record.get("卖家信息") or {}
        item = item if isinstance(item, dict) else {}
        seller = seller if isinstance(seller, dict) else {}
        payload = {key: record.get(key) for key in ("任务名称", "搜索关键字", "爬取时间")}
        payload.update({"商品信息": {**{key: item.get(key) for key in ITEM_FIELDS}, **item_fields(item, stage)},
                        "卖家信息": {**{key: seller.get(key) for key in SELLER_FIELDS}, **seller_fields(seller, stage)},
                        "_collection_stage": stage})
        if stage == "search_card":
            payload["_source_round_id"] = round_id
        if self.image_audit:self.image_audit.output('journal_'+stage,payload['商品信息'])
        self.write(payload)

    def write(self, payload):
        data = (json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        if len(data) > 1024 * 1024:
            raise ValueError("Evidence record exceeds limit")
        with self.path.open("ab") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


def price_recorder(original, journal, round_id, on_error, *, cards_journal=None):
    """Mirror native normalized records after its SQLite save; no extra requests."""
    fields = ("keyword", "task_name", "run_id", "snapshot_time", "item_id",
              "title", "price", "price_display", "region", "seller", "link")

    seen_cards = set()

    def record(**kwargs):
        if cards_journal is not None:
            # Capture all parsed cards, including unpriced items, before native
            # price filtering or the scraper's processed-detail skip.
            kwargs["items"] = list(kwargs["items"])
            observed = kwargs.get("snapshot_time") or datetime.now().isoformat()
            try:
                for item in kwargs["items"]:
                    key = str(item.get("商品ID") or item.get("商品链接") or "")
                    if key and key in seen_cards:
                        continue
                    cards_journal.append({"任务名称": kwargs["task_name"], "搜索关键字": kwargs["keyword"],
                        "爬取时间": observed, "商品信息": item}, "search_card", round_id=round_id)
                    if key:
                        seen_cards.add(key)
            except Exception:
                on_error("engine_save_failed")
                raise
        records = original(**kwargs)
        try:
            for item in records:
                journal.write({**{key: item.get(key) for key in fields}, "round_id": round_id})
        except Exception:
            on_error("engine_save_failed")
            raise
        return records

    return record


def collection_dispatcher(base, journal, *, collect_seller_profiles=False, on_error,
                          profile_timeout=30, stats=None, detail_evidence=None):
    """Keep upstream semaphore, job copies and seller merging/cache callback.

    Raw evidence is durable before asynchronous enrichment starts. No analysis,
    image or notification callback can run in collection-only mode.
    """
    stats = stats if stats is not None else {}
    for key in ("raw_saved", "seller_records_saved", "seller_profile_failures"):
        stats.setdefault(key, 0)

    class CollectionDispatcher(base):
        def __init__(self, **kwargs):
            loader = kwargs["seller_loader"]

            async def seller_loader(key):
                if not collect_seller_profiles:
                    return {}
                try:
                    result = await asyncio.wait_for(loader(key), timeout=profile_timeout)
                    if not isinstance(result, dict):
                        raise ValueError("Invalid seller profile")
                    return result
                except Exception:
                    self.profile_failures += 1
                    stats["seller_profile_failures"] += 1
                    raise

            async def save_enriched(record, keyword):
                try:
                    journal.append(record, "seller_enriched")
                except Exception:
                    on_error("engine_save_failed")
                    raise
                stats["seller_records_saved"] += 1
                return True

            self.profile_failures = 0
            self.raw_saved_count = 0
            kwargs.update(seller_loader=seller_loader, saver=save_enriched)
            super().__init__(**kwargs)

        def submit(self, job):
            job = copy.deepcopy(job)
            if detail_evidence is not None:
                detail_evidence.enrich(job.final_record)
            try:
                raw = copy.deepcopy(job.final_record)
                # These fields already arrived with the detail response; do
                # not wait for a separate profile request to preserve them.
                raw["卖家信息"] = {"卖家芝麻信用": job.zhima_credit_text,
                                  "卖家注册时长": job.registration_duration_text}
                seller_id = str(job.seller_id or '')
                if seller_id.isascii() and seller_id.isdigit() and len(seller_id)<=50:
                    raw['卖家信息']['卖家ID'] = seller_id
                journal.append(raw, "card")
            except Exception:
                on_error("engine_save_failed")
                raise
            self.raw_saved_count += 1
            stats["raw_saved"] += 1
            previous = set(self._tasks)
            super().submit(job)
            for task in self._tasks - previous:
                task.add_done_callback(self._observe)

        def _observe(self, task):
            if not task.cancelled() and task.exception() is not None:
                on_error("engine_pipeline_failed")

        async def _build_analysis_result(self, job, record):
            return {"analysis_source": "not_run", "is_recommended": None}

        async def _load_seller_info(self, job):
            result = await super()._load_seller_info(job)
            seller_id = str(job.seller_id or '')
            if seller_id.isascii() and seller_id.isdigit() and len(seller_id)<=50:
                result['卖家ID'] = seller_id
            return result

        async def _notify_if_recommended(self, item_data, analysis_result):
            pass

        async def join(self):
            # Upstream drops completed tasks from _tasks. The done observer
            # retrieves errors even if a task finished before join was called.
            while self._tasks:
                await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    return CollectionDispatcher
