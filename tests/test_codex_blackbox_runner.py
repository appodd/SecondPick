import json
import os
import subprocess
from pathlib import Path

from devtools.run_codex_blackbox import (
    build_codex_command,
    resolve_codex_bin,
    run_codex_prompt,
)


def test_resolve_codex_bin_prefers_windows_cmd_shim(monkeypatch) -> None:
    observed = []

    def fake_which(command):
        observed.append(command)
        if command == "codex.cmd":
            return "C:\\npm\\codex.cmd"
        return None

    monkeypatch.setattr("devtools.run_codex_blackbox.os.name", "nt")
    monkeypatch.setattr("devtools.run_codex_blackbox.shutil.which", fake_which)

    assert resolve_codex_bin("codex") == "C:\\npm\\codex.cmd"
    assert observed == ["codex.cmd"]


def test_build_codex_command_for_new_session() -> None:
    command = build_codex_command(
        "codex",
        Path("C:/project"),
        Path("C:/out/answer.txt"),
        session_id=None,
        model="glm-5.2",
    )

    assert command == [
        "codex",
        "exec",
        "-s",
        "workspace-write",
        "-m",
        "glm-5.2",
        "--json",
        "-C",
        "C:\\project",
        "-o",
        "C:\\out\\answer.txt",
        "-",
    ]


def test_build_codex_command_for_resumed_session() -> None:
    command = build_codex_command(
        "codex",
        Path("C:/project"),
        Path("C:/out/answer.txt"),
        session_id="019fcc5a-b516-7e43-876a-2395339fdb84",
        model="glm-5.2",
    )

    assert command == [
        "codex",
        "exec",
        "-s",
        "workspace-write",
        "resume",
        "-m",
        "glm-5.2",
        "--json",
        "-o",
        "C:\\out\\answer.txt",
        "019fcc5a-b516-7e43-876a-2395339fdb84",
        "-",
    ]


def test_build_codex_command_allows_explicit_browser_sandbox_override() -> None:
    command = build_codex_command(
        "codex",
        Path("C:/project"),
        Path("C:/out/answer.txt"),
        session_id=None,
        model="glm-5.2",
        sandbox_mode="danger-full-access",
    )

    assert command[2:4] == ["-s", "danger-full-access"]


def test_run_codex_prompt_writes_exact_unicode_to_stdin(tmp_path, monkeypatch) -> None:
    prompt_path = tmp_path / "prompt.txt"
    events_path = tmp_path / "events.jsonl"
    stderr_path = tmp_path / "stderr.txt"
    answer_path = tmp_path / "answer.txt"
    metadata_path = tmp_path / "events.metadata.json"
    prompt = "我人在上海，目标是索尼 A7C 一代机身。"
    prompt_path.write_text(prompt, encoding="utf-8")
    observed = {}

    class FakeProcess:
        returncode = 0

        def communicate(self, input, timeout):
            observed["input"] = input
            observed["timeout"] = timeout

    def fake_popen(command, **kwargs):
        observed["metadata_before_popen"] = metadata_path.exists()
        observed["command"] = command
        observed["text"] = kwargs["text"]
        observed["encoding"] = kwargs["encoding"]
        observed["cwd"] = kwargs["cwd"]
        observed["env"] = kwargs.get("env")
        return FakeProcess()

    monkeypatch.setattr("devtools.run_codex_blackbox.subprocess.Popen", fake_popen)

    result = run_codex_prompt(
        prompt_path,
        events_path,
        stderr_path,
        answer_path,
        tmp_path,
        model="glm-5.2",
    )

    assert result == 0
    assert observed["input"] == prompt
    assert observed["text"] is True
    assert observed["encoding"] == "utf-8"
    assert observed["cwd"] == tmp_path
    assert observed["timeout"] == 300
    assert observed["env"]["PYTHONPATH"] == f"{tmp_path / 'src'}{os.pathsep}{tmp_path}"
    assert observed["env"]["PYTHONUTF8"] == "1"
    assert observed["env"]["PYTHONIOENCODING"] == "utf-8"
    assert observed["metadata_before_popen"] is True
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata == {
        "model": "glm-5.2",
        "sandbox_mode": "workspace-write",
        "timeout_seconds": 300,
        "project_root": str(tmp_path.resolve()),
        "session_id": None,
        "command": observed["command"],
    }


def test_run_codex_prompt_times_out_and_terminates_windows_process_tree(tmp_path, monkeypatch) -> None:
    prompt_path = tmp_path / "prompt.txt"
    events_path = tmp_path / "events.jsonl"
    stderr_path = tmp_path / "stderr.txt"
    answer_path = tmp_path / "answer.txt"
    metadata_path = tmp_path / "custom-metadata.json"
    prompt_path.write_text("测试", encoding="utf-8")
    observed = {}

    class FakeProcess:
        pid = 1234
        returncode = None

        def communicate(self, input, timeout):
            observed["input"] = input
            observed["timeout"] = timeout
            raise subprocess.TimeoutExpired("codex", timeout)

        def wait(self, timeout=None):
            self.returncode = -9
            return self.returncode

    def fake_popen(command, **kwargs):
        observed["command"] = command
        return FakeProcess()

    def fake_run(command, **kwargs):
        observed["termination_command"] = command

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devtools.run_codex_blackbox.subprocess.Popen", fake_popen)
    monkeypatch.setattr("devtools.run_codex_blackbox.subprocess.run", fake_run)
    monkeypatch.setattr("devtools.run_codex_blackbox.os.name", "nt")

    result = run_codex_prompt(
        prompt_path,
        events_path,
        stderr_path,
        answer_path,
        tmp_path,
        model="glm-5.2",
        timeout_seconds=300,
        metadata_path=metadata_path,
    )

    assert result == 124
    assert observed["input"] == "测试"
    assert observed["timeout"] == 300
    assert observed["termination_command"] == [
        "taskkill",
        "/PID",
        "1234",
        "/T",
        "/F",
    ]
    assert "timed out after 300 seconds" in stderr_path.read_text(encoding="utf-8")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["model"] == "glm-5.2"
    assert metadata["timeout_seconds"] == 300
