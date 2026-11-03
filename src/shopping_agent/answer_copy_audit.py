"""Read-only prose lint for saved replay outputs; no semantic quality score."""
from __future__ import annotations

import re

from shopping_agent.assessment import signature


_PROSE_FIELDS = {"content", "analysis", "summary", "reason", "risk", "uncertainties"}
_INTERNAL = re.compile(
    r"(?<![A-Za-z0-9_])(?:assessment_id|listing_id|criterion_id|source_type|evidence_refs|review_context|"
    r"scope_coverage|candidate_ids|review_batch|nomination|preference_revision_id)(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])(?:card|detail|statement):[1-9][0-9]*:[0-9a-f]{8,64}(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])(?:NOT_MET|MET|UNKNOWN|CONFLICT|insufficient_evidence|not_met)(?![A-Za-z0-9_])"
    r"|服务(?:提供的)?覆盖记录|本次比较输入|本组提名|输入签名"
)


def prose_findings(value, path: str = "$", field: str = "") -> list[dict]:
    """Scan new explanatory prose, leaving protocol IDs/references untouched."""
    if isinstance(value, dict):
        return [finding for key, item in value.items()
                for finding in prose_findings(item, f"{path}.{key}", key)]
    if isinstance(value, list):
        return [finding for index, item in enumerate(value)
                for finding in prose_findings(item, f"{path}[{index}]", field)]
    if isinstance(value, str) and field in _PROSE_FIELDS:
        return [dict(path=path, token=match.group(),
                     excerpt=value[max(0, match.start()-35):match.end()+65])
                for match in _INTERNAL.finditer(value)]
    return []


def audit_answer_copy(report: dict) -> dict:
    if report.get("mode") not in {"real_model_service_journey", "real_model_correction_probes"}:
        raise ValueError("expected a saved real-model journey or correction report")
    calls = report.get("calls")
    if not isinstance(calls, list) or not calls:
        raise ValueError("expected nonempty saved calls")
    records = []
    for index, call in enumerate(calls):
        if signature(call["request"]) != call["request_signature"]:
            raise ValueError("saved request signature mismatch")
        returned = call.get("state") == "returned" and isinstance(call.get("result"), dict)
        records.append(dict(call_index=index, phase=call["phase"], evaluated=returned,
                            findings=prose_findings(call["result"]) if returned else []))
    findings = sum(len(row["findings"]) for row in records)
    complete = (report.get("state") == "checks_passed_manual_review_pending"
                and report.get("calls_count") == len(calls) and all(row["evaluated"] for row in records))
    return dict(mode="answer_copy_audit_no_model_calls", calls=0, checker_version="shopper-copy-lint-v1",
                source_signature=signature(report), source_prompt_version=report["prompt_version"],
                source_state=report["state"], source_model_calls=len(calls), complete=complete,
                state="incomplete" if not complete else "copy_findings" if findings else "checks_passed",
                finding_count=findings, records=records, quality_verified=False, manual_review="pending",
                limitations=["fixed token patterns, not exhaustive prose review", "no semantic or citation-support audit",
                             "saved prompt version recorded, not revalidated against current template",
                             "technical user questions and literal quotations require manual interpretation"])
