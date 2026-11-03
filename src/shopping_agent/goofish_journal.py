"""Transactional, bounded readers for append-only monitor evidence journals."""
import hashlib
import json
import os

from shopping_agent.db import utc_now_iso

MAX_LINE_BYTES = 1024 * 1024
MAX_BATCH_BYTES = 4 * MAX_LINE_BYTES
MAX_BATCH_LINES = 500


class JournalBatch:
    def __init__(self, conn, stream, *, task_id, path, keyword, source_task, kind, incremental=False):
        self.conn, self.stream, self.task_id = conn, stream, task_id
        self.incremental = incremental
        self.key = hashlib.sha256(json.dumps([str(path.resolve()), keyword, source_task, kind],
                                            ensure_ascii=False).encode()).hexdigest()
        stat = os.fstat(stream.fileno())
        self.file_id = f"{stat.st_dev}:{stat.st_ino}"
        self.end = stat.st_size  # Do not chase a writer during this transaction.
        self.offset, self.discarding, self.blocked_tail, self.bytes_read = 0, False, False, 0
        if incremental:
            row = conn.execute("SELECT * FROM monitor_stream_checkpoints WHERE task_id=? AND stream_key=?",
                               (task_id, self.key)).fetchone()
            if row and row["file_id"] == self.file_id and 0 <= row["byte_offset"] <= self.end:
                head, tail = self._hashes(row["byte_offset"])
                if head == row["head_hash"] and tail == row["tail_hash"]:
                    self.offset, self.discarding = row["byte_offset"], bool(row["discarding"])
        stream.seek(self.offset)

    def _hashes(self, offset):
        self.stream.seek(0)
        head = hashlib.sha256(self.stream.read(min(offset, 256))).hexdigest()
        self.stream.seek(max(0, offset - 256))
        tail = hashlib.sha256(self.stream.read(min(offset, 256))).hexdigest()
        return head, tail

    def __iter__(self):
        lines = 0
        while self.stream.tell() < self.end:
            if self.incremental and (self.bytes_read >= MAX_BATCH_BYTES or lines >= MAX_BATCH_LINES):
                break
            start = self.stream.tell()
            limit = 65536 if self.discarding else MAX_LINE_BYTES + 1
            line = self.stream.readline(min(limit, self.end - start))
            if not line:
                break
            self.bytes_read += len(line)
            if self.discarding:
                self.offset = self.stream.tell()
                self.discarding = not line.endswith(b"\n")
                continue
            if not line.endswith(b"\n") and len(line) <= MAX_LINE_BYTES and self.incremental:
                # The writer may finish even a syntactically valid JSON tail.
                self.blocked_tail = True
                self.stream.seek(start)
                break
            self.offset = self.stream.tell()
            self.discarding = len(line) > MAX_LINE_BYTES and not line.endswith(b"\n")
            lines += 1
            yield line

    @property
    def has_more(self):
        return self.offset < self.end and not self.blocked_tail

    def save(self):
        if not self.incremental:
            return {}
        head, tail = self._hashes(self.offset)
        self.conn.execute("""INSERT INTO monitor_stream_checkpoints
            (task_id,stream_key,file_id,byte_offset,discarding,head_hash,tail_hash,updated_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(task_id,stream_key) DO UPDATE SET
            file_id=excluded.file_id,byte_offset=excluded.byte_offset,discarding=excluded.discarding,
            head_hash=excluded.head_hash,tail_hash=excluded.tail_hash,updated_at=excluded.updated_at""",
            (self.task_id, self.key, self.file_id, self.offset, int(self.discarding), head, tail, utc_now_iso()))
        return dict(has_more=self.has_more, bytes_read=self.bytes_read,
                    pending_tail=self.blocked_tail or self.discarding)
