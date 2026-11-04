"""Bounded, cancellable external-engine process; no browser opens at import/startup."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
import threading
import sqlite3

from shopping_agent.goofish_import import import_goofish_jsonl
from shopping_agent.goofish_prices import import_price_observations
from shopping_agent.db import connect, utc_now_iso
from shopping_agent.goofish_status import read_worker_status
from shopping_agent.monitor_diagnostics import MonitorDiagnostics, retention_status
from shopping_agent.browser.monitor_auth import load_monitor_login
from shopping_agent.goofish_browser import CredentialError, collection_environment
from shopping_agent.monitor_logs import ConsoleLog

SUPPORTED_REVISION = "f85d140b6b45029d9a0925feb96dad733b41396d"
ERRORS = {"login_required", "verification_required", "engine_failed", "engine_dependencies_missing", "engine_save_failed",
          "engine_paused", "engine_timezone_missing", "engine_pipeline_failed", "engine_sync_failed", "engine_version_unsupported"}


class EngineError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def windows_job(process):
    """Kill all engine descendants if the owning web process exits or crashes."""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                    ("max_working_set", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]

    class IOCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", IOCounters),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise OSError("Engine process ownership could not be established")
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle, int(process._handle)):
        kernel.CloseHandle(handle)
        raise OSError("Engine process ownership could not be established")
    return lambda: kernel.CloseHandle(handle)


def terminate_tree(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


def run_process(command, *, cwd, env, stop, timeout, on_tick=None, input_data=None, output_log=None):
    if stop.is_set():
        raise EngineError("cancelled")
    kwargs = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
              else {"start_new_session": True})
    with subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                          stdout=subprocess.PIPE if output_log else subprocess.DEVNULL,
                          stderr=subprocess.STDOUT if output_log else subprocess.DEVNULL, bufsize=0, **kwargs) as process:
        started = time.monotonic()
        next_tick = started
        close_job = None
        writer = None
        reader = None
        try:
            if os.name == "nt":
                close_job = windows_job(process)
            if output_log:
                reader = threading.Thread(target=output_log.drain, args=(process.stdout,), daemon=True, name="monitor-console")
                reader.start()
            if input_data is not None:
                def write_input():
                    try:
                        process.stdin.write(input_data)
                        process.stdin.close()
                    except (OSError, ValueError):
                        pass  # The outcome/status channel reports fixed errors.
                writer = threading.Thread(target=write_input, daemon=True, name="monitor-credentials")
                writer.start()
            while process.poll() is None:
                if stop.wait(.1):
                    raise EngineError("cancelled")
                if time.monotonic() - started >= timeout:
                    raise EngineError("engine_timeout")
                if on_tick is not None and time.monotonic() >= next_tick:
                    on_tick()
                    next_tick = time.monotonic() + 1
            if process.returncode:
                raise EngineError("engine_failed")
        finally:
            try:
                terminate_tree(process)
            finally:
                if close_job:
                    close_job()
                if writer:
                    writer.join(timeout=2)
                if reader:
                    reader.join(timeout=2)


class GoofishEngine:
    def __init__(self, config):
        self.config = config

    def preflight(self):
        cfg = self.config.monitor_engine
        if not cfg.enabled or cfg.root is None:
            raise EngineError("engine_not_configured")
        if cfg.state_file is not None and not cfg.state_file.is_file():
            raise EngineError("login_required")
        root = cfg.root.resolve()
        try:
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                      capture_output=True, text=True, timeout=10, **kwargs)
            clean = subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", "src"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, **kwargs)
        except (OSError, subprocess.SubprocessError):
            raise EngineError("engine_version_unsupported") from None
        if revision.returncode or revision.stdout.strip() != SUPPORTED_REVISION or clean.returncode:
            raise EngineError("engine_version_unsupported")
        return root

    def run(self, monitor, stop):
        round_id = uuid.uuid4().hex
        diagnostics = MonitorDiagnostics(self.config, monitor, round_id) if "task_id" in monitor else None
        try:
            root = self.preflight()
            credential_payload, credential_mtime, shared_login = load_monitor_login(self.config)
        except CredentialError:
            if diagnostics is not None:
                diagnostics.emit("preflight", "login_required")
            raise EngineError("login_required") from None
        except EngineError as exc:
            if diagnostics is not None:
                diagnostics.emit("preflight", exc.code)
            raise
        cfg = self.config.monitor_engine
        database_key = hashlib.sha256(str(self.config.database_path.resolve()).encode()).hexdigest()[:16]
        directory = cfg.work_dir.resolve() / database_key / f"monitor-{monitor['id']}"
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / "session.marker"
        if marker.is_symlink() or marker.exists() and marker.stat().st_size != 2:
            raise EngineError("engine_failed")
        if marker.exists() and marker.read_bytes() != b"{}":
            raise EngineError("engine_failed")
        if not marker.exists():
            with marker.open("xb") as stream:
                stream.write(b"{}")
        os.utime(marker, (credential_mtime, credential_mtime))
        source_task = f"shopping-monitor-{monitor['id']}"
        (directory / "job.json").write_text(json.dumps(dict(
            source_task=source_task, round_id=round_id, keyword=monitor["keyword"], max_pages=monitor["max_pages"],
            max_items=monitor["max_items"], state_file=str(marker), credential_transport="stdin",
            collect_seller_profiles=monitor.get("collect_seller_profiles") is True,
            browser_channel=cfg.browser_channel),
            ensure_ascii=False), encoding="utf-8")
        outcome = directory / "outcome.json"
        outcome.unlink(missing_ok=True)
        (directory / "status.json").unlink(missing_ok=True)
        diagnostics.emit("process", "round_started")
        env = collection_environment()
        error = None
        guard_state = None
        collection_stats = None
        totals = {name: dict(imported=0, duplicates=0, invalid=0, out_of_scope=0,
                            run_id=None, bytes_read=0, has_more=False, pending_tail=False)
                  for name in ("products", "cards", "prices")}
        failed_streams = set()
        pool_count = 0
        worker_status = None
        retention = retention_status(directory)
        last_progress = None
        retention_warned = False

        def counts():
            return dict(imported=totals["products"]["imported"], search_cards=totals["cards"]["imported"],
                        price_observations=totals["prices"]["imported"], candidate_pool_count=pool_count,
                        invalid=sum(t["invalid"] for t in totals.values()))

        def result():
            return {**totals["products"], "search_cards": dict(totals["cards"]),
                    "price_observations": dict(totals["prices"]), "candidate_pool_count": pool_count,
                    "sync_pending": bool(failed_streams) or any(t["has_more"] or t["pending_tail"] for t in totals.values()),
                    "error_code": error or ("engine_sync_failed" if failed_streams else None),
                    "scheduler_owner": "shopping_agent", "diagnostics_available": diagnostics.available,
                    "retention": dict(retention),
                    **({"worker_status": dict(worker_status)} if worker_status else {}),
                    **({"sync_failed_streams": sorted(failed_streams)} if failed_streams else {}),
                    **({"failure_guard": guard_state} if guard_state is not None else {}),
                    **({"collection": collection_stats} if collection_stats is not None else {})}

        def sync():
            nonlocal pool_count, worker_status, retention, last_progress, retention_warned
            observed = read_worker_status(directory, round_id)
            if observed and observed != worker_status:
                worker_status = observed
                diagnostics.emit("process", "worker_" + observed["phase"])
            for name in totals:
                path = directory / f"{name}.jsonl"
                if not path.exists():
                    continue
                importer = import_price_observations if name == "prices" else import_goofish_jsonl
                try:
                    batch = importer(self.config, path=path, task_id=monitor["task_id"],
                        keyword=monitor["keyword"], source_task=source_task, incremental=True)
                    for key in ("imported", "duplicates", "invalid", "out_of_scope", "bytes_read"):
                        totals[name][key] += batch[key]
                    if batch["run_id"] is not None:
                        totals[name]["run_id"] = batch["run_id"]
                    for key in ("has_more", "pending_tail"):
                        totals[name][key] = batch[key]
                    failed_streams.discard(name)
                except Exception:
                    # Each import/checkpoint transaction rolls back independently.
                    # Still import other streams and never publish raw exceptions.
                    failed_streams.add(name)
            try:
                retention = retention_status(directory)
                if retention["warning"] and not retention_warned:
                    diagnostics.emit("retention", "evidence_retained", evidence_bytes=retention["evidence_bytes"])
                    retention_warned = True
                with connect(self.config.database_path, timeout=.25) as conn:
                    pool_count = conn.execute("""SELECT COUNT(DISTINCT ls.listing_id) FROM listing_snapshots ls
                        JOIN task_runs tr ON tr.run_id=ls.run_id WHERE tr.task_id=?""", (monitor["task_id"],)).fetchone()[0]
                    conn.execute("""UPDATE monitors SET result_json=?,updated_at=?
                        WHERE id=? AND task_id=? AND state='running'""",
                        (json.dumps(result()), utc_now_iso(), monitor["id"], monitor["task_id"]))
            except Exception:
                diagnostics.emit("sync", "engine_sync_failed", **counts())
                raise EngineError("engine_sync_failed") from None
            if failed_streams:
                diagnostics.emit("sync", "engine_sync_failed", **counts())
                raise EngineError("engine_sync_failed")
            progress = counts()
            if progress != last_progress:
                diagnostics.emit("sync", "sync_progress", **progress)
                last_progress = progress
            return any(t["has_more"] for t in totals.values())

        console = None
        if cfg.capture_logs:
            values = [c.get("value", "") for c in json.loads(credential_payload).get("cookies", [])]
            secrets = [part for value in values for part in [value, *value.splitlines()] if len(part) >= 6]
            console = ConsoleLog(directory / "logs", round_id, secrets=secrets)
            console.write("[monitor] round started; AI analysis and notifications disabled")
        try:
            run_process([str(cfg.python.resolve()) if cfg.python else sys.executable,
                         str(Path(__file__).with_name("goofish_worker.py").resolve()), str(root), str(directory)],
                        cwd=directory, env=env, stop=stop, timeout=cfg.timeout_seconds, on_tick=sync,
                        input_data=credential_payload, output_log=console)
            with outcome.open("rb") as stream:
                payload = stream.read(4097)
            if len(payload) > 4096:
                raise ValueError("Invalid worker outcome")
            data = json.loads(payload)
            if not isinstance(data, dict) or "error_code" not in data:
                raise ValueError("Invalid worker outcome")
            if data.get("error_code"):
                error = data["error_code"] if data["error_code"] in ERRORS else "engine_failed"
            state = data.get("failure_guard")
            if isinstance(state, dict) and type(state.get("consecutive_failures")) is int and 0 <= state["consecutive_failures"] <= 2**31:
                from datetime import datetime
                paused = state.get("paused_until")
                if paused is not None:
                    datetime.fromisoformat(paused)
                guard_state = {"consecutive_failures": state["consecutive_failures"], "paused_until": paused}
            stats = data.get("collection")
            keys = ("raw_saved", "seller_records_saved", "seller_profile_failures")
            if isinstance(stats, dict) and all(type(stats.get(k)) is int and 0 <= stats[k] <= 2**31 for k in keys):
                collection_stats = {k: stats[k] for k in keys}
        except EngineError as exc:
            error = exc.code
        except (OSError, ValueError, TypeError, RecursionError):
            error = "engine_failed"
        finally:
            if console:
                console.write(f"[monitor] process exited; result={error or 'completed'}")
                console.close()
        # The process tree has exited before this bounded final drain. Leave
        # large backlogs/fragments on disk with durable checkpoints for resume.
        deadline = time.monotonic() + 5
        for _ in range(8):
            try:
                more = sync()
            except EngineError:
                error = error or "engine_sync_failed"
                break
            if not more or time.monotonic() >= deadline:
                break
        if error:
            diagnostics.emit("finished", error, **counts())
        if result()["sync_pending"]:
            diagnostics.emit("sync", "sync_pending", **counts())
        diagnostics.emit("finished", "round_finished", **counts())
        if shared_login and error in {"login_required", "verification_required"}:
            try:
                with connect(self.config.database_path, timeout=.25) as conn:
                    conn.execute("UPDATE browser_auth SET state='invalid' WHERE id=1")
            except sqlite3.Error:
                error = "engine_sync_failed"
                diagnostics.emit("finished", "engine_sync_failed", **counts())
        return result()
