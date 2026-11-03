"""Offline monitor used only by the temporary E2E server; no platform traffic."""
import json
import uuid

from shopping_agent.config import AppConfig
from shopping_agent.db import connect, utc_now_iso
from shopping_agent.goofish_import import import_goofish_jsonl
from shopping_agent.monitor_diagnostics import MonitorDiagnostics


class DemoMonitor:
    def __init__(self, database_path, directory):
        self.config = AppConfig(database_path=database_path)
        self.directory = directory

    def run(self, monitor, stop):
        round_id = uuid.uuid4().hex
        source = f"shopping-monitor-{monitor['id']}"
        log = MonitorDiagnostics(self.config, monitor, round_id)
        log.emit("process", "round_started")
        result = dict(imported=0, search_cards={"imported": 0}, price_observations={"imported": 0},
                      worker_status={"phase": "collecting", "error_code": None})
        for stage, count, key in (("search_card", 30, "search_cards"), ("product_record", 2, "products")):
            records = [{"搜索关键字": monitor["keyword"], "任务名称": source,
                "爬取时间": "2026-10-20T09:00:00", "_collection_stage": stage, "_source_round_id": round_id,
                "商品信息": {"商品ID": str(100000 + monitor["id"] * 100 + i),
                    "商品链接": f"https://www.goofish.com/item?id={100000 + monitor['id'] * 100 + i}",
                    "商品标题": f"离线监控手柄 {i+1}", "当前售价": "399"}} for i in range(count)]
            path = self.directory / f"{monitor['id']}-{key}.jsonl"
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
            batch = import_goofish_jsonl(self.config, path=path, task_id=monitor["task_id"],
                                        keyword=monitor["keyword"], source_task=source)
            if key == "products":
                result["imported"] = batch["imported"]
            else:
                result[key] = {"imported": batch["imported"]}
            with connect(self.config.database_path) as conn:
                conn.execute("UPDATE monitors SET result_json=?,updated_at=? WHERE id=?",
                             (json.dumps(result), utc_now_iso(), monitor["id"]))
            log.emit("sync", "sync_progress", imported=result["imported"], search_cards=result["search_cards"]["imported"])
        if "超时" in monitor["keyword"]:
            stop.wait(.8)
            result["error_code"] = "engine_timeout"
            log.emit("finished", "engine_timeout", imported=result["imported"])
        elif stop.wait(45):
            result["error_code"] = "cancelled"
            log.emit("finished", "cancelled", imported=result["imported"])
        return result
