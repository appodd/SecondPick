"""One local service owns recovery and scheduling for a database."""
import os

_retained = set()


class ServiceLease:
    def __init__(self, database_path):
        path = database_path.resolve()
        self.path = path.with_name(path.name + ".service.lock")
        self.stream = None

    def __enter__(self):
        if self.stream is not None:
            raise RuntimeError("本地服务锁已持有。")
        stream = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            stream = self.path.open("a+b")
            if stream.seek(0, 2) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if stream is not None:
                stream.close()
            raise RuntimeError("此数据库的本地服务锁不可用；请先关闭已运行的服务并检查目录权限。") from None
        self.stream = stream
        return self

    def retain_until_exit(self):
        # Failed shutdown must not let another service recover still-live work.
        _retained.add(self)

    def release(self):
        if self.stream is not None:
            self.stream.close()  # The OS releases the lock, including on crash.
            self.stream = None
        _retained.discard(self)

    def __exit__(self, *args):
        if self not in _retained:
            self.release()
