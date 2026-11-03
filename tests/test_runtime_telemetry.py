"""CLI event fixtures, not real-model usage or billing evidence."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shopping_agent.codex_runtime import CodexRuntime, CodexTimeoutError, InvalidCodexResult
from shopping_agent.runtime_telemetry import parse_cli_telemetry, summarize_telemetry, MAX_EVENT_BYTES
from test_codex_runtime import build_request


def events(*extra):
    return [dict(type="thread.started", thread_id="private-thread"), dict(type="turn.started"),
            dict(type="item.completed", item=dict(id="i1", type="agent_message", text="private answer")),
            *extra, dict(type="turn.completed", usage=dict(input_tokens=100, cached_input_tokens=60,
                cache_write_input_tokens=0, output_tokens=10, reasoning_output_tokens=2))]


def parse(rows, **kwargs):
    data = b"\n".join(json.dumps(row).encode() for row in rows)
    return parse_cli_telemetry(io.BytesIO(data), process_finished=True, **kwargs)


def test_allowlisted_counts_ignore_text_payloads_and_duplicate_completed_items():
    command = dict(type="item.completed", item=dict(id="tool1", type="command_execution", command="private-command",
                                                    aggregated_output="private-output", model="invented-model"))
    result = parse(events(command, command))
    assert result["tokens"]["input_tokens"] == 100
    assert result["tokens"]["cached_input_tokens"] == 60
    assert result["completed_item_types"] == {"agent_message": 1, "command_execution": 1}
    assert result["capture_status"] == "complete"
    assert result["model_identity"] is None and result["cost"] is None and result["tool_calls"] is None
    assert "private" not in json.dumps(result) and "invented-model" not in json.dumps(result)


@pytest.mark.parametrize("fault", ["bool", "negative", "huge", "malformed", "duplicate_terminal", "missing_terminal"])
def test_invalid_or_incomplete_usage_is_not_reported_as_complete_tokens(fault):
    rows = events()
    if fault in {"bool", "negative", "huge"}:
        rows[-1]["usage"]["input_tokens"] = {"bool": True, "negative": -1, "huge": 2**70}[fault]
    elif fault == "malformed":
        rows.append(["private-invalid"])
    elif fault == "duplicate_terminal":
        rows.append(rows[-1])
    else:
        rows.pop()
    assert parse(rows)["tokens"] is None


def test_oversized_and_invalid_utf8_streams_are_bounded_and_partial():
    for raw in (b"x" * (MAX_EVENT_BYTES + 50), b"\xff\n", b"[" * 2000 + b"0" + b"]" * 2000):
        result = parse_cli_telemetry(io.BytesIO(raw), process_finished=True)
        assert result["capture_status"] == "partial" and result["tokens"] is None


def test_failed_turn_keeps_no_usage_and_does_not_expose_error_text():
    result = parse([dict(type="turn.failed", error={"message": "private-failure"})])
    assert result["terminal"] == "turn.failed" and result["tokens"] is None
    assert "private" not in json.dumps(result)
    assert summarize_telemetry([dict(telemetry=result)])["tokens"] is None


@pytest.mark.parametrize("kind,payload,expected", [
    ("turn.failed", {"error": {"message": "401 Unauthorized private-token"}}, "authentication"),
    ("error", {"message": "429 Too many requests https://private.invalid"}, "rate_limit"),
    ("item.completed", {"item": {"id": "1", "type": "error", "message": "stream disconnected private-path"}}, "network"),
    ("error", {"message": "503 Service unavailable private-id"}, "service"),
])
def test_failure_categories_keep_only_allowlisted_hints(kind, payload, expected):
    result = parse([dict(type=kind, **payload)])
    assert result["failure_categories"] == [expected]
    assert "private" not in json.dumps(result)
    # Ordinary assistant/tool output must not be misinterpreted as CLI errors.
    result = parse([dict(type="item.completed", item=dict(id="1", type="agent_message", text="401 Unauthorized"))])
    assert result["failure_categories"] == []


def test_default_runtime_failure_reports_safe_diagnostics_without_usage(tmp_path, monkeypatch):
    from shopping_agent.codex_runtime import CodexExecutionError
    runtime = CodexRuntime(tmp_path)
    observed = {}
    class Process:
        pid = 123
        returncode = 1
        def communicate(self, input, timeout):
            observed["stream"].write(b'{"type":"turn.failed","error":{"message":"429 private-secret"}}\n')
            return None, None
    def popen(command, **kwargs):
        observed["stream"] = kwargs["stdout"]
        return Process()
    monkeypatch.setattr("shopping_agent.codex_runtime.subprocess.Popen", popen)
    with pytest.raises(CodexExecutionError) as error:
        runtime.run(build_request(runtime), run_id=7)
    assert error.value.diagnostics["failure_categories"] == ["rate_limit"]
    assert error.value.diagnostics["exit_code"] == 1
    assert "private" not in json.dumps(error.value.diagnostics)
    assert observed["stream"].closed and runtime.take_telemetry(7) is None


def test_summary_does_not_add_cached_tokens_to_input_or_fill_missing_calls():
    captured = parse(events())
    result = summarize_telemetry([dict(telemetry=captured), dict(telemetry=captured)])
    assert result["tokens"]["input_tokens"] == 200 and result["tokens"]["cached_input_tokens"] == 120
    assert summarize_telemetry([dict(telemetry=captured), {}])["tokens"] is None
    assert summarize_telemetry([])["tokens"] is None


@pytest.mark.parametrize("invalid_answer", [False, True])
@pytest.mark.parametrize("capture_unavailable", [False, True])
def test_runtime_captures_separately_and_consumes_metadata_per_call(tmp_path, monkeypatch, invalid_answer, capture_unavailable):
    runtime = CodexRuntime(tmp_path, capture_telemetry=True)
    observed = {}
    class Process:
        pid = 123
        returncode = 0
        def communicate(self, input, timeout):
            stream = observed["kwargs"]["stdout"]
            if stream != subprocess.DEVNULL:
                stream.write(b"\n".join(json.dumps(row).encode() for row in events()))
            command = observed["command"]
            Path(command[command.index("-o")+1]).write_text("bad JSON" if invalid_answer else
                '{"type":"answer","content":"answer","candidate_ids":[12]}', encoding="utf-8")
            return None, None
    def popen(command, **kwargs):
        observed.update(command=command, kwargs=kwargs)
        return Process()
    monkeypatch.setattr("shopping_agent.codex_runtime.subprocess.Popen", popen)
    if capture_unavailable:
        def unavailable(**kwargs):
            raise OSError("private-capture-path")
        monkeypatch.setattr("shopping_agent.codex_runtime.tempfile.TemporaryFile", unavailable)
    if invalid_answer:
        with pytest.raises(InvalidCodexResult):
            runtime.run(build_request(runtime), run_id=1)
    else:
        assert runtime.run(build_request(runtime), run_id=1).content == "answer"
    metadata = runtime.take_telemetry(1)
    if capture_unavailable:
        assert metadata == {"capture_status": "unavailable"}
    else:
        assert metadata["tokens"]["output_tokens"] == 10
    assert runtime.take_telemetry(1) is None
    assert observed["kwargs"]["stderr"] == subprocess.PIPE
    if not capture_unavailable:
        assert observed["kwargs"]["stdout"].closed


def test_instrumented_real_local_process_timeout_cleans_up_before_stream_close(tmp_path, monkeypatch):
    runtime = CodexRuntime(tmp_path, codex_bin=sys.executable, timeout_seconds=1, capture_telemetry=True)
    code = 'import sys,time; sys.stdin.read(); print(\'{"type":"turn.started"}\',flush=True); time.sleep(30)'
    monkeypatch.setattr(runtime, "build_command", lambda path: [sys.executable, "-u", "-c", code])
    with pytest.raises(CodexTimeoutError):
        runtime.run(build_request(runtime), run_id=2)
    assert runtime.take_telemetry(2)["capture_status"] == "partial"
    assert not runtime.cancel(2)
