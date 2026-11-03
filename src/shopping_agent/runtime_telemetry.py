"""Bounded, allowlisted metadata from CLI JSONL; never retain message/tool text."""
from __future__ import annotations

import json
import re


TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
                "output_tokens", "reasoning_output_tokens")
MAX_EVENT_BYTES = 2 * 1024 * 1024


def _failure_categories(value) -> set[str]:
    """Advisory categories only; never return upstream messages, URLs or IDs."""
    if not isinstance(value, dict):
        return set()
    text = " ".join(value[k][:4096] for k in ("message", "code") if isinstance(value.get(k), str)).lower()
    patterns = {
        "authentication": r"unauthorized|authentication|invalid.api.key|token.expired|\b401\b",
        "rate_limit": r"rate.limit|too.many.requests|insufficient.quota|\b429\b",
        "network": r"connection.(?:reset|refused|closed)|network|dns|tls|stream.disconnected|error.sending.request",
        "service": r"service.unavailable|internal.server.error|\b50[0234]\b",
    }
    return {kind for kind, pattern in patterns.items() if re.search(pattern, text)}


def parse_cli_telemetry(stream, *, process_finished: bool) -> dict:
    data = stream.read(MAX_EVENT_BYTES + 1)
    truncated = len(data) > MAX_EVENT_BYTES
    data = data[:MAX_EVENT_BYTES]
    event_count = malformed = unknown_events = 0
    terminals, usage, items, seen = [], None, {}, set()
    failures = set()
    for line in data.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError, RecursionError):
            malformed += 1
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            malformed += 1
            continue
        event_count += 1
        kind = event["type"]
        if kind in {"turn.failed", "error"}:
            failures.update(_failure_categories(event.get("error")))
            failures.update(_failure_categories(event))
        if kind in {"turn.completed", "turn.failed"}:
            terminals.append(kind)
            if kind == "turn.completed":
                raw = event.get("usage")
                if (isinstance(raw, dict) and all(type(raw.get(k)) is int and 0 <= raw[k] <= 2**63-1
                                                for k in ("input_tokens", "output_tokens"))
                        and all(k not in raw or (type(raw[k]) is int and 0 <= raw[k] <= 2**63-1)
                                for k in TOKEN_FIELDS)):
                    usage = {key: raw.get(key) for key in TOKEN_FIELDS}
        elif kind == "item.completed":
            item = event.get("item")
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or not 0 < len(item["id"]) <= 128 or not isinstance(item.get("type"), str)
                    or not re.fullmatch(r"[a-z_]{1,64}", item["type"])):
                malformed += 1
                continue
            key = (item["id"], item["type"])
            if item["type"] == "error":
                failures.update(_failure_categories(item))
            if key not in seen:
                seen.add(key)
                items[item["type"]] = items.get(item["type"], 0) + 1
        elif kind not in {"thread.started", "turn.started", "item.started", "item.updated", "error"}:
            unknown_events += 1
    complete = bool(process_finished and not truncated and not malformed and len(terminals) == 1)
    return dict(schema_version="codex-cli-events-v1", capture_status="complete" if complete else "partial",
                event_count=event_count, malformed_lines=malformed, truncated=truncated,
                unknown_event_count=unknown_events, terminal=terminals[0] if len(terminals) == 1 else None,
                tokens=usage if complete and terminals == ["turn.completed"] else None,
                failure_categories=sorted(failures),
                completed_item_types=items, model_identity=None, cost=None, tool_calls=None)


def summarize_telemetry(calls: list[dict]) -> dict:
    captures = [c.get("telemetry") for c in calls]
    complete = bool(calls and all(isinstance(c, dict) and c.get("capture_status") == "complete"
                                  and c.get("terminal") == "turn.completed" and c.get("tokens")
                                  for c in captures))
    totals = {key: sum(c["tokens"][key] for c in captures)
              if all(c["tokens"].get(key) is not None for c in captures) else None
              for key in TOKEN_FIELDS} if complete else None
    items = {}
    for capture in captures:
        if isinstance(capture, dict):
            for kind, count in capture.get("completed_item_types", {}).items():
                items[kind] = items.get(kind, 0) + count
    return dict(captured_calls=sum(isinstance(c, dict) for c in captures), total_calls=len(calls),
                complete=complete, tokens=totals, completed_item_types=items,
                model_identity=None, cost=None, tool_calls=None)
