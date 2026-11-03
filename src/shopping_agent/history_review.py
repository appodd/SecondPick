"""Local, bounded history review using the existing operation lifecycle."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, model_validator

from shopping_agent.assessment import (
    AssessmentModel, CheckSuggestion, Criterion, ResearchResult, SCHEMA_VERSION, PROMPT_VERSION,
    evidence_signature, evidence_state, save_research, save_standard, signature,
)


class ReviewInputChangedError(ValueError):
    pass


class HistoryReviewResult(AssessmentModel):
    type: Literal["history_review"]
    summary: str = Field(min_length=1, max_length=2000)
    criteria: list[Criterion] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_criteria(self):
        ResearchResult(criteria=self.criteria)
        if not self.summary.strip():
            raise ValueError("review summary required")
        return self


class ComparisonEntry(AssessmentModel):
    listing_id: int = Field(gt=0)
    assessment_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=2000)
    uncertainties: list[str] = Field(max_length=20)


class ComparisonChange(AssessmentModel):
    listing_id: int = Field(gt=0)
    assessment_id: int = Field(gt=0)
    kind: Literal["entered", "exited"]
    reason: str = Field(min_length=1, max_length=2000)


class ComparisonResult(AssessmentModel):
    type: Literal["comparison"]
    content: str = Field(min_length=1, max_length=16000)
    ranked_candidates: list[ComparisonEntry] = Field(max_length=4)
    changes: list[ComparisonChange] = Field(max_length=8)
    check_suggestions: list[CheckSuggestion] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_entries(self):
        if not self.content.strip():
            raise ValueError("comparison content required")
        for items in (self.ranked_candidates, self.changes):
            ids = [item.listing_id for item in items]
            if len(ids) != len(set(ids)) or any(not item.reason.strip() for item in items):
                raise ValueError("comparison entries must be unique with reasons")
        if any(not text.strip() for item in self.ranked_candidates for text in item.uncertainties):
            raise ValueError("blank uncertainty")
        return self


class NominationResult(AssessmentModel):
    type: Literal["nomination"]
    candidates: list[ComparisonEntry] = Field(max_length=4)

    @model_validator(mode="after")
    def validate_candidates(self):
        ComparisonResult(type="comparison", content="nomination", ranked_candidates=self.candidates, changes=[])
        return self


def scope_ids(conn, task_id):
    return [row[0] for row in conn.execute(
        "SELECT DISTINCT s.listing_id FROM listing_snapshots s JOIN task_runs r ON r.run_id=s.run_id WHERE r.task_id=? ORDER BY s.listing_id", (task_id,)
    )]


def check_inputs(conn, review, request):
    revision = conn.execute("SELECT COALESCE(MAX(id),0) FROM task_preference_revisions WHERE task_id=?", (review["task_id"],)).fetchone()[0]
    if revision != review["preference_revision_id"] or request.task.preference_revision_id != revision:
        raise ReviewInputChangedError("requirements changed during history review")
    if request.task.id != review["task_id"] or evidence_signature(conn, review["task_id"]) != review["evidence_signature"] or request.evidence_signature != review["evidence_signature"]:
        raise ReviewInputChangedError("evidence changed during history review")


def linked_batches(conn, review_id, *, include_inputs=True):
    columns = "a.*" if include_inputs else "a.id, a.result_json, a.candidate_ids_json"
    rows = conn.execute(f"SELECT {columns} FROM research_assessments a WHERE a.id IN (SELECT assessment_id FROM review_assessment_links WHERE review_id=? UNION SELECT assessment_id FROM review_candidate_links WHERE review_id=?) ORDER BY a.id", (review_id, review_id)).fetchall()
    result = []
    for raw in rows:
        row = dict(raw)
        if not conn.execute("SELECT 1 FROM review_assessment_links WHERE review_id=? AND assessment_id=?", (review_id, row["id"])).fetchone():
            selected = {r[0] for r in conn.execute("SELECT listing_id FROM review_candidate_links WHERE review_id=? AND assessment_id=?", (review_id, row["id"]))}
            data = json.loads(row["result_json"])
            data["assessments"] = [a for a in data["assessments"] if a["listing_id"] in selected]
            row["result_json"] = json.dumps(data, ensure_ascii=False)
            row["candidate_ids_json"] = json.dumps([i for i in json.loads(row["candidate_ids_json"]) if i in selected])
        result.append(row)
    return result


def assessed_items(conn, review_id):
    return {item["listing_id"]: (row["id"], item) for row in linked_batches(conn, review_id, include_inputs=False)
            for item in json.loads(row["result_json"])["assessments"]}


def coverage(conn, review):
    scope = set(json.loads(review["scope_ids_json"]))
    assessed = set(assessed_items(conn, review["id"])) & scope
    return dict(scope_count=len(scope), reviewed_count=len(assessed), assessed_count=len(assessed),
                pending_count=len(scope - assessed), truncated=False)


def begin_review(conn, *, operation_id, request, result, now):
    task_id = request.task.id
    bound = dict(task_id=task_id, preference_revision_id=request.task.preference_revision_id,
                 evidence_signature=request.evidence_signature)
    check_inputs(conn, bound, request)
    standard_id = save_standard(conn, operation_id=operation_id, task_id=task_id,
                                criteria=result.criteria, request=request, now=now)
    existing = conn.execute("SELECT * FROM history_reviews WHERE operation_id=?", (operation_id,)).fetchone()
    if existing:
        if existing["input_json"] != request.model_dump_json() or existing["standard_id"] != standard_id:
            raise ValueError("operation already started a different history review")
        return existing["id"]
    previous = conn.execute("SELECT id FROM comparison_snapshots WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    ids = scope_ids(conn, task_id)
    review_id = conn.execute(
        "INSERT INTO history_reviews (task_id,operation_id,standard_id,preference_revision_id,evidence_signature,scope_ids_json,input_json,previous_comparison_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (task_id, operation_id, standard_id, request.task.preference_revision_id, request.evidence_signature,
         json.dumps(ids), request.model_dump_json(), previous[0] if previous else None, now),
    ).lastrowid
    # v5 already required independent per-candidate judgments, so its bound
    # snapshots are compatible. v6 adds a separate nomination phase, not new
    # assessment semantics. Older/unbound contracts never gain partial reuse.
    reused = set()
    _, dependencies = evidence_state(conn, task_id)
    for row in conn.execute("SELECT * FROM research_assessments WHERE task_id=? AND standard_id=? AND schema_version=? AND prompt_version IN (?,?,?,?,?,?,?,?,?,?) ORDER BY id DESC",
                            (task_id, standard_id, SCHEMA_VERSION, PROMPT_VERSION, "shopping-research-v13", "shopping-research-v12", "shopping-research-v11", "shopping-research-v10", "shopping-research-v9", "shopping-research-v8", "shopping-research-v7", "shopping-research-v6", "shopping-research-v5")):
        snapshot = json.loads(row["input_json"])
        members = {a["listing_id"] for a in json.loads(row["result_json"])["assessments"]}
        saved = json.loads(row["dependencies_json"])
        if snapshot.get("phase") != "review_batch" or snapshot.get("runtime_config") != request.runtime_config:
            continue
        if not saved and (row["prompt_version"] != PROMPT_VERSION or row["evidence_signature"] != request.evidence_signature):
            continue
        selected = {i for i in members & set(ids) - reused if
                    (saved.get(str(i)) == dependencies.get(str(i)) and str(i) in saved) or
                    (not saved and row["evidence_signature"] == request.evidence_signature)}
        if selected == members and selected:
            conn.execute("INSERT INTO review_assessment_links VALUES (?,?)", (review_id, row["id"]))
        elif selected:
            conn.executemany("INSERT INTO review_candidate_links VALUES (?,?,?)", [(review_id, i, row["id"]) for i in sorted(selected)])
        reused.update(selected)
    return review_id


def save_batch(conn, *, review, request, answer, now):
    check_inputs(conn, review, request)
    if request.phase != "review_batch" or answer.research is None:
        raise ValueError("review batch must return structured assessments")
    expected = set(request.allowed_listing_ids)
    actual = {a.listing_id for a in answer.research.assessments}
    pending = set(json.loads(review["scope_ids_json"])) - set(assessed_items(conn, review["id"]))
    if actual and not actual <= pending:
        for row in linked_batches(conn, review["id"]):
            members = {a["listing_id"] for a in json.loads(row["result_json"])["assessments"]}
            if (members == actual and row["operation_id"] == review["operation_id"]
                    and row["input_signature"] == signature(request.model_dump(mode="json"))
                    and json.loads(row["result_json"]) == answer.research.model_dump(mode="json")
                    and json.loads(row["candidate_ids_json"]) == answer.candidate_ids):
                return row["id"], False
    if not actual or actual != expected or not actual <= pending:
        raise ValueError("review batch must assess exactly its pending input candidates")
    by_id = {a.listing_id: a for a in answer.research.assessments}
    if not set(answer.candidate_ids) <= actual or any(by_id[i].conclusion == "not_met" for i in answer.candidate_ids):
        raise ValueError("batch shortlist must reference eligible assessments")
    batch_index = conn.execute("SELECT COALESCE(MAX(batch_index),0)+1 FROM research_assessments WHERE operation_id=?", (review["operation_id"],)).fetchone()[0]
    save_research(conn, operation_id=review["operation_id"], task_id=review["task_id"],
                  research=answer.research, request=request, now=now,
                  batch_index=batch_index, candidate_ids=answer.candidate_ids)
    assessment_id = conn.execute("SELECT id FROM research_assessments WHERE operation_id=? AND batch_index=?", (review["operation_id"], batch_index)).fetchone()[0]
    conn.execute("INSERT INTO review_assessment_links VALUES (?,?)", (review["id"], assessment_id))
    return assessment_id, True


def needs_nomination(conn, review_id):
    return bool(conn.execute("SELECT 1 FROM review_candidate_links WHERE review_id=? LIMIT 1", (review_id,)).fetchone())


def nomination_progress(conn, review):
    required = needs_nomination(conn, review["id"])
    total = (len(json.loads(review["scope_ids_json"])) + 19) // 20 if required else 0
    saved = conn.execute("SELECT COUNT(*) FROM review_nominations WHERE review_id=?", (review["id"],)).fetchone()[0]
    return dict(required=required, total_groups=total, completed_groups=saved, pending_groups=total-saved)


def nomination_context(conn, review, group_index):
    if not needs_nomination(conn, review["id"]) or coverage(conn, review)["pending_count"]:
        raise ValueError("nomination requires complete current assessments after partial reuse")
    ids = sorted(json.loads(review["scope_ids_json"]))
    if type(group_index) is not int or group_index < 0 or group_index*20 >= len(ids):
        raise ValueError("invalid nomination group")
    items = assessed_items(conn, review["id"])
    return dict(review_id=review["id"], group_index=group_index, assessments=[
        dict(assessment_id=items[i][0], **items[i][1]) for i in ids[group_index*20:(group_index+1)*20]])


def validate_nominees(entries, available):
    for entry in entries:
        item = available.get(entry.listing_id)
        if item is None or item["assessment_id"] != entry.assessment_id:
            raise ValueError("nomination references an assessment outside its current group")
        if item["conclusion"] == "not_met":
            raise ValueError("nomination cannot recommend hard-requirement failures")
        if not entry.uncertainties and any(j["status"] in {"UNKNOWN", "CONFLICT"} for j in item["judgments"]):
            raise ValueError("nomination must retain unresolved uncertainties")


def save_nomination(conn, *, review, request, result, now):
    check_inputs(conn, review, request)
    if request.phase != "nomination" or not isinstance(result, NominationResult):
        raise ValueError("nomination requires a structured nomination result")
    index = request.review_context.get("group_index")
    context = nomination_context(conn, review, index)
    if context != request.review_context or set(request.allowed_listing_ids) != {a["listing_id"] for a in context["assessments"]}:
        raise ValueError("nomination input differs from current server-bound group")
    validate_nominees(result.candidates, {a["listing_id"]: a for a in context["assessments"]})
    snapshot = request.model_dump_json()
    existing = conn.execute("SELECT * FROM review_nominations WHERE review_id=? AND group_index=?", (review["id"], index)).fetchone()
    if existing:
        if existing["input_json"] == snapshot and existing["result_json"] == result.model_dump_json():
            return existing["id"], False
        raise ValueError("conflicting duplicate nomination")
    row_id = conn.execute("INSERT INTO review_nominations(review_id,group_index,result_json,input_json,input_signature,prompt_version,created_at) VALUES (?,?,?,?,?,?,?)",
        (review["id"], index, result.model_dump_json(), snapshot, signature(request.model_dump(mode="json")), PROMPT_VERSION, now)).lastrowid
    return row_id, True


def comparison_context(conn, review):
    previous = None
    if review["previous_comparison_id"] is not None:
        previous = json.loads(conn.execute("SELECT result_json FROM comparison_snapshots WHERE id=?", (review["previous_comparison_id"],)).fetchone()[0])
    previous_ids = {c["listing_id"] for c in previous["ranked_candidates"]} if previous else set()
    proposals = set(previous_ids)
    nominations = []
    if needs_nomination(conn, review["id"]):
        if nomination_progress(conn, review)["pending_groups"]:
            raise ValueError("all nomination groups must complete before comparison")
        for row in conn.execute("SELECT group_index,result_json FROM review_nominations WHERE review_id=? ORDER BY group_index", (review["id"],)):
            entries = json.loads(row["result_json"])["candidates"]
            nominations.append(dict(group_index=row["group_index"], candidates=entries))
            proposals.update(item["listing_id"] for item in entries)
    else:
        for row in linked_batches(conn, review["id"], include_inputs=False):
            proposals.update(json.loads(row["candidate_ids_json"]))
    summaries = []
    for listing_id, (assessment_id, item) in assessed_items(conn, review["id"]).items():
        if listing_id in proposals:
            summaries.append(dict(assessment_id=assessment_id, **item))
    return dict(review_id=review["id"], coverage=coverage(conn, review), assessments=summaries,
                previous_comparison=previous, nominations=nominations)


def save_comparison(conn, *, review, request, result, now):
    check_inputs(conn, review, request)
    if request.phase != "comparison":
        raise ValueError("comparison requires the server-bound comparison input")
    counts = coverage(conn, review)
    if counts["pending_count"]:
        raise ValueError("incomplete history review cannot publish a complete comparison")
    context = comparison_context(conn, review)
    if context != request.review_context:
        raise ValueError("comparison dependencies changed")
    available = {a["listing_id"]: a for a in context["assessments"]}
    for entry in (*result.ranked_candidates, *result.changes):
        item = available.get(entry.listing_id)
        if item is None or item["assessment_id"] != entry.assessment_id:
            raise ValueError("comparison references an assessment outside its current inputs")
    if any(available[e.listing_id]["conclusion"] == "not_met" for e in result.ranked_candidates):
        raise ValueError("comparison cannot recommend candidates failing hard requirements")
    if any(not e.uncertainties and any(j["status"] in {"UNKNOWN", "CONFLICT"} for j in available[e.listing_id]["judgments"])
           for e in result.ranked_candidates):
        raise ValueError("comparison must retain unresolved candidate uncertainties")
    before = {c["listing_id"] for c in context["previous_comparison"]["ranked_candidates"]} if context["previous_comparison"] else set()
    after = {c.listing_id for c in result.ranked_candidates}
    expected = {(i, "entered") for i in after - before} | {(i, "exited") for i in before - after}
    if {(c.listing_id, c.kind) for c in result.changes} != expected:
        raise ValueError("comparison must explain every entering and exiting candidate")
    return conn.execute(
        "INSERT INTO comparison_snapshots (task_id,operation_id,review_id,standard_id,preference_revision_id,evidence_signature,previous_comparison_id,result_json,input_json,input_signature,schema_version,prompt_version,coverage_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (review["task_id"], review["operation_id"], review["id"], review["standard_id"], review["preference_revision_id"],
         review["evidence_signature"], review["previous_comparison_id"], result.model_dump_json(), request.model_dump_json(),
         signature(request.model_dump(mode="json")), SCHEMA_VERSION, PROMPT_VERSION, json.dumps(counts), now),
    ).lastrowid


def serialize_review(conn, row, revision, current_signature):
    return dict(id=row["id"], task_id=row["task_id"], operation_id=row["operation_id"], standard_id=row["standard_id"],
        evidence_signature=row["evidence_signature"],
        preference_revision_id=row["preference_revision_id"], state=row["state"], error_detail=row["error_detail"],
        stale=row["preference_revision_id"] != revision or row["evidence_signature"] != current_signature,
        coverage=coverage(conn, row), nomination_progress=nomination_progress(conn, row), created_at=row["created_at"])


def serialize_comparison(row, revision, current_signature):
    return dict(id=row["id"], task_id=row["task_id"], operation_id=row["operation_id"], review_id=row["review_id"],
        evidence_signature=row["evidence_signature"],
        standard_id=row["standard_id"], preference_revision_id=row["preference_revision_id"], previous_comparison_id=row["previous_comparison_id"],
        stale=row["preference_revision_id"] != revision or row["evidence_signature"] != current_signature,
        result=json.loads(row["result_json"]), coverage=json.loads(row["coverage_json"]), created_at=row["created_at"])
