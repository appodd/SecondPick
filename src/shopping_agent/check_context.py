"""Bounded organizational context; never a source of candidate facts."""
import hashlib
import json


class CheckContextChangedError(ValueError):
    pass


def check_signature(conn, task_id):
    from shopping_agent.check_reviews import latest_review, review_basis, review_dto
    # Append-only revision IDs also detect A -> B -> A changes. Include all
    # in-scope items, even those outside the bounded prompt window.
    checks = list(conn.execute(
        "SELECT q.* "
        "FROM candidate_check_current q WHERE q.task_id=? AND EXISTS "
        "(SELECT 1 FROM listing_snapshots s JOIN task_runs t ON t.run_id=s.run_id "
        "WHERE t.task_id=q.task_id AND s.listing_id=q.listing_id) ORDER BY q.id", (task_id,)))
    reviews = {q["id"]: latest_review(conn, q["id"]) for q in checks}
    basis = review_basis(conn, task_id) if any(r is not None for r in reviews.values()) else None
    rows = [(q["id"], q["revision_id"], q["effective_state"], q["evidence_current"],
             reviews[q["id"]]["id"] if reviews[q["id"]] else 0,
             review_dto(conn, reviews[q["id"]], q, basis)["status"] if reviews[q["id"]] else None) for q in checks]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def require_current_checks(conn, task_id, expected):
    if expected and check_signature(conn, task_id) != expected:
        raise CheckContextChangedError("待核实清单已变化，请按当前清单重试分析。")


def follow_up_context(conn, task_id, listing_ids, refs):
    """At most 20 questions total, scoped to actually supplied candidates.

    No linked text is copied here: only a current statement already supplied as
    evidence may be addressed by its existing immutable reference.
    """
    ids = sorted(set(listing_ids))
    if not ids:
        return dict(items=[], total_count=0, dismissed_count=0, truncated=False)
    marks = ",".join("?" for _ in ids)
    where = f"task_id=? AND listing_id IN ({marks})"
    args = (task_id, *ids)
    counts = {row[0]: row[1] for row in conn.execute(
        f"SELECT effective_state,COUNT(*) FROM candidate_check_current WHERE {where} GROUP BY effective_state", args)}
    rows = conn.execute(f"SELECT * FROM candidate_check_current WHERE {where} AND effective_state!='dismissed' ORDER BY id DESC LIMIT 20", args).fetchall()
    sources = {(data["listing_id"], data["data"]["statement_id"]): ref
               for ref, data in refs.items() if ref.startswith("statement:")}
    items = []
    from shopping_agent.check_reviews import latest_review, review_basis, review_dto
    reviews = {row["id"]: latest_review(conn, row["id"]) for row in rows}
    basis = review_basis(conn, task_id) if any(r is not None for r in reviews.values()) else None
    for row in rows:
        current = bool(row["evidence_current"])
        source_ref = sources.get((row["listing_id"], row["statement_id"])) if current else None
        item = dict(id=row["id"], listing_id=row["listing_id"], revision_id=row["revision_id"],
            question=row["question"], note=row["note"], state=row["effective_state"],
            needs_recheck=row["state"] == "evidence_linked" and not current,
            linked_evidence_ref=source_ref, source_status=("current_in_input" if source_ref else
                "current_not_in_input" if current else "invalid" if row["state"] == "evidence_linked" else "none"),
            independently_verified=False)
        review = review_dto(conn, reviews[row["id"]], row, basis)
        if review:
            item["user_review"] = dict(id=review["id"], status=review["status"], independently_verified=False)
            if review["status"] == "current":
                source_refs = [sources[(row["listing_id"], s["statement_id"])] for s in review["sources"] if s["current"] and (row["listing_id"], s["statement_id"]) in sources]
                item["user_review"].update(outcome=review["outcome"], summary=review["summary"], source_refs=source_refs,
                    unavailable_source_count=len(review["sources"])-len(source_refs))
        items.append(item)
    total = sum(n for state, n in counts.items() if state != "dismissed")
    return dict(items=items, total_count=total, dismissed_count=counts.get("dismissed", 0), truncated=total>len(items))
