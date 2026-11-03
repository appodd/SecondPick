from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from shopping_agent.config import AppConfig
from shopping_agent.goofish_prices import candidate_price_history
from shopping_agent.asking_prices import load_asking_quotes, apply_quote
from shopping_agent.monitor_evidence import load_monitor_evidence
from shopping_agent.db import (
    connect,
    fetch_detail_snapshots_for_run,
    fetch_latest_listing_snapshots_for_run,
    fetch_research_task,
    fetch_search_run,
    fetch_seller_items_for_listing_in_runs,
    fetch_task_runs,
    initialize,
)
from shopping_agent.extraction.listing_parser import parse_price_value
from shopping_agent.platforms.xianyu_detail_parser import parse_xianyu_detail_text


FIELD_SEMANTICS = {
    "search_description": (
        "null means repeated persisted text is omitted from this compact index; "
        "inspect search_description_status to distinguish the reason"
    ),
    "search_description_status": {
        "redundant_with_title": (
            "the persisted search description equals title, so the duplicate text is omitted"
        ),
        "missing": "no persisted search description is available",
        "distinct": "search_description contains distinct persisted search-card text",
    },
}


def build_candidate_index(
    config: AppConfig,
    *,
    task_id: int | None = None,
    run_ids: list[int] | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict:
    if limit is not None and not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100.")
    if cursor is not None and limit is None:
        raise ValueError("candidate cursor requires an explicit limit.")

    initialize(config.database_path)
    with connect(config.database_path) as conn:
        scope = _resolve_scope(conn, task_id=task_id, run_ids=run_ids)
        candidates, selected_rows = _load_scoped_candidates(conn, scope["run_ids"])

    scope_revision = _candidate_scope_revision(scope, selected_rows)
    offset = 0
    if cursor is not None:
        cursor_revision, offset = _decode_candidate_cursor(cursor)
        if cursor_revision != scope_revision:
            raise ValueError("candidate scope changed; restart candidate-index without --cursor.")
        if offset < 0 or offset >= len(candidates):
            raise ValueError("Invalid candidate cursor offset.")

    if limit is None:
        page_candidates = candidates
        has_more = False
        next_cursor = None
    else:
        page_candidates = candidates[offset : offset + limit]
        next_offset = offset + len(page_candidates)
        has_more = next_offset < len(candidates)
        next_cursor = (
            _encode_candidate_cursor(scope_revision, next_offset)
            if has_more
            else None
        )

    return {
        "scope": scope,
        "scope_revision": scope_revision,
        "field_semantics": FIELD_SEMANTICS,
        "deduplicated_count": len(candidates),
        "returned_count": len(page_candidates),
        "page": {
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "next_cursor": next_cursor,
        },
        "candidates": page_candidates,
    }


def _candidate_scope_revision(
    scope: dict,
    selected_rows: dict[int, object],
) -> str:
    payload = {
        "run_ids": scope["run_ids"],
        "selected_snapshots": [
            [listing_id, int(row["id"])]
            for listing_id, row in selected_rows.items()
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _encode_candidate_cursor(scope_revision: str, offset: int) -> str:
    payload = json.dumps(
        {"v": 1, "scope_revision": scope_revision, "offset": offset},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decode_candidate_cursor(cursor: str) -> tuple[str, int]:
    try:
        payload = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if set(payload) != {"v", "scope_revision", "offset"}:
            raise ValueError
        if payload["v"] != 1:
            raise ValueError
        scope_revision = payload["scope_revision"]
        offset = payload["offset"]
        if not isinstance(scope_revision, str) or not isinstance(offset, int):
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid candidate cursor.") from exc
    return scope_revision, offset


def build_candidate_evidence(
    config: AppConfig,
    *,
    listing_ids: list[int],
    task_id: int | None = None,
    run_ids: list[int] | None = None,
    raw_text_chars: int = 0,
) -> dict:
    unique_listing_ids = list(dict.fromkeys(listing_ids))
    if not unique_listing_ids:
        raise ValueError("At least one listing ID is required.")
    if raw_text_chars < 0:
        raise ValueError("raw_text_chars must be non-negative.")

    initialize(config.database_path)
    with connect(config.database_path) as conn:
        scope = _resolve_scope(conn, task_id=task_id, run_ids=run_ids)
        candidates, selected_rows = _load_scoped_candidates(conn, scope["run_ids"])
        index_by_listing = {item["listing_id"]: item for item in candidates}
        outside_ids = [listing_id for listing_id in unique_listing_ids if listing_id not in index_by_listing]
        if outside_ids:
            invalid = ", ".join(str(listing_id) for listing_id in outside_ids)
            raise ValueError(f"Listing IDs outside the candidate scope: {invalid}.")

        detail_by_listing = _load_scoped_details(conn, scope["run_ids"])
        result_candidates = [
            _serialize_evidence_candidate(
                conn,
                index_by_listing[listing_id],
                selected_rows[listing_id],
                detail_by_listing.get(listing_id),
                scope["run_ids"],
                raw_text_chars,
                scope["task_id"],
            )
            for listing_id in unique_listing_ids
        ]

    return {
        "scope": scope,
        "requested_listing_ids": unique_listing_ids,
        "returned_count": len(result_candidates),
        "candidates": result_candidates,
    }


def _resolve_scope(
    conn,
    *,
    task_id: int | None,
    run_ids: list[int] | None,
) -> dict:
    explicit_run_ids = list(dict.fromkeys(run_ids or []))
    if (task_id is None) == (not explicit_run_ids):
        raise ValueError("Specify exactly one candidate scope: --task-id or one or more --run-id values.")

    if task_id is not None:
        if fetch_research_task(conn, task_id) is None:
            raise ValueError(f"Research task {task_id} does not exist.")
        resolved_run_ids = [int(row["run_id"]) for row in fetch_task_runs(conn, task_id)]
        resolved_run_ids = list(dict.fromkeys(resolved_run_ids))
        if not resolved_run_ids:
            raise ValueError(f"Research task {task_id} has no attached runs.")
        return {"task_id": task_id, "run_ids": resolved_run_ids}

    for run_id in explicit_run_ids:
        if fetch_search_run(conn, run_id) is None:
            raise ValueError(f"Search run {run_id} does not exist.")
    return {"task_id": None, "run_ids": explicit_run_ids}


def _load_scoped_candidates(conn, run_ids: list[int]) -> tuple[list[dict], dict[int, object]]:
    occurrences_by_listing: dict[int, list[tuple[int, object]]] = {}
    listing_order: list[int] = []
    detail_status_by_listing: dict[int, str] = {}

    for run_id in run_ids:
        for row in fetch_latest_listing_snapshots_for_run(conn, run_id):
            listing_id = int(row["listing_id"])
            if listing_id not in occurrences_by_listing:
                listing_order.append(listing_id)
                occurrences_by_listing[listing_id] = []
            occurrences_by_listing[listing_id].append((run_id, row))
        for detail_row in fetch_detail_snapshots_for_run(conn, run_id):
            listing_id = int(detail_row["listing_id"])
            if not bool(detail_row["access_blocked"]):
                detail_status_by_listing[listing_id] = "captured"
            elif detail_status_by_listing.get(listing_id) != "captured":
                detail_status_by_listing[listing_id] = "blocked"

    selected_rows: dict[int, object] = {}
    monitor_evidence = load_monitor_evidence(conn, run_ids)
    quotes = load_asking_quotes(conn, run_ids)
    attributes = {}
    for run_id in run_ids:
        for row in fetch_detail_snapshots_for_run(conn,run_id):
            if not row['access_blocked'] and (row['listing_id'] not in attributes or row['id']>attributes[row['listing_id']]['id']):
                saved_text=_read_text_file(row['text_path']).split('为你推荐')[0]
                attributes[row['listing_id']]=dict(id=row['id'],values=_read_attributes_json(row['attributes_json']),
                    page_fields=dict(shipping='included',source='saved_detail_page_display',independently_verified=False) if re.search(r'(?:^|\n)包邮(?:\n|$)',saved_text) else {})
    candidates = []
    for listing_id in listing_order:
        occurrences = occurrences_by_listing[listing_id]
        _, latest_row = max(
            occurrences,
            key=lambda occurrence: (
                occurrence[1]["source_evidence_stage"] != "search_card",
                occurrence[1]["collected_at"] or "",
                int(occurrence[1]["id"]),
            ),
        )
        selected_rows[listing_id] = latest_row
        detail_status = detail_status_by_listing.get(listing_id, "not_captured")
        candidates.append(
            _serialize_index_candidate(
                latest_row,
                source_run_ids=sorted({run_id for run_id, _ in occurrences}),
                detail_status=detail_status,
            )
        )
        if listing_id in monitor_evidence:
            candidates[-1]['monitor_evidence'] = monitor_evidence[listing_id]
        apply_quote(candidates[-1],quotes.get(listing_id))
        candidates[-1]['market_attributes']=attributes.get(listing_id,{}).get('values',{})
        candidates[-1]['market_provenance']=dict(listing_snapshot_id=int(latest_row['id']),detail_snapshot_id=attributes.get(listing_id,{}).get('id'))
        candidates[-1]['market_page_fields']=attributes.get(listing_id,{}).get('page_fields',{})
        history = candidate_price_history(conn, listing_id, run_ids)
        candidates[-1]['price_history']=history
        if "external_source" in candidates[-1]:
            if history:
                candidates[-1]["external_source"]["price_observations"] = history
                candidates[-1]["external_source"]["price_observation_semantics"] = (
                    "Search-page asking prices, not sold prices or independent verification. "
                    "At most 20 records, newest import first; source timestamps retain their original timezone semantics. "
                    "Do not infer the latest source observation from import order. "
                    "Candidate current_quote selects the effective saved asking price; historical snapshots remain unchanged."
                )
    return candidates, selected_rows


def _load_scoped_details(conn, run_ids: list[int]) -> dict[int, dict]:
    occurrences: dict[int, list[object]] = {}
    for run_id in run_ids:
        for row in fetch_detail_snapshots_for_run(conn, run_id):
            occurrences.setdefault(int(row["listing_id"]), []).append(row)

    result = {}
    for listing_id, rows in occurrences.items():
        valid_rows = [row for row in rows if not bool(row["access_blocked"])]
        blocked_rows = [row for row in rows if bool(row["access_blocked"])]
        selected = (
            max(
                valid_rows,
                key=lambda row: (row["created_at"] or "", int(row["id"])),
            )
            if valid_rows
            else None
        )
        result[listing_id] = {
            "row": selected,
            "scoped_count": len(rows),
            "valid_scoped_count": len(valid_rows),
            "blocked_scoped_count": len(blocked_rows),
            "text": _read_text_file(selected["text_path"]) if selected is not None else "",
        }
    return result


def _serialize_evidence_candidate(
    conn,
    index_candidate: dict,
    search_row,
    detail_evidence: dict | None,
    run_ids: list[int],
    raw_text_chars: int,
    task_id: int | None = None,
) -> dict:
    listing_id = index_candidate["listing_id"]
    detail_row = detail_evidence["row"] if detail_evidence else None
    detail_text = detail_evidence["text"] if detail_row is not None else ""
    persisted_attributes = _read_attributes_json(
        detail_row["attributes_json"] if detail_row is not None else None
    )
    parsed_detail = _parse_detail_text(detail_text)
    dom_attributes = parsed_detail.attributes if parsed_detail is not None else {}
    attributes = persisted_attributes or dom_attributes
    if persisted_attributes:
        attributes_source = detail_row["attributes_source"]
    else:
        attributes_source = "detail_dom_fallback" if dom_attributes else None
    detail = None
    if detail_row is not None:
        description = parsed_detail.description if parsed_detail is not None else ""
        detail = {
            "snapshot_id": int(detail_row["id"]),
            "run_id": int(detail_row["run_id"]),
            "description": description,
            "attributes": attributes,
            "attributes_source": attributes_source,
            "evidence_source": (
                None
                if attributes_source is None
                else (
                    "detail_dom_fallback"
                    if attributes_source == "detail_dom_fallback"
                    else "seller_entered_attribute"
                )
            ),
            "independently_verified": False,
        }

    seller_fields = _seller_fields(search_row, parsed_detail)
    seller_items = _seller_items(conn, listing_id, run_ids)
    conflicts = _attribute_conflicts(attributes, dom_attributes, attributes_source)
    if detail_row is not None:
        detail_status = "captured"
    elif detail_evidence and detail_evidence["blocked_scoped_count"]:
        detail_status = "blocked"
    else:
        detail_status = "not_captured"
    return {
        **index_candidate,
        **_user_statements(conn, task_id, listing_id),
        "detail_status": detail_status,
        "detail": detail,
        "seller_fields": seller_fields,
        "seller_other_items": seller_items,
        "evidence_conflicts": conflicts,
        "collection_state": {
            "detail_snapshot_count": detail_evidence["scoped_count"] if detail_evidence else 0,
            "valid_detail_snapshot_count": (
                detail_evidence["valid_scoped_count"] if detail_evidence else 0
            ),
            "blocked_detail_snapshot_count": (
                detail_evidence["blocked_scoped_count"] if detail_evidence else 0
            ),
            "listing_lifetime_product_image_count": int(
                search_row["product_image_count"] or 0
            ),
            "listing_lifetime_downloaded_product_image_count": int(
                search_row["downloaded_product_image_count"] or 0
            ),
            "listing_lifetime_ocr_result_count": int(
                search_row["ocr_result_count"] or 0
            ),
        },
        "raw_text_excerpt": (
            detail_text[:raw_text_chars] if detail_row is not None and raw_text_chars else None
        ),
    }


def _user_statements(conn, task_id, listing_id):
    if task_id is None:
        return dict(user_statements=[], user_statement_count=0, user_statements_truncated=False)
    where = "s.task_id=? AND s.listing_id=? AND s.status='active' AND m.task_id=s.task_id AND m.role='user'"
    count = conn.execute(f"SELECT COUNT(*) FROM candidate_statement_current s JOIN conversation_messages m ON m.id=s.source_message_id WHERE {where}", (task_id, listing_id)).fetchone()[0]
    rows = conn.execute(f"SELECT s.*,m.content FROM candidate_statement_current s JOIN conversation_messages m ON m.id=s.source_message_id WHERE {where} ORDER BY s.id DESC LIMIT 20", (task_id, listing_id)).fetchall()
    return dict(user_statement_count=count, user_statements_truncated=count > 20, user_statements=[dict(
        id=row["id"], source_message_id=row["source_message_id"], kind=row["kind"], statement_text=row["content"],
        attribution="user_relayed_seller_claim" if row["kind"] == "seller_reply" else "user_observation",
        independently_verified=False, created_at=row["created_at"]) for row in reversed(rows)])


def _parse_detail_text(detail_text: str):
    if not detail_text:
        return None
    try:
        return parse_xianyu_detail_text(detail_text)
    except Exception:
        return None


def _read_attributes_json(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in decoded.items()
        if key and item is not None
    }


def _read_text_file(text_path: str | None) -> str:
    if not text_path:
        return ""
    path = Path(text_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _seller_fields(search_row, parsed_detail) -> dict:
    dom_fields = _parse_dom_seller_fields(
        parsed_detail.seller_stats if parsed_detail is not None else []
    )
    values = {}
    field_sources = {}
    for key in (
        "seller_credit_level",
        "seller_registered_days",
        "seller_sold_count",
        "seller_good_rate",
        "seller_realname_verified",
        "seller_reply_rate_24h",
    ):
        value = search_row[key]
        if key == "seller_realname_verified" and value is not None:
            value = bool(value)
        if value is not None:
            values[key] = value
            field_sources[key] = "db"
        else:
            values[key] = dom_fields.get(key)
            field_sources[key] = (
                "detail_dom_fallback" if values[key] is not None else "none"
            )
    used_sources = {source for source in field_sources.values() if source != "none"}
    if len(used_sources) > 1:
        data_source = "mixed"
    elif used_sources:
        data_source = next(iter(used_sources))
    else:
        data_source = "none"
    values["data_source"] = data_source
    values["field_sources"] = field_sources
    values["source"] = "platform_seller_field"
    values["independently_verified"] = False
    return values


def _parse_dom_seller_fields(lines: list[str]) -> dict:
    result = {}
    for line in lines or []:
        year_match = re.search(r"来闲鱼(\d+)年", line)
        if year_match:
            result["seller_registered_days"] = int(year_match.group(1)) * 365
        day_match = re.search(r"来闲鱼(\d+)天", line)
        if day_match:
            result["seller_registered_days"] = int(day_match.group(1))
        sold_match = re.search(r"卖出(\d+)件", line)
        if sold_match:
            result["seller_sold_count"] = int(sold_match.group(1))
        rate_match = re.search(r"好评率(\d+(?:\.\d+)?)%", line)
        if rate_match:
            result["seller_good_rate"] = f"{rate_match.group(1)}%"
    return result


def _seller_items(conn, listing_id: int, run_ids: list[int]) -> list[dict]:
    items = []
    seen = set()
    for row in fetch_seller_items_for_listing_in_runs(conn, listing_id, run_ids):
        item_id = row["item_id_ext"]
        identity = ("item_id", item_id) if item_id else (
            "title_url",
            row["title"] or "",
            row["url"] or "",
        )
        if identity in seen:
            continue
        seen.add(identity)
        items.append(
            {
                "item_id_ext": item_id,
                "title": row["title"],
                "url": row["url"],
            }
        )
    return items


def _attribute_conflicts(
    attributes: dict[str, str],
    dom_attributes: dict[str, str],
    attributes_source: str | None,
) -> list[dict]:
    if not attributes_source or attributes_source == "detail_dom_fallback":
        return []
    conflicts = []
    for field in set(attributes).intersection(dom_attributes):
        if attributes[field] != dom_attributes[field]:
            conflicts.append(
                {
                    "field": field,
                    "selected_value": attributes[field],
                    "selected_source": attributes_source,
                    "conflicting_value": dom_attributes[field],
                    "conflicting_source": "detail_dom_fallback",
                }
            )
    return sorted(conflicts, key=lambda item: item["field"])


def _serialize_index_candidate(
    row,
    *,
    source_run_ids: list[int],
    detail_status: str,
) -> dict:
    title = str(row["title"] or "")
    description = row["description"]
    if description is None or not str(description):
        compact_description = None
        description_status = "missing"
    elif str(description) == title:
        compact_description = None
        description_status = "redundant_with_title"
    else:
        compact_description = str(description)
        description_status = "distinct"

    return {
        "listing_id": int(row["listing_id"]),
        "source_run_ids": source_run_ids,
        "url": row["url"],
        "title": title,
        "search_description": compact_description,
        "search_description_status": description_status,
        "price_text": row["price_text"],
        "price_value": parse_price_value(row["price_text"]),
        "location": row["location"],
        "seller_name": row["seller_name"],
        "search_condition": row["search_condition"],
        "has_detail": detail_status == "captured",
        "detail_status": detail_status,
        **({"external_source": {
            "type": row["source_type"], "label": row["source_label"],
            "imported_at": row["collected_at"], "independently_verified": False,
            "source_observed_at": row["source_observed_at"],
            "evidence_stage": row["source_evidence_stage"] or "product_record",
            "source_round_id": row["source_round_id"],
            "seller_profile": json.loads(row["source_seller_json"] or "{}"),
        }} if row["source_type"] == "external_monitor" else {}),
    }
