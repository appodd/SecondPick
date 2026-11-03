import os
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
              "Path(" + repr(str(ready)) + ").write_text('ready'); time.sleep(30)")
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert ready.exists()
        with pytest.raises(RuntimeError, match="服务锁"):
            with ServiceLease(path):
                pass
        process.kill()
        process.wait(timeout=5)
        with ServiceLease(path):
            pass
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
