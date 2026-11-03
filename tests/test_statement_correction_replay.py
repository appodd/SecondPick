"""Fabricated harness results, not real-model quality evidence."""
import importlib.util
import json
import sys

import pytest

from shopping_agent.assessment import input_refs
from shopping_agent.codex_runtime import AnswerResult, CodexRuntime
from shopping_agent.statement_correction_replay import build_correction_probes, check_correction_probe


@pytest.fixture
def probes(tmp_path):
    return build_correction_probes(tmp_path)


def fabricated(probe):
    refs = input_refs(probe.request)
    assessments = []
    for listing_id, (status, source) in probe.expected.items():
        card = next(ref for ref in refs if ref.startswith(f"card:{listing_id}:"))
        statements = [ref for ref in refs if ref.startswith(f"statement:{listing_id}:")]
        judgments = [dict(criterion_id=key, status="MET", source_type="seller_claim",
                          reason="测试夹具", evidence_refs=[card]) for key in ("budget", "capacity")]
        judgments.append(dict(criterion_id="originality", status=status, source_type=source or "missing",
                              reason="测试夹具", evidence_refs=statements if source else []))
        assessments.append(dict(listing_id=listing_id, judgments=judgments, summary="测试夹具",
                                conclusion="not_met" if status == "NOT_MET" else "insufficient_evidence"))
    return AnswerResult.model_validate(dict(type="answer", content="测试夹具", candidate_ids=[],
        research=dict(criteria=[c.model_dump() for c in probe.request.current_criteria], assessments=assessments)))


def test_context_uses_persisted_current_metadata_and_no_oracles(probes):
    for probe in probes:
        message = next(m for m in probe.request.messages if m.candidate_statement)
        binding = message.candidate_statement
        refs = input_refs(probe.request)
        assert binding["revision_id"] > 0
        if probe.name == "withdrawn-repair-claim":
            assert binding["status"] == "withdrawn"
            assert not any(ref.startswith("statement:") for ref in refs)
        elif probe.name == "rebound-repair-claim":
            assert binding["listing_id"] != binding["original_listing_id"]
            assert f"商品#{binding['original_listing_id']}" in message.content
        else:
            assert binding["kind"] == "user_observation"
        prompt = CodexRuntime._build_prompt(probe.request)
        assert "oracle" not in prompt and "expected" not in prompt


@pytest.mark.parametrize("index", [0, 1, 2])
def test_correct_fabricated_result_passes(probes, index):
    assert check_correction_probe(probes[index], fabricated(probes[index])) == []


@pytest.mark.parametrize("fault", ["old_target", "foreign_ref", "source", "missing_statement", "proposal"])
def test_rebound_semantic_or_reference_errors_fail(probes, fault):
    probe = probes[1]
    result = fabricated(probe)
    failed = next(a for a in result.research.assessments if a.conclusion == "not_met")
    other = next(a for a in result.research.assessments if a is not failed)
    if fault == "old_target":
        failed.judgments[-1], other.judgments[-1] = other.judgments[-1], failed.judgments[-1]
    elif fault == "foreign_ref":
        failed.judgments[-1].evidence_refs = other.judgments[0].evidence_refs
    elif fault == "source":
        failed.judgments[-1].source_type = "image_observation"
    elif fault == "missing_statement":
        failed.judgments[-1].evidence_refs = failed.judgments[0].evidence_refs
    else:
        result.candidate_ids = [failed.listing_id]
    assert check_correction_probe(probe, result)


def test_withdrawn_claim_cannot_establish_failure(probes):
    result = fabricated(probes[0])
    result.research.assessments[0].judgments[-1].status = "NOT_MET"
    assert check_correction_probe(probes[0], result)


def test_cli_plan_and_overwrite_are_call_free(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("correction_script", "scripts/replay_statement_corrections.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "check_codex_availability", lambda: pytest.fail("setup called"))
    monkeypatch.setattr(sys, "argv", ["replay"])
    assert module.main() == 0 and json.loads(capsys.readouterr().out)["calls"] == 0
    path = tmp_path / "keep.json"
    path.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["replay", "--run", "--output", str(path)])
    with pytest.raises(FileExistsError):
        module.main()
    assert path.read_text() == "keep"
