from __future__ import annotations

import json
import signal
import subprocess
import threading
from pathlib import Path

import pytest

from shopping_agent.config import AppConfig
from shopping_agent.codex_runtime import (
    RESULT_SCHEMA_JSON,
    ActionRequestResult,
    AnswerResult,
    CodexCancelledError,
    CodexCleanupError,
    CodexExecutionError,
    CodexRequest,
    CodexRuntime,
    CodexTimeoutError,
    InvalidCodexResult,
)
from shopping_agent.user_settings import UserSettings


@pytest.fixture
def runtime(tmp_path: Path) -> CodexRuntime:
    return CodexRuntime(project_root=tmp_path, codex_bin="codex")


def build_request(
    runtime: CodexRuntime,
    *,
    allowed_listing_ids: set[int] | None = None,
) -> CodexRequest:
    return runtime.build_request(
        task={
            "id": 7,
            "original_goal": "Find a camera",
            "effective_goal": "Find a silver camera",
        },
        messages=[{"task_id": 7, "role": "user", "content": "Prefer local pickup"}],
        candidates=[{"task_id": 7, "listing_id": 12, "title": "Camera"}],
        evidence=[
            {"task_id": 7, "listing_id": 12, "detail_status": "captured"}
        ],
        runs=[{"task_id": 7, "run_id": 3, "role": "initial"}],
        allowed_listing_ids=allowed_listing_ids or {12},
    )


def test_command_is_fixed_read_only_and_uses_stdin(tmp_path: Path) -> None:
    runtime = CodexRuntime(project_root=tmp_path, codex_bin="codex")
    command = runtime.build_command(last_message_path=tmp_path / "last.json")

    assert command == [
        runtime.resolved_codex_bin,
        "exec",
        "-s",
        "read-only",
        "--json",
        "-C",
        str(tmp_path.resolve()),
        "-o",
        str((tmp_path / "last.json").resolve()),
        "-",
    ]
    assert "--search" not in command
    assert "resume" not in command


def test_runtime_prefers_windows_codex_cmd_shim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shopping_agent.codex_runtime.os.name", "nt")
    monkeypatch.setattr(
        "shopping_agent.codex_runtime.shutil.which",
        lambda command: "C:/npm/codex.cmd" if command == "codex.cmd" else None,
    )

    runtime = CodexRuntime(project_root=tmp_path, codex_bin="codex")

    assert runtime.resolved_codex_bin == "C:/npm/codex.cmd"


def test_config_exposes_only_repository_codex_binary_and_timeout() -> None:
    config = AppConfig()

    assert config.codex_bin == "codex"
    assert config.codex_timeout_seconds == 300
    assert "codex_bin" not in UserSettings.model_fields
    assert "codex_timeout_seconds" not in UserSettings.model_fields
    assert not any("codex" in name for name in UserSettings.model_fields)


def test_build_request_returns_validated_current_task_shape(
    runtime: CodexRuntime,
) -> None:
    request = build_request(runtime)

    assert isinstance(request, CodexRequest)
    assert request.task.id == 7
    assert request.messages[0].task_id == 7
    assert request.candidates[0].listing_id == 12
    assert request.evidence[0].listing_id == 12
    assert request.runs[0].run_id == 3
    assert request.allowed_listing_ids == frozenset({12})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("messages", [{"role": "user", "content": "missing task"}]),
        ("messages", [{"task_id": None, "role": "user", "content": "null task"}]),
        ("messages", [{"task_id": 8, "role": "user", "content": "cross task"}]),
        ("candidates", [{"listing_id": 12, "title": "missing task"}]),
        (
            "evidence",
            [{"task_id": None, "listing_id": 12, "detail_status": "captured"}],
        ),
        ("runs", [{"task_id": 8, "run_id": 3, "role": "cross task"}]),
        (
            "evidence",
            [
                {
                    "task_id": 7,
                    "listing_id": 12,
                    "detail": {"run_id": 3},
                }
            ],
        ),
        (
            "candidates",
            [
                {
                    "task_id": 7,
                    "listing_id": 12,
                    "related": {"task_id": 8, "listing_id": 13},
                }
            ],
        ),
        (
            "runs",
            [
                {
                    "task_id": 7,
                    "run_id": 3,
                    "parent": {"task_id": None, "run_id": 2},
                }
            ],
        ),
    ],
)
def test_build_request_rejects_unscoped_or_cross_task_context(
    runtime: CodexRuntime,
    field: str,
    value: list[dict[str, object]],
) -> None:
    arguments = {
        "task": {
            "id": 7,
            "original_goal": "x",
            "effective_goal": "x",
        },
        "messages": [{"task_id": 7, "role": "user", "content": "current task"}],
        "candidates": [{"task_id": 7, "listing_id": 12}],
        "evidence": [{"task_id": 7, "listing_id": 12}],
        "runs": [{"task_id": 7, "run_id": 3}],
        "allowed_listing_ids": {12},
    }
    arguments[field] = value

    with pytest.raises(ValueError, match="current task"):
        runtime.build_request(
            **arguments,
        )


