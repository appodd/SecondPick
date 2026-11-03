import json
from pathlib import Path
import sys

import pytest

from shopping_agent.config import AppConfig, MonitorEngineConfig
from shopping_agent.monitor_environment import check_monitor_environment


def config(tmp_path):
    return AppConfig(monitor_engine=MonitorEngineConfig(root=tmp_path, python=Path(sys.executable)))


def test_unconfigured_environment_does_not_spawn_or_read_login(tmp_path, monkeypatch):
    import shopping_agent.monitor_environment as module
    monkeypatch.setattr(module, "run_process", lambda *a, **kw: pytest.fail("must not spawn"))
    result = check_monitor_environment(AppConfig())
    assert result["ready"] is False and result["checks"] == [{"code": "configuration", "ok": False}]


def test_probe_uses_isolated_cwd_and_safe_environment_without_changing_enabled(tmp_path, monkeypatch):
    import shopping_agent.monitor_environment as module
    monkeypatch.setattr(module.GoofishEngine, "preflight", lambda self: tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "private-model-key")
    monkeypatch.setenv("NTFY_TOPIC_URL", "private-notification-url")
    monkeypatch.setenv("ProgramFiles", "C:/system-programs")
    def process(command, *, cwd, env, **kwargs):
        assert Path(cwd) != tmp_path and not (Path(cwd) / ".env").exists()
        assert {k.upper(): v for k, v in env.items()}["PROGRAMFILES"] == "C:/system-programs"
        assert env["SKIP_AI_ANALYSIS"] == "true" and env["RUN_HEADLESS"] == "true"
        assert "OPENAI_API_KEY" not in env and "NTFY_TOPIC_URL" not in env
        Path(command[-1]).write_text(json.dumps([dict(code=c, ok=True, secret="discarded")
            for c in ("dependencies", "control_flow", "browser")]))
    monkeypatch.setattr(module, "run_process", process)
    value = config(tmp_path)
    result = check_monitor_environment(value)
    assert result["ready"] is True and not value.monitor_engine.enabled
    assert "private" not in json.dumps(result) and "discarded" not in json.dumps(result)


@pytest.mark.parametrize("rows", [[], [{"code": "browser", "ok": True}],
    [{"code": "dependencies", "ok": True}], [{"code": "dependencies", "ok": 1}],
    [{"code": "dependencies", "ok": False}, {"code": "control_flow", "ok": True}]])
def test_malformed_or_incomplete_probe_cannot_report_ready(tmp_path, monkeypatch, rows):
    import shopping_agent.monitor_environment as module
    monkeypatch.setattr(module.GoofishEngine, "preflight", lambda self: tmp_path)
    monkeypatch.setattr(module, "run_process", lambda cmd, **kw: Path(cmd[-1]).write_text(json.dumps(rows)))
    result = check_monitor_environment(config(tmp_path))
    assert not result["ready"] and result["checks"][-1] == dict(code="probe", ok=False)


def test_standalone_probe_with_missing_engine_dependencies_fails_cleanly(tmp_path, monkeypatch):
    import shopping_agent.monitor_environment as module
    monkeypatch.setattr(module.GoofishEngine, "preflight", lambda self: tmp_path)
    result = check_monitor_environment(config(tmp_path))
    assert not result["ready"] and result["checks"][-1] == dict(code="dependencies", ok=False)


def test_oversized_probe_result_is_rejected(tmp_path, monkeypatch):
    import shopping_agent.monitor_environment as module
    monkeypatch.setattr(module.GoofishEngine, "preflight", lambda self: tmp_path)
    monkeypatch.setattr(module, "run_process", lambda cmd, **kw: Path(cmd[-1]).write_text(" " * 5000))
    result = check_monitor_environment(config(tmp_path))
    assert not result["ready"] and result["checks"][-1] == dict(code="probe", ok=False)
