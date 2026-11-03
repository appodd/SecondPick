"""Versioned model judgments; no purchasing heuristics or scoring in code."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SCHEMA_VERSION = "candidate-assessment-v2"
PROMPT_VERSION = "shopping-research-v14"


class AssessmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CheckSuggestion(AssessmentModel):
    listing_id: int = Field(gt=0, le=2**63-1)
    question: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_text(self):
        if not self.question.strip() or not self.reason.strip():
            raise ValueError("suggestion requires a question and reason")
        return self


class Criterion(AssessmentModel):
    criterion_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    description: str = Field(min_length=1, max_length=1000)
    priority: Literal["hard", "soft"]
    source_message_ids: list[int] = Field(default_factory=list, max_length=50)
    source_refs: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_source(self):
        if not self.description.strip() or any(i <= 0 for i in self.source_message_ids) or not (self.source_message_ids or self.source_refs):
            raise ValueError("criterion requires a description and requirement sources")
        if len(set(self.source_message_ids)) != len(self.source_message_ids):
            raise ValueError("duplicate criterion sources")
        import re
        if len(set(self.source_refs)) != len(self.source_refs) or any(
            not re.fullmatch(r"task_goal|preference_revision:[1-9][0-9]*", ref) for ref in self.source_refs
        ):
            raise ValueError("invalid requirement source references")
        return self


class CriterionJudgment(AssessmentModel):
    criterion_id: str
    status: Literal["MET", "NOT_MET", "UNKNOWN", "CONFLICT"]
    reason: str = Field(min_length=1, max_length=2000)
    source_type: Literal["seller_claim", "platform_display", "image_observation", "user_statement", "inference", "missing"]
    evidence_refs: list[str] = Field(max_length=50)

    @model_validator(mode="after")
    def validate_evidence(self):
        if not self.reason.strip():
            raise ValueError("judgment reason required")
        if self.status != "UNKNOWN" and not self.evidence_refs:
            raise ValueError("non-unknown judgments require references")
        if self.status == "CONFLICT" and len(set(self.evidence_refs)) < 2:
            raise ValueError("conflict requires at least two input references")
        if self.source_type == "missing" and self.status != "UNKNOWN":
            raise ValueError("missing information must remain unknown")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("duplicate evidence references")
        return self


class CandidateAssessment(AssessmentModel):
    listing_id: int = Field(gt=0)
    judgments: list[CriterionJudgment] = Field(min_length=1, max_length=50)
    conclusion: Literal["consider", "conditional", "not_met", "insufficient_evidence"]
    summary: str = Field(min_length=1, max_length=2000)


class ResearchResult(AssessmentModel):
    criteria: list[Criterion] = Field(min_length=1, max_length=50)
    assessments: list[CandidateAssessment] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_complete_judgments(self):
        ids = {c.criterion_id for c in self.criteria}
        if len(ids) != len(self.criteria):
            raise ValueError("criterion IDs must be unique")
        listing_ids = [a.listing_id for a in self.assessments]
        if len(set(listing_ids)) != len(listing_ids):
            raise ValueError("duplicate candidate assessments")
        hard = {c.criterion_id for c in self.criteria if c.priority == "hard"}
        for item in self.assessments:
            if not item.summary.strip():
                raise ValueError("candidate summary required")
            if {j.criterion_id for j in item.judgments} != ids or len(item.judgments) != len(ids):
                raise ValueError("each candidate must assess every criterion exactly once")
            if item.conclusion == "consider" and any(
                j.criterion_id in hard and j.status != "MET" for j in item.judgments
            ):
                raise ValueError("unresolved hard requirements cannot be declared satisfied")
            if item.conclusion in {"consider", "conditional"} and any(
                j.criterion_id in hard and j.status == "NOT_MET" for j in item.judgments
            ):
                raise ValueError("failed hard requirements contradict a positive conclusion")
            if item.conclusion == "not_met" and not any(
                j.criterion_id in hard and j.status == "NOT_MET" for j in item.judgments
            ):
                raise ValueError("unknown evidence alone cannot establish failed requirements")
        return self


def signature(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def input_refs(request) -> dict[str, dict]:
    """References address immutable prompt excerpts, not independently verified facts."""
    refs = {}
    for kind, items in (("card", request.candidates), ("detail", request.evidence)):
        for item in items:
            data = item.model_dump(mode="json")
            refs[f"{kind}:{item.listing_id}:{signature(data)[:16]}"] = data
            if kind == "detail":
                refs.update(statement_refs(data))
    from shopping_agent.project_visual import visual_refs
    refs.update(visual_refs(request.model_dump(mode='json')))
    return refs


def statement_refs(data):
    """Each bound statement has its own immutable reference, including conflicts."""
    try:
        payload = json.loads(data["data"].get("evidence_json", "{}"))
    except (ValueError, TypeError):
        return {}
    refs = {}
    for statement in payload.get("user_statements", []) if isinstance(payload, dict) else []:
        excerpt = dict(task_id=data["task_id"], listing_id=data["listing_id"],
                       data={"statement_id": statement["id"], "source_message_id": statement["source_message_id"],
                             "evidence_json": json.dumps(statement, ensure_ascii=False)})
        refs[f"statement:{data['listing_id']}:{signature(excerpt)[:16]}"] = excerpt
    return refs


def evidence_signature(conn, task_id: int) -> str:
    return evidence_state(conn, task_id)[0]


def evidence_state(conn, task_id: int) -> tuple[str, dict[str, str]]:
    """Return the publication guard plus independent local-review dependencies.

    Any saved evidence change invalidates the whole-task guard. Include the
    saved detail text files used by candidate_context, but do not read raw images.
    """
    run_sql = "SELECT run_id FROM task_runs WHERE task_id = ?"
    listing_sql = f"SELECT listing_id FROM listing_snapshots WHERE run_id IN ({run_sql})"
    queries = {
        "task_runs": "task_id = ?",
        "listing_snapshots": f"run_id IN ({run_sql})",
        "detail_snapshots": f"listing_id IN ({listing_sql}) AND run_id IN ({run_sql})",
        "listings": f"id IN ({listing_sql})",
        "media_assets": f"listing_id IN ({listing_sql})",
        "ocr_results": f"media_asset_id IN (SELECT id FROM media_assets WHERE listing_id IN ({listing_sql}))",
        "seller_items": f"seller_listing_id IN ({listing_sql}) AND source_run_id IN ({run_sql})",
        "reference_evidence": f"run_id IN ({run_sql})",
    }
    data = {}
    for table, where in queries.items():
        data[table] = [dict(row) for row in conn.execute(
            f"SELECT * FROM {table} WHERE {where} ORDER BY id", (task_id,) * where.count("?")
        )]
    # External provenance and asking-price observations are visible evidence.
    # Only add nonempty streams so tasks without monitor data keep their
    # existing signatures. New observations invalidate only their owner.
    monitor_records = [dict(row) for row in conn.execute(
        "SELECT * FROM monitor_import_records WHERE task_id=? ORDER BY snapshot_id", (task_id,))]
    for row in monitor_records:
        if row.get('evidence_json') == '{}':
            row.pop('evidence_json', None)  # Additive migration is not new evidence.
    price_observations = [dict(row) for row in conn.execute(
        f"SELECT * FROM monitor_price_observations WHERE task_id=? AND listing_id IN ({listing_sql}) ORDER BY id",
        (task_id, task_id))]
    if monitor_records:
        data["monitor_import_records"] = monitor_records
    if price_observations:
        data["monitor_price_observations"] = price_observations
    data["candidate_statements"] = [dict(row) for row in conn.execute(
        f"SELECT s.id,s.task_id,s.listing_id,s.source_message_id,s.kind,s.created_at,m.content FROM candidate_statement_current s JOIN conversation_messages m ON m.id=s.source_message_id WHERE s.task_id=? AND s.status='active' AND s.listing_id IN ({listing_sql}) AND m.task_id=s.task_id AND m.role='user' ORDER BY s.id", (task_id, task_id))]
    changes = [dict(row) for row in conn.execute("SELECT c.* FROM candidate_statement_changes c JOIN candidate_statements s ON s.id=c.statement_id WHERE s.task_id=? ORDER BY c.id", (task_id,))]
    if changes:
        data["statement_changes"] = changes
    data["detail_text_signatures"] = {}
    for row in data["detail_snapshots"]:
        path = row.get("text_path")
        if not path or row["access_blocked"]:
            continue
        try:
            digest = hashlib.sha256()
            with Path(path).open("rb") as stream:
                for chunk in iter(lambda: stream.read(65536), b""):
                    digest.update(chunk)
            data["detail_text_signatures"][path] = digest.hexdigest()
        except OSError:
            data["detail_text_signatures"][path] = None
    # Partition dependencies by candidate, not by cited refs: newly saved detail
    # evidence must invalidate a judgment that previously reported UNKNOWN too.
    # Keep the task-wide signature unchanged for publication/scope protection.
    candidates = {str(row["listing_id"]): {} for row in data["listing_snapshots"]}
    media_owners = {row["id"]: str(row["listing_id"]) for row in data["media_assets"]}
    for table, key in (("listing_snapshots", "listing_id"), ("detail_snapshots", "listing_id"),
                       ("listings", "id"), ("media_assets", "listing_id"),
                       ("seller_items", "seller_listing_id"), ("candidate_statements", "listing_id")):
        for row in data[table]:
            candidates[str(row[key])].setdefault(table, []).append(row)
    snapshot_owners = {row["id"]: str(row["listing_id"]) for row in data["listing_snapshots"]}
    for row in monitor_records:
        owner = snapshot_owners.get(row["snapshot_id"])
        if owner in candidates:
            candidates[owner].setdefault("monitor_import_records", []).append(row)
    for row in price_observations:
        candidates[str(row["listing_id"])].setdefault("monitor_price_observations", []).append(row)
    for change in changes:
        for listing_id in {change["old_listing_id"], change["new_listing_id"]}:
            if str(listing_id) in candidates:
                candidates[str(listing_id)].setdefault("statement_changes", []).append(change)
    for row in data["ocr_results"]:
        candidates[media_owners[row["media_asset_id"]]].setdefault("ocr_results", []).append(row)
    for value in candidates.values():
        value["detail_text_signatures"] = {
            row["text_path"]: data["detail_text_signatures"][row["text_path"]]
            for row in value.get("detail_snapshots", [])
            if row.get("text_path") in data["detail_text_signatures"] and not row["access_blocked"]
        }
    return signature(data), {key: signature(value) for key, value in candidates.items()}


def save_research(conn, *, operation_id, task_id, research, request, now, batch_index=0, candidate_ids=()):
    """Called inside answer publication's existing transaction."""
    research = ResearchResult.model_validate(research.model_dump())
    if request is None or request.task.id != task_id or not request.evidence_signature:
        raise ValueError("research requires a server-bound input snapshot")
    current_signature, dependencies = evidence_state(conn, task_id)
    if current_signature != request.evidence_signature:
        raise ValueError("saved evidence changed during analysis; retry with current evidence")
    from shopping_agent.project_visual import validate_judgments
    validate_judgments(request,research)
    refs = input_refs(request)
    for item in research.assessments:
        if item.listing_id not in request.allowed_listing_ids:
            raise ValueError("assessment candidate is outside input scope")
        for judgment in item.judgments:
            for ref in judgment.evidence_refs:
                if ref not in refs or refs[ref]["listing_id"] != item.listing_id:
                    raise ValueError("evidence reference is missing or belongs to another candidate")
    standard_id = save_standard(conn, operation_id=operation_id, task_id=task_id,
                                criteria=research.criteria, request=request, now=now)
    snapshot = request.model_dump(mode="json")
    # Ordinary chat can use broader conversational context. Only the independent
    # local review contract permits candidate-level dependency validity.
    bound_dependencies = {str(a.listing_id): dependencies[str(a.listing_id)] for a in research.assessments} if request.phase == "review_batch" else {}
    conn.execute(
        "INSERT INTO research_assessments (task_id, operation_id, standard_id, result_json, input_json, input_signature, evidence_signature, schema_version, prompt_version, created_at, batch_index, candidate_ids_json, dependencies_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, operation_id, standard_id, research.model_dump_json(), json.dumps(snapshot, ensure_ascii=False),
         signature(snapshot), request.evidence_signature, SCHEMA_VERSION, PROMPT_VERSION, now, batch_index, json.dumps(list(candidate_ids)), json.dumps(bound_dependencies)),
    )
    return standard_id


