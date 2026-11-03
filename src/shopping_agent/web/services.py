from __future__ import annotations

from shopping_agent.region_preference import region_preference

from pathlib import Path

from shopping_agent.candidate_context import (
    FIELD_SEMANTICS,
    build_candidate_evidence,
    build_candidate_index,
)
from shopping_agent.config import AppConfig
from shopping_agent.db import (
    connect,
    fetch_recent_platform_access_events,
    fetch_recent_tasks,
    fetch_task_count,
    fetch_task_report,
    initialize,
)
from shopping_agent.market_baseline import MarketBaselineOptions, build_market_baseline
from shopping_agent.tasks import build_task_summary
from shopping_agent.research_history import research_page, assessment_detail
from shopping_agent.task_history import task_summary, history_page
from shopping_agent.web.schemas import (
    CandidatePage,
    DebugSnapshot,
    ListingEvidence,
    MarketOverview,
    TaskDetail,
    TaskListPage,
    TaskListItem,
    ResearchHistory, AssessmentBatch, TaskHistory,
)


GLOBAL_ACCESS_EVENT_WARNING = (
    "Platform access events are global diagnostics and are not task-scoped."
)


class WorkbenchService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def list_tasks(self, limit: int = 50, offset: int = 0) -> TaskListPage:
        initialize(self.config.database_path)
        with connect(self.config.database_path) as conn:
            rows = fetch_recent_tasks(conn, limit=limit, offset=offset)
            total_count = fetch_task_count(conn)
            operation_states = {row["task_id"]: row["state"] for row in conn.execute(
                "SELECT task_id, state FROM operations WHERE id IN (SELECT MAX(id) FROM operations GROUP BY task_id)"
            ).fetchall()}
        items = [
            TaskListItem.model_validate(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "city": row["city"],
                    "status": row["status"],
                    "run_count": row["run_count"],
                    "report_count": row["report_count"],
                    "updated_at": row["updated_at"],
                    "operation_state": operation_states.get(row["id"]),
                }
            )
            for row in rows
        ]
        next_offset = offset + len(items)
        has_more = next_offset < total_count
        return TaskListPage.model_validate(
            {
                "items": items,
                "total_count": total_count,
                "returned_count": len(items),
                "truncated": has_more,
                "page": {
                    "offset": offset,
                    "limit": limit,
                    "has_more": has_more,
                    "next_offset": next_offset if has_more else None,
                },
            }
        )

    def get_task(self, task_id: int, *, include_research: bool = True, history_limit: int = 10) -> TaskDetail:
        initialize(self.config.database_path)
        with connect(self.config.database_path) as conn:
            conn.execute("BEGIN")
            summary = task_summary(conn, task_id, history_limit)
            if include_research:
                summary["research"] = research_page(conn, task_id)
        return TaskDetail.model_validate(summary)

    def get_task_history(self, task_id, limit=10, cursor=None):
        initialize(self.config.database_path)
        with connect(self.config.database_path) as conn:
            conn.execute("BEGIN")
            return TaskHistory.model_validate(history_page(conn, task_id, limit, cursor))

    def get_research_history(self, task_id, limit=10, cursor=None):
        initialize(self.config.database_path)
        with connect(self.config.database_path) as conn:
            conn.execute("BEGIN")
            return ResearchHistory.model_validate(research_page(conn, task_id, limit, cursor))

    def get_assessment(self, task_id, assessment_id):
        initialize(self.config.database_path)
        with connect(self.config.database_path) as conn:
            conn.execute("BEGIN")
            data = assessment_detail(conn, task_id, assessment_id)
        return AssessmentBatch.model_validate(data) if data is not None else None

    def get_candidates(
        self,
        task_id: int,
        limit: int,
        cursor: str | None,
    ) -> CandidatePage:
        # Candidate paging does not need to deserialize every historical assessment.
        initialize(self.config.database_path)
        with connect(self.config.database_path) as conn:
            has_runs = conn.execute("SELECT 1 FROM task_runs WHERE task_id = ? LIMIT 1", (task_id,)).fetchone()
            task_exists = conn.execute("SELECT 1 FROM research_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task_exists:
            raise ValueError(f"Research task not found: {task_id}")
        if not has_runs:
            if cursor:
                raise ValueError("Candidate scope changed; reload candidates.")
            return CandidatePage.model_validate({
                "scope": {"task_id": task_id, "run_ids": []},
                "scope_revision": f"empty-task-{task_id}",
                "field_semantics": FIELD_SEMANTICS,
                "deduplicated_count": 0, "returned_count": 0,
                "page": {"offset": 0, "limit": limit, "has_more": False, "next_cursor": None},
                "candidates": [],
            })
        result = build_candidate_index(
            self.config,
            task_id=task_id,
            limit=limit,
            cursor=cursor,
        )
        return CandidatePage.model_validate(result)

    def get_listing_evidence(self, task_id: int, listing_id: int) -> ListingEvidence:
        result = build_candidate_evidence(
            self.config,
            task_id=task_id,
            listing_ids=[listing_id],
        )
        return ListingEvidence.model_validate(result["candidates"][0])

    def get_market(self, task_id: int) -> MarketOverview:
        summary = build_task_summary(self.config, task_id)
        task = summary["task"]
        run_ids = [int(run["run_id"]) for run in summary["runs"]]
        if not run_ids:
            result = _empty_market_overview(
                goal=task["effective_goal"],
                target_city=region_preference(task["effective_goal"])["city"] or "",
            )
            candidates: list[dict] = []
        else:
            result = build_market_baseline(
                self.config,
                run_ids=run_ids,
                options=MarketBaselineOptions(
                    goal=task["effective_goal"],
                    target_city=region_preference(task["effective_goal"])["city"] or "",
                ),
            )
            candidates = build_candidate_index(
                self.config,
                task_id=task_id,
            )["candidates"]
        result.update(_market_context(summary, candidates))
        return MarketOverview.model_validate(result)

    def get_report_path(self, task_id: int, report_id: int) -> Path | None:
        initialize(self.config.database_path)
        with connect(self.config.database_path) as conn:
            row = fetch_task_report(conn, task_id, report_id)
        if row is None:
            return None
        reports_root = self.config.reports_dir.resolve()
        report_path = Path(row["path"]).resolve()
        if not report_path.is_relative_to(reports_root) or not report_path.is_file():
            return None
        return report_path

    def get_debug_snapshot(self, task_id: int) -> DebugSnapshot:
        summary = build_task_summary(self.config, task_id)
        with connect(self.config.database_path) as conn:
            access_events = [
                dict(row) for row in fetch_recent_platform_access_events(conn)
            ]
        return DebugSnapshot.model_validate(
            {
                "task": summary["task"],
                "runs": summary["runs"],
                "reports": [_report_metadata(report) for report in summary["reports"]],
                "search_coverage": summary["search_coverage"],
                "global_platform_access_events": {
                    "scope": "global",
                    "warning": GLOBAL_ACCESS_EVENT_WARNING,
                    "events": access_events,
                },
            }
        )


def _web_task_summary(summary: dict) -> dict:
    return {
        **summary,
        "reports": [_report_metadata(report) for report in summary["reports"]],
    }


def _report_metadata(report: dict) -> dict:
    return {key: value for key, value in report.items() if key != "path"}


def _market_context(summary: dict, candidates: list[dict]) -> dict:
    location_counts: dict[str, int] = {}
    status_counts = {
        "captured": 0,
        "blocked": 0,
        "not_captured": 0,
    }
    for candidate in candidates:
        location = str(candidate.get("location") or "").strip()
        if location:
            location_counts[location] = location_counts.get(location, 0) + 1
        status_counts[candidate["detail_status"]] += 1

    candidate_count = len(candidates)
    target_city = region_preference(summary["task"]["effective_goal"])["city"]
    target_city_count = location_counts.get(target_city, 0)
    listing_snapshot_count = sum(
        int(run["listing_snapshot_count"]) for run in summary["runs"]
    )
    duplicate_count = max(0, listing_snapshot_count - candidate_count)
    return {
        "geography": {
            "locations": [
                {"value": value, "count": count}
                for value, count in sorted(
                    location_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
            "target_city_count": target_city_count,
            "target_city_coverage_ratio": (
                round(target_city_count / candidate_count, 4)
                if candidate_count and target_city
                else None
            ),
        },
        "collection_coverage": {
            "collection_rounds": len(summary["runs"]),
            "listing_snapshot_count": listing_snapshot_count,
            "duplicate_count": duplicate_count,
            "duplicate_rate": (
                round(duplicate_count / listing_snapshot_count, 4)
                if listing_snapshot_count
                else None
            ),
            "captured_detail_count": status_counts["captured"],
            "blocked_detail_count": status_counts["blocked"],
            "not_captured_detail_count": status_counts["not_captured"],
            "detail_coverage_ratio": (
                round(status_counts["captured"] / candidate_count, 4)
                if candidate_count
                else None
            ),
        },
        "search_coverage": summary["search_coverage"],
    }


def _empty_market_overview(*, goal: str, target_city: str) -> dict:
    limitations = [
        "local collected active/listing snapshots only",
        "not sold-price evidence",
        "not cross-platform market coverage",
        "listing detail, OCR, condition, seller profile, and official specs still need model review",
    ]
    price_evidence_level = {
        "level": "missing_local_active_samples",
        "label": "no usable local active listing price samples",
        "sample_count": 0,
        "model_use": "collect more current comparable listings before price judgment",
        "limitations": limitations,
    }
    price_summary = {
        "count": 0,
        "min": None,
        "q1": None,
        "median": None,
        "q3": None,
        "max": None,
        "spread": None,
        "values": [],
    }
    return {
        "goal": goal,
        "target_city": target_city,
        "run_ids": [],
        "decision_owner": "llm",
        "is_final_recommendation": False,
        "source_scope": "local_candidate_pool_only",
        "price_evidence_level": price_evidence_level,
        "notes": [
            "This task has no attached runs, so there is no local market evidence.",
        ],
        "sample_policy": {
            "included": "priced candidates without obvious accessory, service, wrong-size, or suspicious-low-price noise flags",
            "excluded_noise_signal_keys": [
                "likely_accessory_or_parts",
                "likely_service_listing",
                "likely_non_target_size",
                "mentions_non_target_screen_size",
                "suspicious_low_price_for_target",
            ],
            "priced_candidate_count": 0,
            "unpriced_candidate_count": 0,
            "excluded_noise_sample_count": 0,
            "exclusion_summary": [],
        },
        "overall": {
            "candidate_count": 0,
            "priced_candidate_count": 0,
            "priced_clean_sample_count": 0,
            "priced_excluded_noise_sample_count": 0,
            "source_quality": "no_local_samples",
            "price_evidence_level": price_evidence_level,
            "price_summary": price_summary,
        },
        "spec_price_groups": [],
        "near_duplicate_groups": [],
        "suggested_llm_checks": [
            "Attach a search run before drawing market conclusions.",
        ],
    }
