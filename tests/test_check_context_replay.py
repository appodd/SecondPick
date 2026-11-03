"""Harness contract checks with fabricated outputs, not model quality evidence."""
import importlib.util
import json
import sys

import pytest

from shopping_agent.assessment import input_refs
from shopping_agent.check_context_replay import build_check_probes, check_check_probe
from shopping_agent.codex_runtime import CodexRuntime
from test_statement_correction_replay import fabricated


@pytest.fixture
def probes(tmp_path):
    return build_check_probes(tmp_path)


def test_saved_context_keeps_oracles_out_of_input(probes):
    assert len(probes) == 3
    for probe in probes:
        assert probe.request.phase == "chat" and len(probe.request.follow_up_context["items"]) == 1
        assert check_check_probe(probe, fabricated(probe)) == []
        prompt = CodexRuntime._build_prompt(probe.request)
        assert "oracle" not in prompt and "expected" not in prompt
    invalid = probes[1].request.follow_up_context["items"][0]
    assert invalid["needs_recheck"] and invalid["linked_evidence_ref"] is None
    assert not any(ref.startswith("statement:") for ref in input_refs(probes[1].request))


@pytest.mark.parametrize("index", [0, 1])
def test_question_or_withdrawn_claim_cannot_pass_as_seller_evidence(probes, index):
    result = fabricated(probes[index])
    result.research.assessments[0].judgments[-1].source_type = "seller_claim"
    assert check_check_probe(probes[index], result)


def test_link_does_not_override_second_conflicting_reply(probes):
    result = fabricated(probes[2])
    result.research.assessments[0].judgments[-1].evidence_refs.pop()
    assert check_check_probe(probes[2], result)


def test_plan_and_existing_report_do_not_call_model(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("checks_script", "scripts/replay_check_context.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "check_codex_availability", lambda: pytest.fail("unexpected setup"))
    monkeypatch.setattr(sys, "argv", ["replay"])
    assert module.main() == 0 and json.loads(capsys.readouterr().out)["calls"] == 0
    output = tmp_path / "keep.json"
    output.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["replay", "--run", "--output", str(output)])
    with pytest.raises(FileExistsError):
        module.main()
    assert output.read_text() == "keep"
