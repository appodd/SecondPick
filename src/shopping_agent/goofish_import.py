"""Read ai-goofish-monitor JSONL without importing its runtime or AI conclusions."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from shopping_agent.config import AppConfig, load_config
from shopping_agent.goofish_pipeline import SELLER_FIELDS
from shopping_agent.goofish_evidence import evidence_fields
from shopping_agent.goofish_journal import JournalBatch, MAX_LINE_BYTES
from shopping_agent.db import (
    add_listing_snapshot, attach_run_to_task, connect, create_query,
    create_search_run, initialize, upsert_listing, utc_now_iso, add_media_asset,
)

def _text(value, limit=2000):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Invalid field type")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Invalid number")
    result = str(value).strip()
    if len(result) > limit:
        raise ValueError("Field too long")
    return result or None


def _normalize(record, keyword, source_task):
    if not isinstance(record, dict):
        raise ValueError("Record must be an object")
    if record.get("搜索关键字") != keyword:
        return None
    if source_task is not None and record.get("任务名称") != source_task:
        return None
    item = record.get("商品信息")
    if not isinstance(item, dict):
        raise ValueError("Missing product")
    url = urlsplit(_text(item.get("商品链接")) or "")
    ids = parse_qs(url.query).get("id", [])
    if (url.scheme != "https" or url.hostname not in {"www.goofish.com", "goofish.com"}
            or url.port not in {None, 443} or url.username or url.password
            or url.path not in {"/item", "/item/"} or len(ids) != 1
            or not ids[0].isascii() or not ids[0].isdigit()):
        raise ValueError("Invalid product URL")
    item_id = _text(item.get("商品ID"), 100)
    if item_id is not None and item_id != ids[0]:
        raise ValueError("Product ID mismatch")
    title = _text(item.get("商品标题"))
    if not title:
        raise ValueError("Missing title")
    # Only platform/product fields are accepted. In particular ai_analysis,
    # price_insight and generated seller summaries never become evidence.
    normalized = dict(
        url=f"https://www.goofish.com/item?id={ids[0]}", title=title,
        price_text=_text(item.get("当前售价"), 100),
        location=_text(item.get("发货地区"), 200),
        seller_name=_text(item.get("卖家昵称"), 200),
        source_task=_text(record.get("任务名称"), 500),
        observed_at=_text(record.get("爬取时间"), 100), keyword=keyword,
    )
    is_search_card = record.get("_collection_stage") == "search_card"
    if is_search_card:
        round_id = _text(record.get("_source_round_id"), 100)
        if not round_id or not normalized["observed_at"]:
            raise ValueError("Missing card observation identity")
        datetime.fromisoformat(normalized["observed_at"])
        normalized.update(evidence_stage="search_card", source_round_id=round_id)
    profile = None if is_search_card else record.get("卖家信息")
    selected = {}
    if isinstance(profile, dict):
        for key in SELLER_FIELDS:
            try:
                value = _text(profile.get(key), 1000)
            except ValueError:
                continue
            if value is not None:
                selected[key] = value
    # Keep legacy card fingerprints unchanged when no profile is present.
    if selected:
        normalized["seller_profile"] = selected
    evidence = evidence_fields(item, profile if isinstance(profile, dict) else {}, record.get("_collection_stage"))
    if evidence:
        normalized["monitor_evidence"] = dict(version=1, stage=record.get("_collection_stage"), fields=evidence)
    return normalized


def import_goofish_jsonl(config: AppConfig, *, path: Path, task_id: int,
                         keyword: str, source_task: str | None = None, incremental: bool = False) -> dict:
    """Synchronize one explicitly selected result stream into an existing task.

    Re-reading a growing file is idempotent per task. Observations with changed
    fields/time append snapshots. Incomplete/invalid lines are counted, never
    echoed; a later read can import a completed tail. No network/model calls.
    Incremental mode defers incomplete tails and commits a bounded batch and
    its cursor together; manual imports retain full-file compatibility.
    """
    if not keyword.strip() or len(keyword) > 120:
        raise ValueError("keyword must contain 1..120 characters")
    initialize(config.database_path, timeout=.25 if incremental else 5.0)
    from shopping_agent.auto_covers import AutoCovers
    covers=AutoCovers(config)
    try:covers.activate()  # Capture the historical boundary BEFORE this import. No network.
    except (OSError,ValueError,RuntimeError):covers=None  # Cache metadata failure must not block ingestion.
    cover_listings=[]
    counts = dict(imported=0, duplicates=0, invalid=0, out_of_scope=0, run_id=None)
    with path.open("rb") as stream, connect(config.database_path, timeout=.25 if incremental else 5.0) as conn:
        conn.execute("BEGIN IMMEDIATE")
        task = conn.execute("SELECT goal,city FROM research_tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise ValueError("Research task not found")
        batch = JournalBatch(conn, stream, task_id=task_id, path=path, keyword=keyword,
                             source_task=source_task, kind="products", incremental=incremental)
        for line in batch:
            if len(line) > MAX_LINE_BYTES:
                counts["invalid"] += 1
                continue
            if not line.strip():
                continue
            try:
                record = _normalize(json.loads(line.decode("utf-8-sig")), keyword, source_task)
            except (ValueError, TypeError, RecursionError):
                counts["invalid"] += 1
                continue
            if record is None:
                counts["out_of_scope"] += 1
                continue
            fingerprint = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if conn.execute("SELECT 1 FROM monitor_import_records WHERE task_id=? AND fingerprint=?",
                            (task_id, fingerprint)).fetchone():
                counts["duplicates"] += 1
                continue
            if counts["run_id"] is None:
                counts["run_id"] = create_search_run(conn, task["goal"], task["city"])
                attach_run_to_task(conn, task_id, counts["run_id"], role="monitor_import",
                                   notes="ai-goofish-monitor JSONL；导入时间不等于源采集时间")
                create_query(conn, counts["run_id"], "xianyu", keyword)
            listing_id = upsert_listing(conn, "xianyu", record["url"])
            snapshot_id = add_listing_snapshot(
                conn, listing_id, counts["run_id"], title=record["title"],
                price_text=record["price_text"], location=record["location"],
                seller_name=record["seller_name"], source_type="external_monitor",
                source_label=("ai-goofish-monitor 搜索卡片（未抓取详情，非独立核验）"
                    if record.get("evidence_stage") == "search_card" else
                    "ai-goofish-monitor 导入（平台/卖家信息，非独立核验）"),
            )
            conn.execute("""INSERT INTO monitor_import_records
                (task_id,fingerprint,snapshot_id,source,source_task,observed_at,imported_at,seller_json,evidence_stage,source_round_id,evidence_json)
                VALUES(?,?,?,'ai-goofish-monitor',?,?,?,?,?,?,?)""",
                (task_id, fingerprint, snapshot_id, record["source_task"], record["observed_at"], utc_now_iso(),
                 json.dumps(record.get("seller_profile", {}), ensure_ascii=False),
                 record.get("evidence_stage", "product_record"), record.get("source_round_id"),
                 json.dumps(record.get("monitor_evidence", {}), ensure_ascii=False)))
            # URL persistence only: never fetch bytes, invoke OCR or call an AI here.
            for group in record.get('monitor_evidence',{}).get('fields',{}).values():
                urls=list(group.get('商品图片列表',[]))
                if group.get('商品主图链接'):urls.insert(0,group['商品主图链接'])
                for url in dict.fromkeys(urls):add_media_asset(conn,listing_id,'product_image_url',url,'')
            cover_listings.append(listing_id)
            counts["imported"] += 1
        counts.update(batch.save())
    try:
        if covers is not None:covers.admit(task_id,cover_listings)  # Commit completed; enqueue only, never download here.
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Cover enqueue deferred; imported products retained")
    return counts


def main():
    parser = argparse.ArgumentParser(description="将 ai-goofish-monitor JSONL 同步到已有研究任务（不访问平台、不调用模型）")
    parser.add_argument("path", type=Path)
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--keyword", required=True, help="精确匹配源文件的搜索关键字")
    parser.add_argument("--source-task", help="可选：精确匹配源任务名称")
    parser.add_argument("--config", type=Path, default=Path("config/default.toml"))
    args = parser.parse_args()
    try:
        result = import_goofish_jsonl(load_config(args.config), path=args.path,
                                      task_id=args.task_id, keyword=args.keyword, source_task=args.source_task)
    except (OSError, ValueError) as exc:
        # Paths and raw records may be sensitive; do not echo them on failure.
        parser.exit(1, f"导入失败：{type(exc).__name__}；请检查文件、配置与任务编号。\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
