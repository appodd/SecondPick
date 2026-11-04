import os
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from shopping_agent.service_lease import ServiceLease


def test_second_owner_blocked_and_separate_database_allowed(tmp_path):
    path = tmp_path / "db.sqlite"
    with ServiceLease(path):
        with pytest.raises(RuntimeError, match="服务锁"):
            with ServiceLease(path):
                pytest.fail("Second owner acquired")
        with ServiceLease(tmp_path / "other.sqlite"):
            pass
    with ServiceLease(path):
        pass
    assert path.with_name(path.name + ".service.lock").exists()  # Never unlink a live-lock inode.


def test_shutdown_failure_keeps_owner_until_explicit_release(tmp_path):
    path = tmp_path / "db.sqlite"
    lease = ServiceLease(path)
    with pytest.raises(RuntimeError, match="shutdown"):
        with lease:
            lease.retain_until_exit()
            raise RuntimeError("shutdown failed")
    try:
        with pytest.raises(RuntimeError, match="服务锁"):
            with ServiceLease(path):
                pass
    finally:
        lease.release()  # No worker exists in this isolated test.
    with ServiceLease(path):
        pass


def test_real_process_crash_releases_ownership_without_removing_lock_file(tmp_path):
    path, ready = tmp_path / "db.sqlite", tmp_path / "ready"
    script = ("from pathlib import Path; import time; from shopping_agent.service_lease import ServiceLease; "
              "lease=ServiceLease(Path(" + repr(str(path)) + ")); lease.__enter__(); "
              "import os,json; staged=Path(" + repr(str(ready) + '.tmp') + "); "
              "staged.write_text(json.dumps({'owner_pid':os.getpid()})); staged.replace(Path(" + repr(str(ready)) + ")); time.sleep(30)")
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert ready.exists()
        owner_pid = json.loads(ready.read_text())["owner_pid"]
        with pytest.raises(RuntimeError, match="服务锁"):
            with ServiceLease(path):
                pass
        # A Windows venv python.exe can be a redirector: waiting for that PID
        # does not prove the Python process holding the OS lock has exited.
        # Terminate and synchronously wait for the PID reported by the holder.
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x00100000 | 0x0001, False, owner_pid)
            assert handle, (owner_pid, process.pid, ctypes.get_last_error())
            try:
                assert kernel.TerminateProcess(handle, 1)
                assert kernel.WaitForSingleObject(handle, 5000) == 0
            finally:
                kernel.CloseHandle(handle)
        else:
            assert owner_pid == process.pid
            process.kill()
        process.wait(timeout=5)
        with ServiceLease(path):
            pass
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