def save_standard(conn, *, operation_id, task_id, criteria, request, now):
    sources = {row["id"] for row in conn.execute(
        "SELECT id FROM conversation_messages WHERE task_id = ? AND role = 'user'", (task_id,)
    )}
    for criterion in criteria:
        if not set(criterion.source_message_ids) <= sources:
            raise ValueError("criterion source is not a user message in this task")
        for ref in criterion.source_refs:
            supplied = request.requirement_sources.get(ref)
            if not isinstance(supplied, dict):
                raise ValueError("requirement source was not supplied in the input")
            if ref == "task_goal":
                row = conn.execute("SELECT goal FROM research_tasks WHERE id=?", (task_id,)).fetchone()
                if row is None or supplied.get("text") != row["goal"] or request.task.original_goal != row["goal"]:
                    raise ValueError("original task goal source changed")
            else:
                revision_id = int(ref.split(":")[1])
                row = conn.execute("SELECT effective_goal FROM task_preference_revisions WHERE id=? AND task_id=?", (revision_id, task_id)).fetchone()
                if row is None or revision_id > request.task.preference_revision_id or supplied.get("text") != row["effective_goal"]:
                    raise ValueError("preference source belongs to another task or version")
    criteria_json = json.dumps([c.model_dump() for c in criteria], ensure_ascii=False, sort_keys=True)
    revision = request.task.preference_revision_id
    existing = conn.execute(
        "SELECT * FROM requirement_standards WHERE task_id = ? AND preference_revision_id = ?", (task_id, revision)
    ).fetchone()
    canonical_existing = json.dumps([Criterion.model_validate(c).model_dump() for c in json.loads(existing["criteria_json"])], ensure_ascii=False, sort_keys=True) if existing else None
    if existing and canonical_existing != criteria_json:
        raise ValueError("an existing requirement standard cannot be silently rewritten")
    if existing:
        standard_id = existing["id"]
    else:
        standard_id = conn.execute(
            "INSERT INTO requirement_standards (task_id, preference_revision_id, criteria_json, operation_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, revision, criteria_json, operation_id, now),
        ).lastrowid
    return standard_id


