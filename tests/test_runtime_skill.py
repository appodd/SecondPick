from pathlib import Path


SKILL_PATH = Path("skills/secondhand-shopping-research/SKILL.md")
REFERENCE_DIR = SKILL_PATH.parent / "references"
EXPECTED_REFERENCES = {
    "task-memory.md",
    "search-discovery.md",
    "candidate-review.md",
    "detail-investigation.md",
    "visual-evidence.md",
    "deep-research.md",
    "external-verification.md",
}
EXPECTED_HEADINGS = {
    "## When To Read",
    "## Stage Goal",
    "## Minimum Data Prerequisites",
    "## Reuse Saved Evidence",
    "## Canonical Commands",
    "## Output And Evidence Semantics",
    "## Exit Conditions",
    "## Related Stages",
}


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _reference_text(name: str) -> str:
    return (REFERENCE_DIR / name).read_text(encoding="utf-8")


def test_runtime_skill_is_a_concise_router_without_cli_examples() -> None:
    text = _skill_text()

    assert len(text) < 6_000
    assert "python -m shopping_agent.cli" not in text
    assert "Tool-event display truncation" not in text
    assert "handoff.md" not in text
    assert "SESSION_HANDOFF.md" not in text
    assert "README" in text
    assert "source" in text
    assert "config" in text
    assert "CLI help" in text
    assert "current question" in text
    assert "effective_goal" in text
    assert "evidence gaps" in text
    assert "Do not enumerate the Skill directory" in text


def test_runtime_skill_links_each_direct_reference_exactly_once() -> None:
    text = _skill_text()

    assert {path.name for path in REFERENCE_DIR.glob("*.md")} == EXPECTED_REFERENCES
    for name in EXPECTED_REFERENCES:
        assert text.count(f"references/{name}") == 1


def test_each_reference_uses_the_shared_eight_section_contract() -> None:
    for name in EXPECTED_REFERENCES:
        text = _reference_text(name)
        headings = {line for line in text.splitlines() if line.startswith("## ")}
        assert headings == EXPECTED_HEADINGS, name
        assert not text.startswith("---"), name


def test_candidate_review_owns_complete_exact_once_candidate_semantics() -> None:
    text = _reference_text("candidate-review.md")

    for token in (
        "deduplicated_count",
        "returned_count",
        "exactly once",
        "search_description=null",
        "redundant_with_title",
        "candidate-index --run-id 62 --pretty",
        "one complete `candidate-index` call",
        "query-candidates",
    ):
        assert token in text
    assert "candidate-index --run-id 62 --limit 40 --cursor" not in text
    assert "candidate-evidence" not in text


def test_candidate_review_requires_index_before_semantic_comparison() -> None:
    text = _reference_text("candidate-review.md")

    assert "must make one complete `candidate-index` call before `query-candidates`" in text
    assert "strictly mechanical count/list request" in text
    assert "at most one `query-candidates` call" in text


def test_detail_investigation_owns_provenance_conflicts_and_seller_uncertainty() -> None:
    text = _reference_text("detail-investigation.md")

    for token in (
        "evidence_conflicts",
        "search_card",
        "seller_entered_attribute",
        "platform_seller_field",
        "detail_dom_fallback",
        "seller type",
        "candidate-evidence",
        "capture-detail",
    ):
        assert token in text


def test_visual_search_deep_and_external_references_own_their_guardrails() -> None:
    visual = _reference_text("visual-evidence.md")
    search = _reference_text("search-discovery.md")
    deep = _reference_text("deep-research.md")
    external = _reference_text("external-verification.md")

    assert "--listing-id" in visual
    assert "OCR is fallible" in visual
    assert "1800" in search
    assert "correction search" in search
    assert "300-600" in deep
    assert "marginal gain" in deep
    assert "first-answer gate" in deep
    assert "official" in external
    assert "seller claims" in external


def test_stage_commands_live_only_in_their_own_references() -> None:
    texts = {name: _reference_text(name) for name in EXPECTED_REFERENCES}
    command_owners = {
        "task-summary": "task-memory.md",
        "task-create": "task-memory.md",
        "task-update": "task-memory.md",
        "spike-search": "search-discovery.md",
        "candidate-index": "candidate-review.md",
        "query-candidates": "candidate-review.md",
        "candidate-evidence": "detail-investigation.md",
        "capture-detail": "detail-investigation.md",
        "download-media": "visual-evidence.md",
        "analyze-images": "visual-evidence.md",
        "compare-runs": "deep-research.md",
        "reference-list": "external-verification.md",
        "reference-add": "external-verification.md",
    }

    for command, owner in command_owners.items():
        containing_files = {name for name, text in texts.items() if command in text}
        assert containing_files == {owner}, command
