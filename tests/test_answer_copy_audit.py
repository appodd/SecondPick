"""Checker tests use fabricated outputs, not model quality evidence."""
import copy

import pytest

from shopping_agent.answer_copy_audit import audit_answer_copy, prose_findings
from shopping_agent.assessment import signature


def report():
    request = {"task": {"id": 1}}
    return dict(mode="real_model_service_journey", prompt_version="shopping-research-v9",
                state="checks_passed_manual_review_pending", calls_count=1,
                calls=[dict(phase="comparison", state="returned", request=request,
                            request_signature=signature(request), result={
                                "type": "comparison", "content": "商品 #1 的原装情况未知，需核实卖家答复。",
                                "ranked_candidates": [dict(listing_id=1, assessment_id=2,
                                    reason="价格符合预算", uncertainties=["维修情况未知"])],
                                "evidence_refs": ["statement:1:0123456789abcdef"]})])


def test_protocol_fields_and_natural_product_ids_are_not_removed_or_flagged():
    source = report()
    original = copy.deepcopy(source)
    result = audit_answer_copy(source)
    assert result["state"] == "checks_passed" and result["calls"] == 0
    assert not result["quality_verified"] and source == original


@pytest.mark.parametrize("text", ["assessment_id=2", "statement:1:0123456789abcdef", "原装为UNKNOWN", "本次比较输入只有一件"])
def test_detects_internal_tokens_in_nested_prose_and_lists(text):
    findings = prose_findings({"ranked_candidates": [{"reason": text, "uncertainties": [text]}]})
    assert len(findings) == 2
    assert findings[0]["path"].endswith(".reason")
    assert findings[1]["path"].endswith(".uncertainties[0]")


def test_incomplete_source_cannot_receive_complete_copy_pass():
    source = report()
    source["state"] = "incomplete_or_failed"
    assert audit_answer_copy(source)["state"] == "incomplete"
    source["calls"][0]["request"]["task"]["id"] = 2
    with pytest.raises(ValueError, match="signature"):
        audit_answer_copy(source)