@pytest.mark.parametrize("task", [{}, {"id": None}])
def test_build_request_rejects_missing_or_null_root_task_id(
    runtime: CodexRuntime,
    task: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="current task"):
        runtime.build_request(
            task={
                **task,
                "original_goal": "x",
                "effective_goal": "x",
            },
            messages=[],
            candidates=[],
            evidence=[],
            runs=[],
            allowed_listing_ids=set(),
        )


def test_build_request_rejects_candidate_outside_allowed_task_scope(
    runtime: CodexRuntime,
) -> None:
    with pytest.raises(ValueError, match="current task"):
        runtime.build_request(
            task={"id": 7, "original_goal": "x", "effective_goal": "x"},
            messages=[],
            candidates=[{"task_id": 7, "listing_id": 999}],
            evidence=[],
            runs=[],
            allowed_listing_ids={12},
        )


def test_run_rejects_raw_prompt_before_spawning(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned = False

    def fake_popen(*args: object, **kwargs: object):
        nonlocal spawned
        spawned = True
        raise AssertionError("must not spawn")

    monkeypatch.setattr("shopping_agent.codex_runtime.subprocess.Popen", fake_popen)

    with pytest.raises(TypeError, match="CodexRequest"):
        runtime.run("raw prompt", run_id=1)

    assert spawned is False


@pytest.mark.parametrize(
    ("raw", "allowed_ids", "result_type"),
    [
        ('{"type":"answer","content":"ok","candidate_ids":[]}', set(), AnswerResult),
        (
            '{"type":"answer","content":"ok","candidate_ids":[12,18]}',
            {12, 18},
            AnswerResult,
        ),
        (
            '{"type":"action_request","summary":"Search again","listing_ids":[],"actions":["search"],"risk":"Visits search results"}',
            set(),
            ActionRequestResult,
        ),
    ],
)
def test_parse_result_accepts_valid_strict_results(
    runtime: CodexRuntime,
    raw: str,
    allowed_ids: set[int],
    result_type: type,
) -> None:
    assert isinstance(runtime.parse_result(raw, allowed_listing_ids=allowed_ids), result_type)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"type":"unknown"}',
        '{"type":"answer","content":" ","candidate_ids":[]}',
        '{"type":"answer","content":"ok","candidate_ids":[1,2,3,4,5]}',
        '{"type":"answer","content":"ok","candidate_ids":[12,12]}',
        '{"type":"answer","content":"ok","candidate_ids":[0]}',
        '{"type":"answer","content":"ok","candidate_ids":[-1]}',
        '{"type":"answer","content":"ok","candidate_ids":[12],"extra":true}',
        '{"type":"action_request","summary":"x","listing_ids":[],"actions":["unknown"],"risk":"x"}',
        '{"type":"action_request","summary":"x","listing_ids":[12,12],"actions":["detail"],"risk":"x"}',
        '{"type":"action_request","summary":"x","listing_ids":[0],"actions":["detail"],"risk":"x"}',
        '{"type":"action_request","summary":"x","listing_ids":[-1],"actions":["detail"],"risk":"x"}',
        '{"type":"action_request","summary":"x","listing_ids":[12],"actions":["detail","detail"],"risk":"x"}',
    ],
)
def test_parse_result_rejects_malformed_or_invalid_shapes(
    runtime: CodexRuntime,
    raw: str,
) -> None:
    with pytest.raises(InvalidCodexResult):
        runtime.parse_result(raw, allowed_listing_ids={1, 2, 3, 4, 5, 12})


