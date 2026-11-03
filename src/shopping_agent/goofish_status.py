"""Standalone-safe worker status: fixed fields and enums, never raw logs."""
import json
import re

PHASES = {"bootstrap", "timezone_check", "engine_import", "collecting", "completed"}
ERROR_CODES = {"login_required", "verification_required", "engine_failed", "engine_dependencies_missing",
               "engine_save_failed", "engine_paused", "engine_timezone_missing", "engine_pipeline_failed", "engine_version_unsupported"}


class WorkerStatus:
    def __init__(self, directory):
        self.directory, self.phase, self.round_id = directory, "bootstrap", None
        self.error_code = None

    def update(self, phase, error_code=None):
        if phase not in PHASES or error_code is not None and error_code not in ERROR_CODES:
            raise ValueError("Invalid worker status")
        if self.round_id is not None and (not isinstance(self.round_id, str) or not re.fullmatch(r"[0-9a-f]{32}", self.round_id)):
            raise ValueError("Invalid worker round")
        self.phase = phase
        self.error_code = error_code
        payload = dict(phase=phase, error_code=error_code, round_id=self.round_id)
        pending = self.directory / "status.tmp"
        pending.write_text(json.dumps(payload), encoding="utf-8")
        pending.replace(self.directory / "status.json")


def read_worker_status(directory, round_id):
    try:
        with (directory / "status.json").open("rb") as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            return None
        row = json.loads(data)
        if (not isinstance(row, dict) or row.get("phase") not in PHASES
                or row.get("round_id") != round_id or not re.fullmatch(r"[0-9a-f]{32}", round_id)
                or row.get("error_code") is not None and row["error_code"] not in ERROR_CODES):
            return None
        return dict(phase=row["phase"], error_code=row.get("error_code"))
    except (OSError, ValueError, TypeError, RecursionError):
        return None
