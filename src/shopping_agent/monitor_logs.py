"""Bounded local developer console. Only filtered text crosses the API."""
import codecs
from datetime import datetime, timezone
import hashlib
import json
import re

from shopping_agent.db import connect, utc_now_iso

MAX_BYTES = 4 * 1024 * 1024
MAX_ROUNDS = 5
MAX_LINE = 8192
ROUND = re.compile(r"[0-9a-f]{32}")
ANSI = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")
SECRET_LINE = re.compile(r"(?i)(?:cookie|authorization|bearer|password|passwd|secret|api[_-]?key|token|access[_-]?token|refresh[_-]?token|session(?:_?id)?|_m_h5_tk|x[_-]?token)\s*[\"']?\s*[:=]")
URL = re.compile(r"https?://[^\s<>\"']+")


def monitor_directory(config, monitor_id):
    key = hashlib.sha256(str(config.database_path.resolve()).encode()).hexdigest()[:16]
    return config.monitor_engine.work_dir.resolve() / key / f"monitor-{monitor_id}"


def scrub(line, secrets=()):
    line = ANSI.sub("", line)
    line = "".join(c for c in line if c == "\t" or ord(c) >= 32)
    if SECRET_LINE.search(line) or re.search(r"(?i)\bbearer\s+\S+", line):
        return "[credential-bearing output omitted]"
    for secret in secrets:
        if secret:
            line = line.replace(secret, "[REDACTED]")
    def url(match):
        value = match.group(0)
        # Preserve host/path useful for debugging, omit userinfo and all query
        # parameters/fragments rather than guessing which are credentials.
        value = re.sub(r"^(https?://)[^/@]+@", r"\1[REDACTED]@", value)
        return re.split(r"[?#]", value, maxsplit=1)[0] + ("?[REDACTED]" if "?" in value or "#" in value else "")
    line = URL.sub(url, line)
    return re.sub(r"\b1[3-9]\d{9}\b", "[PHONE]", line)


class ConsoleLog:
    def __init__(self, directory, round_id, *, secrets=(), max_bytes=MAX_BYTES):
        self.available, self.stream, self.size, self.capped = False, None, 0, False
        self.secrets = sorted(set(secrets), key=len, reverse=True)
        self.max_bytes = max_bytes
        self.round_id = round_id
        try:
            if not ROUND.fullmatch(round_id) or directory.is_symlink():
                return
            directory.mkdir(parents=True, exist_ok=True)
            resolved = directory.resolve()
            files = sorted((p for p in directory.glob("*.jsonl") if ROUND.fullmatch(p.stem)
                            and not p.is_symlink() and p.resolve().parent == resolved), key=lambda p: p.stat().st_mtime)
            for path in files[:max(0, len(files) - MAX_ROUNDS + 1)]:
                path.unlink()  # Log files only; never evidence/credentials.
            self.stream = (directory / f"{round_id}.jsonl").open("x", encoding="utf-8", newline="\n")
            self.available = True
        except OSError:
            pass

    def write(self, line):
        if not self.available or self.capped or not self.stream:
            return
        try:
            line = scrub(line, self.secrets) if len(line) <= MAX_LINE else "[oversized output line omitted]"
            row = json.dumps(dict(at=utc_now_iso(), text=line), ensure_ascii=False) + "\n"
            if self.size + len(row.encode("utf-8")) > self.max_bytes:
                row = json.dumps(dict(at=utc_now_iso(), text="[log size limit reached; collection continues]")) + "\n"
                self.capped = True
            self.stream.write(row)
            self.stream.flush()
            self.size += len(row.encode("utf-8"))
        except (OSError, ValueError):
            self.available = False

    def drain(self, pipe):
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        pending, oversized, trailing_cr = "", False, False
        try:
            while True:
                chunk = pipe.read(4096)
                text = ("\r" if trailing_cr else "") + decoder.decode(chunk, final=not chunk)
                trailing_cr = bool(chunk and text.endswith("\r"))
                if trailing_cr:
                    text = text[:-1]
                text = text.replace("\r\n", "\n").replace("\r", "\n")
                parts = text.split("\n")
                for index, part in enumerate(parts):
                    if not oversized:
                        if len(pending) + len(part) > MAX_LINE:
                            pending, oversized = "", True
                        else:
                            pending += part
                    if index < len(parts) - 1:
                        self.write("[oversized output line omitted]" if oversized else pending)
                        pending, oversized = "", False
                if not chunk:
                    if pending or oversized:
                        self.write("[oversized output line omitted]" if oversized else pending)
                    return
        except (OSError, ValueError):
            self.available = False

    def close(self):
        if self.stream:
            stream, self.stream = self.stream, None
            try:
                stream.close()
            except OSError:
                self.available = False


def read_console(config, task_id, monitor_id, *, round_id=None, before=None, limit=100):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Invalid log page size")
    if round_id is not None and not ROUND.fullmatch(round_id) or before is not None and before < 0:
        raise ValueError("Invalid log cursor")
    with connect(config.database_path) as conn:
        if not conn.execute("SELECT 1 FROM monitors WHERE task_id=? AND id=?", (task_id, monitor_id)).fetchone():
            raise ValueError("监控不属于当前任务。")
    directory = monitor_directory(config, monitor_id) / "logs"
    try:
        files = [] if directory.is_symlink() else sorted((p for p in directory.glob("*.jsonl")
            if ROUND.fullmatch(p.stem) and not p.is_symlink() and p.resolve().parent == directory.resolve()),
            key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_ROUNDS]
    except OSError:
        files = []
    rounds = []
    for path in files:
        try:
            rounds.append(dict(id=path.stem, updated_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()))
        except OSError:
            continue  # A new round may rotate an old log during this read.
    selected = next((p for p in files if p.stem == round_id), None) if round_id else next(iter(files), None)
    result = dict(items=[], rounds=rounds, round_id=selected.stem if selected else None, next_before=None,
                  has_more=False, capture_enabled=config.monitor_engine.capture_logs,
                  max_bytes=MAX_BYTES, max_rounds=MAX_ROUNDS)
    if selected is None:
        return result
    try:
        with selected.open("rb") as stream:
            size = selected.stat().st_size
            end = min(size, before) if before is not None else size
            start = max(0, end - 256 * 1024)
            stream.seek(start)
            data = stream.read(end - start)
    except OSError:
        return {**result, "read_error": True}
    offset, rows = start, []
    for index, line in enumerate(data.splitlines(keepends=True)):
        position, offset = offset, offset + len(line)
        if start and index == 0 or not line.endswith(b"\n") or len(line) > 4 * MAX_LINE + 256:
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("text"), str) or not isinstance(row.get("at"), str):
                continue
            rows.append((position, dict(at=row["at"], text=scrub(row["text"]))))
        except (ValueError, TypeError, RecursionError):
            continue
    rows = rows[-limit:]
    result.update(items=[r for _, r in rows], has_more=bool(rows and rows[0][0] > 0),
                  next_before=rows[0][0] if rows and rows[0][0] > 0 else None)
    return result
