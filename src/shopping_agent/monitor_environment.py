"""Explicit on-demand environment checks, separate from login and scheduling."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading

from shopping_agent.config import AppConfig, MonitorEngineConfig
from shopping_agent.db import utc_now_iso
from shopping_agent.monitor_engine import GoofishEngine, EngineError, run_process
from shopping_agent.goofish_browser import collection_environment

CHECKS = {"configuration", "source", "revision", "python", "dependencies", "control_flow", "browser", "probe"}


def check_monitor_environment(config):
    checks = []
    def result():
        return dict(ready=bool(checks) and all(c["ok"] for c in checks), checks=checks, checked_at=utc_now_iso())
    cfg = config.monitor_engine
    checks.append(dict(code="configuration", ok=cfg.root is not None and cfg.python is not None))
    if not checks[-1]["ok"]:
        return result()
    checks.append(dict(code="source", ok=cfg.root.is_dir()))
    if not checks[-1]["ok"]:
        return result()
    try:
        probe_config = config.model_copy(update={"monitor_engine": cfg.model_copy(update={"enabled": True, "state_file": None})})
        root = GoofishEngine(probe_config).preflight()
        checks.append(dict(code="revision", ok=True))
    except EngineError:
        checks.append(dict(code="revision", ok=False))
        return result()
    checks.append(dict(code="python", ok=cfg.python.is_file()))
    if not checks[-1]["ok"]:
        return result()
    env = collection_environment()
    try:
        with tempfile.TemporaryDirectory(prefix="shopping-monitor-check-") as directory:
            output = Path(directory) / "result.json"
            command = [str(cfg.python.resolve()), "-X", "utf8", str(Path(__file__).with_name("monitor_probe.py")), str(root), str(output)]
            if cfg.browser_channel is not None:
                command.append(cfg.browser_channel)
            run_process(command, cwd=directory, env=env, stop=threading.Event(), timeout=45)
            if output.is_file():
                with output.open("rb") as stream:
                    raw = stream.read(4097)
            else:
                raw = b""
            rows = json.loads(raw) if len(raw) <= 4096 else None
            if not isinstance(rows, list) or not 1 <= len(rows) <= 3:
                raise ValueError()
            expected = ["dependencies", "control_flow", "browser"]
            for i, row in enumerate(rows):
                if not isinstance(row, dict) or row.get("code") != expected[i] or type(row.get("ok")) is not bool:
                    raise ValueError()
            if any(not row["ok"] for row in rows[:-1]) or len(rows) < 3 and rows[-1]["ok"]:
                raise ValueError()
            checks.extend(dict(code=row["code"], ok=row["ok"]) for row in rows)
    except (OSError, ValueError, RecursionError, EngineError):
        checks.append(dict(code="probe", ok=False))
    return result()


def main():
    parser = argparse.ArgumentParser(description="Check isolated monitoring runtime without platform access")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    args = parser.parse_args()
    config = AppConfig(monitor_engine=MonitorEngineConfig(root=args.root, python=args.python))
    result = check_monitor_environment(config)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