def read_standards(conn, task_id):
    revision = conn.execute("SELECT COALESCE(MAX(id), 0) FROM task_preference_revisions WHERE task_id = ?", (task_id,)).fetchone()[0]
    standards = [dict(row) for row in conn.execute("SELECT * FROM requirement_standards WHERE task_id = ? ORDER BY id", (task_id,))]
    for item in standards:
        item["criteria"] = json.loads(item.pop("criteria_json"))
        item["stale"] = item["preference_revision_id"] != revision
    return standards


def serialize_assessment(row, revision, current_signature, dependencies=None):
    item = dict(row)
    item["candidate_ids"] = json.loads(item.pop("candidate_ids_json"))
    item["result"] = json.loads(item.pop("result_json"))
    used_refs = {ref for candidate in item["result"]["assessments"]
                 for judgment in candidate["judgments"] for ref in judgment["evidence_refs"]}
    snapshot = item.pop("input_json")
    refs = input_refs_from_snapshot(json.loads(snapshot)) if used_refs else {}
    item["evidence_refs"] = {ref: refs[ref] for ref in used_refs if ref in refs}
    saved_dependencies = json.loads(item.pop("dependencies_json", "{}"))
    item["candidate_stale"] = {
        str(candidate["listing_id"]): item["preference_revision_id"] != revision or (
            saved_dependencies[str(candidate["listing_id"])] != dependencies.get(str(candidate["listing_id"]))
            if dependencies is not None and str(candidate["listing_id"]) in saved_dependencies
            else item["evidence_signature"] != current_signature
        ) for candidate in item["result"]["assessments"]
    }
    item["stale"] = any(item["candidate_stale"].values()) or item["preference_revision_id"] != revision or (
        not item["result"]["assessments"] and item["evidence_signature"] != current_signature
    )
    item["validity_signature"] = current_signature
    item["execution_state"] = "succeeded"
    return item


def input_refs_from_snapshot(snapshot):
    # Keep retrieval independent of runtime imports and their result schemas.
    refs = {}
    for kind, key in (("card", "candidates"), ("detail", "evidence")):
        for data in snapshot[key]:
            refs[f"{kind}:{data['listing_id']}:{signature(data)[:16]}"] = data
            if kind == "detail":
                refs.update(statement_refs(data))
    from shopping_agent.project_visual import visual_refs
    refs.update(visual_refs(snapshot))
    return refs
