"""Probe preparation uses real saved reviews; fixture checks are not model results."""
from shopping_agent.check_review_replay import build_review_probes, check_review_probe
from test_statement_correction_replay import fabricated


def test_reviews_are_scoped_and_stale_summaries_are_not_supplied(tmp_path):
    probes = build_review_probes(tmp_path)
    assert len(probes) == 3
    for probe in probes:
        review = probe.request.follow_up_context["items"][0]["user_review"]
        assert review["independently_verified"] is False
        assert check_review_probe(probe, fabricated(probe)) == []
    assert "summary" not in probes[1].request.follow_up_context["items"][0]["user_review"]
    assert probes[0].request.follow_up_context["items"][0]["user_review"]["outcome"] == "answered"


def test_user_answer_cannot_erase_a_conflict(tmp_path):
    probe = build_review_probes(tmp_path)[2]
    result = fabricated(probe)
    result.research.assessments[0].judgments[-1].status = "MET"
    assert check_review_probe(probe, result)
