from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_detail_snapshot,
    add_listing_snapshot,
    add_platform_access_event,
    attach_run_to_task,
    connect,
    create_query,
    create_research_task,
    create_search_run,
    initialize,
    upsert_listing,
)
from shopping_agent.web.services import WorkbenchService
from shopping_agent.web.schemas import TaskListItem


@dataclass(frozen=True)
class SeededWebConfig:
    config: AppConfig
    task_id: int
    captured_listing_id: int
    outside_listing_id: int


@pytest.mark.parametrize(("field", "value"), [("id", "7"), ("run_count", "1")])
def test_task_list_item_uses_strict_numeric_validation(field: str, value: str) -> None:
    payload = {
        "id": 7,
        "title": "R9000P",
        "city": "Shanghai",
        "status": "active",
        "run_count": 1,
        "report_count": 0,
        "updated_at": "2026-09-16T00:00:00+00:00",
    }
    assert TaskListItem.model_validate(payload).id == 7

    payload[field] = value
    with pytest.raises(ValidationError):
        TaskListItem.model_validate(payload)


@pytest.fixture
def seeded_web_config(tmp_path: Path) -> SeededWebConfig:
    config = AppConfig(database_path=tmp_path / "workbench.sqlite")
    initialize(config.database_path)
    detail_text = tmp_path / "detail.txt"
    detail_text.write_text("captured detail", encoding="utf-8")

    with connect(config.database_path) as conn:
        task_id = create_research_task(
            conn,
            title="R9000P",
            goal="Find an R9000P 4060",
            city="Shanghai",
        )
        run_id = create_search_run(conn, goal="R9000P 4060", city="Shanghai")
        create_query(conn, run_id=run_id, platform="xianyu", query_text="R9000P 4060")
        attach_run_to_task(conn, task_id=task_id, run_id=run_id)

        captured_listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://example.test/captured",
        )
        search_only_listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://example.test/search-only",
        )
        outside_listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://example.test/outside",
        )
        add_listing_snapshot(
            conn,
            listing_id=captured_listing_id,
            run_id=run_id,
            title="R9000P 4060",
            description="Captured candidate",
            price_text="6188",
            location="Shanghai",
            seller_name="Seller A",
            seller_credit_level="excellent",
        )
        add_listing_snapshot(
            conn,
            listing_id=search_only_listing_id,
            run_id=run_id,
            title="R9000P search only",
            description="R9000P search only",
            price_text="6500",
            location="Shanghai",
            seller_name="Seller B",
        )
        outside_run_id = create_search_run(conn, goal="outside", city="Beijing")
        add_listing_snapshot(
            conn,
            listing_id=outside_listing_id,
            run_id=outside_run_id,
            title="Outside candidate",
        )
        add_detail_snapshot(
            conn,
            captured_listing_id,
            run_id,
            "https://example.test/captured",
            "Captured detail",
            tmp_path / "detail.png",
            tmp_path / "detail.html",
            detail_text,
            tmp_path / "detail.links.txt",
            tmp_path / "detail.images.txt",
            0,
            0,
            False,
            attributes_json=json.dumps({"condition": "used"}),
            attributes_source="xianyu_api_item_labels",
        )
        add_platform_access_event(
            conn,
            platform="xianyu",
            operation="search",
            target="R9000P 4060",
            attempted_at="2026-09-16T00:00:00+00:00",
        )
        conn.commit()

    return SeededWebConfig(
        config=config,
        task_id=task_id,
        captured_listing_id=captured_listing_id,
        outside_listing_id=outside_listing_id,
    )


def test_workbench_service_returns_scoped_candidates_and_evidence(
    seeded_web_config: SeededWebConfig,
) -> None:
    service = WorkbenchService(seeded_web_config.config)

    candidates = service.get_candidates(
        task_id=seeded_web_config.task_id,
        limit=50,
        cursor=None,
    )
    evidence = service.get_listing_evidence(
        task_id=seeded_web_config.task_id,
        listing_id=seeded_web_config.captured_listing_id,
    )

    assert candidates.deduplicated_count == 2
    assert candidates.returned_count == 2
    assert candidates.candidates[0].source_run_ids
    assert candidates.candidates[1].search_description_status == "redundant_with_title"
    assert evidence.listing_id == seeded_web_config.captured_listing_id
    assert evidence.detail_status == "captured"
    assert evidence.detail is not None
    assert evidence.detail.attributes_source == "xianyu_api_item_labels"
    assert evidence.detail.independently_verified is False
    assert evidence.seller_fields.source == "platform_seller_field"


def test_workbench_service_rejects_listing_outside_task_scope(
    seeded_web_config: SeededWebConfig,
) -> None:
    service = WorkbenchService(seeded_web_config.config)

    with pytest.raises(ValueError, match="outside the candidate scope"):
        service.get_listing_evidence(
            task_id=seeded_web_config.task_id,
            listing_id=seeded_web_config.outside_listing_id,
        )


def test_workbench_service_returns_task_market_and_labeled_debug_snapshot(
    seeded_web_config: SeededWebConfig,
) -> None:
    service = WorkbenchService(seeded_web_config.config)

    tasks = service.list_tasks()
    task = service.get_task(seeded_web_config.task_id)
    market = service.get_market(seeded_web_config.task_id)
    debug = service.get_debug_snapshot(seeded_web_config.task_id)

    assert tasks.items[0].id == seeded_web_config.task_id
    assert tasks.total_count == 1
    assert tasks.returned_count == 1
    assert tasks.truncated is False
    assert task.task.effective_goal == "Find an R9000P 4060"
    assert market.run_ids == [task.runs[0].run_id]
    assert market.overall.candidate_count == 2
    assert market.geography.locations[0].value == "Shanghai"
    assert market.geography.locations[0].count == 2
    # A legacy task city is metadata of unknown provenance, not an implicit preference.
    assert market.target_city == ""
    assert market.geography.target_city_count == 0
    assert market.geography.target_city_coverage_ratio is None
    assert market.collection_coverage.collection_rounds == 1
    assert market.collection_coverage.listing_snapshot_count == 2
    assert market.collection_coverage.duplicate_count == 0
    assert market.collection_coverage.duplicate_rate == 0.0
    assert market.collection_coverage.captured_detail_count == 1
    assert market.collection_coverage.blocked_detail_count == 0
    assert market.collection_coverage.not_captured_detail_count == 1
    assert market.collection_coverage.detail_coverage_ratio == 0.5
    assert market.search_coverage.status == task.search_coverage.status
    assert market.search_coverage.runs[0].new_unique_count == 2
    assert debug.task.id == seeded_web_config.task_id
    assert debug.global_platform_access_events.scope == "global"
    assert "not task-scoped" in debug.global_platform_access_events.warning
    assert debug.global_platform_access_events.events[0].target == "R9000P 4060"


def test_workbench_service_returns_empty_market_for_task_without_runs(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "empty-market.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task_id = create_research_task(
            conn,
            title="No runs",
            goal="No collected candidates",
            city="Shanghai",
        )
        conn.commit()

    market = WorkbenchService(config).get_market(task_id)

    assert market.run_ids == []
    assert market.sample_policy.priced_candidate_count == 0
    assert market.overall.candidate_count == 0
    assert market.overall.price_summary.count == 0
    assert market.spec_price_groups == []
    assert market.geography.locations == []
    assert market.geography.target_city_count == 0
    assert market.geography.target_city_coverage_ratio is None
    assert market.collection_coverage.collection_rounds == 0
    assert market.collection_coverage.detail_coverage_ratio is None
    assert market.search_coverage.runs == []
