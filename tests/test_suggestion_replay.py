"""The saved workflow checker must work before spending real model calls."""
import importlib.util
import json
import sys
from types import SimpleNamespace

import pytest

from shopping_agent.assessment import CheckSuggestion
from shopping_agent.codex_runtime import AnswerResult, CodexRuntime


def script():
    spec = importlib.util.spec_from_file_location("suggestion_replay_script", "scripts/replay_check_suggestions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_and_overwrite_are_call_free(tmp_path, monkeypatch, capsys):
    module = script()
    monkeypatch.setattr(module, "check_codex_availability", lambda: pytest.fail("unexpected setup"))
    monkeypatch.setattr(sys, "argv", ["replay"])
    assert module.main() == 0 and json.loads(capsys.readouterr().out)["calls"] == 0
    path = tmp_path / "keep.json"
    path.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["replay", "--run", "--output", str(path)])
    with pytest.raises(FileExistsError):
        module.main()
    assert path.read_text() == "keep"


def test_two_turn_saved_workflow_with_scripted_model(tmp_path, monkeypatch):
    module = script()
    class Runtime:
        build_request = CodexRuntime.build_request
        def __init__(self):
            self.calls = 0
        def run(self, request, *, run_id, stage_callback):
            self.calls += 1
            stage_callback("analyzing_evidence")
            return AnswerResult(type="answer", content="请核对建议后确认保存。", candidate_ids=[], check_suggestions=[CheckSuggestion(
                listing_id=min(request.allowed_listing_ids), question="屏幕维修记录？" if self.calls == 1 else "电池实际健康情况？", reason="证据未说明")])
        def cancel(self, run_id):
            pass
    monkeypatch.setattr(module, "check_codex_availability", lambda: SimpleNamespace(cli_available=True, auth_available=True))
    monkeypatch.setattr(module, "CapturingCodexRuntime", lambda *args, **kwargs: Runtime())
    path = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["replay", "--run", "--output", str(path)])
    assert module.main() == 0
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["calls_count"] == 2 and report["restored_checklist"]["total_count"] == 1
    assert all(row["operation"]["state"] == "completed" for row in report["turns"])
    assert not report["quality_verified"] and report["manual_review"] == "pending"
