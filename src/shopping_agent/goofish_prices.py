"""Import native search-page asking prices independently of detail snapshots."""
import json
import math
from datetime import datetime

from shopping_agent.db import (initialize, connect, create_search_run, attach_run_to_task,
                               create_query, upsert_listing, utc_now_iso)
from shopping_agent.goofish_import import MAX_LINE_BYTES, _normalize, _text
from shopping_agent.goofish_journal import JournalBatch


def import_price_observations(config, *, path, task_id, keyword, source_task, incremental=False):
    initialize(config.database_path, timeout=.25 if incremental else 5.0)
    counts = dict(imported=0, duplicates=0, invalid=0, out_of_scope=0, run_id=None)
    with path.open("rb") as stream, connect(config.database_path, timeout=.25 if incremental else 5.0) as conn:
        conn.execute("BEGIN IMMEDIATE")
        task = conn.execute("SELECT goal,city FROM research_tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise ValueError("Research task not found")
        batch = JournalBatch(conn, stream, task_id=task_id, path=path, keyword=keyword,
                             source_task=source_task, kind="prices", incremental=incremental)
        for line in batch:
            if len(line) > MAX_LINE_BYTES:
                counts["invalid"] += 1
                continue
            if not line.strip():
                continue
            try:
                raw = json.loads(line.decode("utf-8-sig"))
                if not isinstance(raw, dict):
                    raise ValueError("Invalid record")
                if raw.get("keyword") != keyword or raw.get("task_name") != source_task:
                    counts["out_of_scope"] += 1
                    continue
                item = _normalize({"搜索关键字": keyword, "任务名称": source_task,
                    "商品信息": {"商品ID": raw.get("item_id"), "商品链接": raw.get("link"),
                    "商品标题": raw.get("title"), "当前售价": raw.get("price_display")}}, keyword, source_task)
                price = raw.get("price")
                if type(price) not in (int, float) or not math.isfinite(price) or not 0 <= price <= 1e12:
                    raise ValueError("Invalid price")
                round_id = _text(raw.get("round_id"), 100)
                source_run_id = _text(raw.get("run_id"), 100)
                observed = _text(raw.get("snapshot_time"), 100)
                if not round_id or not source_run_id or not observed:
                    raise ValueError("Missing observation identity")
                datetime.fromisoformat(observed)
            except (ValueError, TypeError, RecursionError, OverflowError):
                counts["invalid"] += 1
                continue
            existing = conn.execute("SELECT id FROM listings WHERE platform='xianyu' AND url=?",
                                    (item["url"],)).fetchone()
            listing_id = existing["id"] if existing else upsert_listing(conn, "xianyu", item["url"])
            if conn.execute("""SELECT 1 FROM monitor_price_observations
                WHERE task_id=? AND source_task=? AND round_id=? AND listing_id=?""",
                (task_id, source_task, round_id, listing_id)).fetchone():
                counts["duplicates"] += 1
                continue
            if existing:
                upsert_listing(conn, "xianyu", item["url"])
            if counts["run_id"] is None:
                counts["run_id"] = create_search_run(conn, task["goal"], task["city"])
                attach_run_to_task(conn, task_id, counts["run_id"], role="monitor_prices",
                    notes="搜索页挂牌报价观察；非成交价，源时间未推断时区")
                create_query(conn, counts["run_id"], "xianyu", keyword)
            conn.execute("""INSERT INTO monitor_price_observations
                (task_id,run_id,listing_id,source_task,round_id,source_run_id,observed_at,imported_at,price,price_text)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (task_id, counts["run_id"], listing_id, source_task,
                round_id, source_run_id, observed, utc_now_iso(), price, item["price_text"]))
            counts["imported"] += 1
        counts.update(batch.save())
    return counts


def candidate_price_history(conn, listing_id, run_ids):
    """Bounded history in import order; source timestamps retain original timezone semantics."""
    if not run_ids:
        return []
    marks = ",".join("?" for _ in run_ids)
    rows = conn.execute(f"""SELECT id,round_id,source_run_id,observed_at,imported_at,price,price_text
        FROM monitor_price_observations WHERE listing_id=? AND run_id IN ({marks})
        ORDER BY id DESC LIMIT 20""", (listing_id, *run_ids)).fetchall()
    return [dict(row) for row in rows]