def test_rejects_out_of_scope_answer_and_action_request(runtime: CodexRuntime) -> None:
    values = [
        '{"type":"answer","content":"x","candidate_ids":[999]}',
        '{"type":"action_request","summary":"x","listing_ids":[999],"actions":["detail"],"risk":"x"}',
    ]
    for raw in values:
        with pytest.raises(InvalidCodexResult, match="scope"):
            runtime.parse_result(raw, allowed_listing_ids={12})


@pytest.mark.parametrize("action", ["detail", "media", "ocr"])
def test_non_search_collection_actions_require_listing_ids(
    runtime: CodexRuntime,
    action: str,
) -> None:
    raw = json.dumps(
        {
            "type": "action_request",
            "summary": "collect",
            "listing_ids": [],
            "actions": [action],
            "risk": "opens a listing",
        }
    )
    with pytest.raises(InvalidCodexResult):
        runtime.parse_result(raw, allowed_listing_ids=set())


def test_run_uses_utf8_stdin_and_parses_only_last_message_file(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeProcess:
        pid = 123
        returncode = 0

        def communicate(self, input: str, timeout: int):
            observed["input"] = input
            observed["timeout"] = timeout
            output_path = Path(observed["command"][observed["command"].index("-o") + 1])
            output_path.write_text(
                '{"type":"answer","content":"safe answer","candidate_ids":[12]}',
                encoding="utf-8",
            )
            return (None, None)

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        observed["command"] = command
        observed["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr("shopping_agent.codex_runtime.subprocess.Popen", fake_popen)
    stages: list[str] = []

    result = runtime.run(
        build_request(runtime),
        run_id=101,
        stage_callback=stages.append,
    )

    kwargs = observed["kwargs"]
    assert isinstance(kwargs, dict)
    assert result.content == "safe answer"
    assert '"original_goal":"Find a camera"' in observed["input"]
    assert '"content":"Prefer local pickup"' in observed["input"]
    assert "cannot execute collection" in observed["input"]
    assert observed["input"].endswith(RESULT_SCHEMA_JSON)
    assert observed["timeout"] == 300
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["cwd"] == runtime.project_root
    assert kwargs["stdout"].closed  # Ephemeral diagnostics are deleted; no stdout text is returned.
    assert runtime.take_telemetry(101) is None  # Usage capture remains opt-in.
    assert kwargs["stderr"] == subprocess.PIPE  # Bounded startup diagnostics are classified, never returned verbatim.
    assert stages == ["starting_codex", "analyzing_evidence", "preparing_answer"]


def test_run_redacts_stderr_and_stdout_from_execution_failure(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcess:
        pid = 123
        returncode = 9

        def communicate(self, input: str, timeout: int):
            return ("raw stdout secret", "raw stderr secret")

        def wait(self, timeout: int):
            return self.returncode

    monkeypatch.setattr(
        "shopping_agent.codex_runtime.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )

    with pytest.raises(CodexExecutionError) as error:
        runtime.run(build_request(runtime), run_id=102)

    detail = str(error.value)
    assert "stdout" not in detail
    assert "stderr" not in detail
    assert "secret" not in detail


def test_run_times_out_and_terminates_windows_process_tree(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeProcess:
        pid = 1234
        returncode = None

        def communicate(self, input: str, timeout: int):
            raise subprocess.TimeoutExpired("codex", timeout)

        def wait(self, timeout: int):
            self.returncode = -9
            return self.returncode

    monkeypatch.setattr(
        "shopping_agent.codex_runtime.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr("shopping_agent.codex_runtime.os.name", "nt")

    def fake_run(command: list[str], **kwargs: object):
        observed["termination_command"] = command
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("shopping_agent.codex_runtime.subprocess.run", fake_run)

    with pytest.raises(CodexTimeoutError, match="timed out"):
        runtime.run(build_request(runtime), run_id=103)

    assert observed["termination_command"] == ["taskkill", "/PID", "1234", "/T", "/F"]


def test_cancel_terminates_active_process_and_discards_partial_result(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    released = threading.Event()
    observed: dict[str, object] = {}

    class FakeProcess:
        pid = 4321
        returncode = None

        def communicate(self, input: str, timeout: int):
            output_path = Path(observed["command"][observed["command"].index("-o") + 1])
            output_path.write_text(
                '{"type":"answer","content":"partial","candidate_ids":[]}',
                encoding="utf-8",
            )
            started.set()
            assert released.wait(2)
            self.returncode = -9
            return (None, "secret")

        def wait(self, timeout: int):
            released.set()
            self.returncode = -9
            return self.returncode

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        observed["command"] = command
        return FakeProcess()

    def fake_terminate(process_id: int) -> None:
        observed["terminated"] = process_id
        released.set()

    monkeypatch.setattr("shopping_agent.codex_runtime.subprocess.Popen", fake_popen)
    monkeypatch.setattr(runtime, "_terminate_process_tree", fake_terminate)
    failures: list[BaseException] = []

    def invoke() -> None:
        try:
            runtime.run(build_request(runtime), run_id=99)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=invoke)
    thread.start()
    assert started.wait(2)
    assert runtime.cancel(run_id=99) is True
    thread.join(timeout=2)

    assert observed["terminated"] == 4321
    assert len(failures) == 1
    assert isinstance(failures[0], CodexCancelledError)
    assert runtime.cancel(run_id=99) is False


def test_cancel_requires_a_key_and_can_cancel_before_spawn(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserved = threading.Event()
    release = threading.Event()
    spawned = False
    failures: list[BaseException] = []

    def stage_callback(stage: str) -> None:
        if stage == "starting_codex":
            reserved.set()
            assert release.wait(2)

    def fake_popen(*args: object, **kwargs: object):
        nonlocal spawned
        spawned = True
        raise AssertionError("cancelled reservation must not spawn")

    monkeypatch.setattr("shopping_agent.codex_runtime.subprocess.Popen", fake_popen)

    def invoke() -> None:
        try:
            runtime.run(
                build_request(runtime),
                run_id=201,
                stage_callback=stage_callback,
            )
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=invoke)
    thread.start()
    assert reserved.wait(2)
    with pytest.raises(TypeError):
        runtime.cancel()
    assert runtime.cancel(201) is True
    release.set()
    thread.join(timeout=2)

    assert spawned is False
    assert len(failures) == 1
    assert isinstance(failures[0], CodexCancelledError)


def test_cancel_returning_true_prevents_success_at_final_callback(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparing = threading.Event()
    release = threading.Event()
    observed: dict[str, object] = {}
    outcomes: list[object] = []

    class FakeProcess:
        pid = 5201
        returncode = None

        def communicate(self, input: str, timeout: int):
            output_path = Path(observed["command"][observed["command"].index("-o") + 1])
            output_path.write_text(
                '{"type":"answer","content":"must not return","candidate_ids":[]}',
                encoding="utf-8",
            )
            self.returncode = 0
            return (None, None)

        def wait(self, timeout: int):
            return self.returncode

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        observed["command"] = command
        return FakeProcess()

    def stage_callback(stage: str) -> None:
        if stage == "preparing_answer":
            preparing.set()
            assert release.wait(2)

    monkeypatch.setattr("shopping_agent.codex_runtime.subprocess.Popen", fake_popen)

    def invoke() -> None:
        try:
            outcomes.append(
                runtime.run(
                    build_request(runtime),
                    run_id=202,
                    stage_callback=stage_callback,
                )
            )
        except BaseException as exc:
            outcomes.append(exc)

    thread = threading.Thread(target=invoke)
    thread.start()
    assert preparing.wait(2)
    assert runtime.cancel(202) is True
    release.set()
    thread.join(timeout=2)

    assert len(outcomes) == 1
    assert isinstance(outcomes[0], CodexCancelledError)


def test_duplicate_run_id_is_rejected_before_second_spawn(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserved = threading.Event()
    release = threading.Event()
    observed: dict[str, object] = {"spawn_count": 0}
    outcomes: list[object] = []

    class FakeProcess:
        pid = 5202
        returncode = None

        def communicate(self, input: str, timeout: int):
            output_path = Path(observed["command"][observed["command"].index("-o") + 1])
            output_path.write_text(
                '{"type":"answer","content":"ok","candidate_ids":[]}',
                encoding="utf-8",
            )
            self.returncode = 0
            return (None, None)

        def wait(self, timeout: int):
            return self.returncode

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        observed["spawn_count"] = int(observed["spawn_count"]) + 1
        observed["command"] = command
        return FakeProcess()

    def stage_callback(stage: str) -> None:
        if stage == "starting_codex":
            reserved.set()
            assert release.wait(2)

    monkeypatch.setattr("shopping_agent.codex_runtime.subprocess.Popen", fake_popen)

    def invoke() -> None:
        try:
            outcomes.append(
                runtime.run(
                    build_request(runtime),
                    run_id=203,
                    stage_callback=stage_callback,
                )
            )
        except BaseException as exc:
            outcomes.append(exc)

    thread = threading.Thread(target=invoke)
    thread.start()
    assert reserved.wait(2)
    with pytest.raises(CodexExecutionError, match="already active"):
        runtime.run(build_request(runtime), run_id=203)
    assert observed["spawn_count"] == 0
    release.set()
    thread.join(timeout=2)

    assert observed["spawn_count"] == 1
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], AnswerResult)


def test_callback_failure_terminates_and_reaps_spawned_process(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeProcess:
        pid = 5203
        returncode = None

        def communicate(self, input: str, timeout: int):
            raise AssertionError("communicate must not run")

        def wait(self, timeout: int):
            observed["wait_timeout"] = timeout
            self.returncode = -15
            return self.returncode

    monkeypatch.setattr(
        "shopping_agent.codex_runtime.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        runtime,
        "_terminate_process_tree",
        lambda process_id: observed.setdefault("terminated", process_id),
    )

    def fail_after_spawn(stage: str) -> None:
        if stage == "analyzing_evidence":
            raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        runtime.run(
            build_request(runtime),
            run_id=204,
            stage_callback=fail_after_spawn,
        )

    assert observed["terminated"] == 5203
    assert observed["wait_timeout"] == 10
    assert runtime.cancel(204) is False


def test_cleanup_reaps_when_graceful_termination_call_fails(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {"wait_count": 0}

    class FakeProcess:
        pid = 5205
        returncode = None

        def communicate(self, input: str, timeout: int):
            raise AssertionError("communicate must not run")

        def wait(self, timeout: int):
            observed["wait_count"] = int(observed["wait_count"]) + 1
            self.returncode = -15
            return self.returncode

    monkeypatch.setattr(
        "shopping_agent.codex_runtime.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )

    def fail_termination(process_id: int) -> None:
        raise OSError("termination helper unavailable")

    monkeypatch.setattr(runtime, "_terminate_process_tree", fail_termination)
    monkeypatch.setattr(
        runtime,
        "_force_kill_process_tree",
        lambda process_id: pytest.fail("force kill must not run after a successful reap"),
    )

    def fail_after_spawn(stage: str) -> None:
        if stage == "analyzing_evidence":
            raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        runtime.run(
            build_request(runtime),
            run_id=206,
            stage_callback=fail_after_spawn,
        )

    assert observed["wait_count"] == 1
    assert runtime.cancel(206) is False


@pytest.mark.parametrize(
    "wait_error",
    [
        subprocess.TimeoutExpired("codex", 10),
        OSError("wait helper unavailable"),
    ],
)
def test_cleanup_forces_and_reaps_after_graceful_wait_fails(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
    wait_error: BaseException,
) -> None:
    observed: dict[str, object] = {"wait_count": 0}

    class FakeProcess:
        pid = 5205
        returncode = None

        def communicate(self, input: str, timeout: int):
            raise AssertionError("communicate must not run")

        def wait(self, timeout: int):
            observed["wait_count"] = int(observed["wait_count"]) + 1
            if observed["wait_count"] == 1:
                raise wait_error
            self.returncode = -9
            return self.returncode

    monkeypatch.setattr(
        "shopping_agent.codex_runtime.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )

    monkeypatch.setattr(
        runtime,
        "_terminate_process_tree",
        lambda process_id: observed.setdefault("terminated", process_id),
    )
    monkeypatch.setattr(
        runtime,
        "_force_kill_process_tree",
        lambda process_id: observed.setdefault("force_killed", process_id),
    )

    def fail_after_spawn(stage: str) -> None:
        if stage == "analyzing_evidence":
            raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        runtime.run(
            build_request(runtime),
            run_id=209,
            stage_callback=fail_after_spawn,
        )

    assert observed["wait_count"] == 2
    assert observed["terminated"] == 5205
    assert observed["force_killed"] == 5205
    assert runtime.cancel(209) is False


def test_ignored_posix_sigterm_escalates_to_process_group_sigkill(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {"signals": [], "wait_count": 0}

    class FakeProcess:
        pid = 5206
        returncode = None

        def communicate(self, input: str, timeout: int):
            raise subprocess.TimeoutExpired("codex", timeout)

        def wait(self, timeout: int):
            observed["wait_count"] = int(observed["wait_count"]) + 1
            if observed["wait_count"] == 1:
                raise subprocess.TimeoutExpired("codex", timeout)
            self.returncode = -9
            return self.returncode

    monkeypatch.setattr("shopping_agent.codex_runtime._is_windows", lambda: False)
    monkeypatch.setattr(
        "shopping_agent.codex_runtime.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        "shopping_agent.codex_runtime._kill_process_group",
        lambda process_id, sig: observed["signals"].append((process_id, sig)),
    )

    with pytest.raises(CodexTimeoutError):
        runtime.run(build_request(runtime), run_id=207)

    assert observed["signals"] == [
        (5206, signal.SIGTERM),
        (5206, getattr(signal, "SIGKILL", 9)),
    ]
    assert observed["wait_count"] == 2
    assert runtime.cancel(207) is False


def test_persistent_unreaped_process_retains_key_for_cancel_retry(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {"can_reap": False, "wait_count": 0}

    class FakeProcess:
        pid = 5207
        returncode = None

        def communicate(self, input: str, timeout: int):
            raise RuntimeError("raw stdout secret")

        def wait(self, timeout: int):
            observed["wait_count"] = int(observed["wait_count"]) + 1
            if not observed["can_reap"]:
                raise subprocess.TimeoutExpired("raw stderr secret", timeout)
            self.returncode = -9
            return self.returncode

    monkeypatch.setattr(
        "shopping_agent.codex_runtime.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )

    def fail_tree_action(process_id: int) -> None:
        raise OSError("raw stderr secret")

    monkeypatch.setattr(runtime, "_terminate_process_tree", fail_tree_action)
    monkeypatch.setattr(runtime, "_force_kill_process_tree", fail_tree_action)

    with pytest.raises(CodexCleanupError) as error:
        runtime.run(build_request(runtime), run_id=208)

    detail = str(error.value)
    assert "raw" not in detail
    assert "stderr" not in detail
    assert "stdout" not in detail
    assert "secret" not in detail
    with pytest.raises(CodexExecutionError, match="already active"):
        runtime.run(build_request(runtime), run_id=208)
    with pytest.raises(CodexCleanupError):
        runtime.cancel(208)

    observed["can_reap"] = True
    assert runtime.cancel(208) is True
    assert runtime.cancel(208) is False


def test_posix_timeout_starts_session_and_terminates_process_group(
    runtime: CodexRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeProcess:
        pid = 5204
        returncode = None

        def communicate(self, input: str, timeout: int):
            raise subprocess.TimeoutExpired("codex", timeout)

        def wait(self, timeout: int):
            self.returncode = -15
            return self.returncode

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        observed["popen_kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr("shopping_agent.codex_runtime._is_windows", lambda: False)
    monkeypatch.setattr("shopping_agent.codex_runtime.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "shopping_agent.codex_runtime._kill_process_group",
        lambda process_id, sig: observed.update(
            process_id=process_id,
            signal=sig,
        ),
    )

    with pytest.raises(CodexTimeoutError):
        runtime.run(build_request(runtime), run_id=205)

    kwargs = observed["popen_kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["start_new_session"] is True
    assert observed["process_id"] == 5204
    assert observed["signal"] == signal.SIGTERM
