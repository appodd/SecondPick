from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from httpx import ASGITransport, AsyncClient
import pytest

from shopping_agent.db import (
    add_listing_snapshot,
    add_saved_report,
    attach_run_to_task,
    connect,
    create_research_task,
    create_search_run,
    initialize,
    upsert_listing,
)
from shopping_agent.setup_status import CodexStatus
from shopping_agent.web.app import create_app
from shopping_agent.web.cli import build_parser, main


pytestmark = pytest.mark.anyio


async def test_product_images_does_not_expose_uncached_source_urls_or_local_paths(web_client):
    with connect(web_client.database_path) as conn:
        before = list(conn.iterdump())
        for source, kind in [
            ("https://images.example.test/one.jpg", "product_image_url"),
            ("https://images.example.test/two.jpg", "product_image_url"),
            ("https://images.example.test/one.jpg", "product_image_url"),
            ("https://user:secret@images.example.test/private.jpg", "product_image_url"),
            ("file:///private/photo.jpg", "product_image_url"),
            ("javascript:alert(1)", "product_image_url"),
            ("https://images.example.test/avatar.jpg", "image_url"),
            (None, "product_image_url"),
        ]:
            conn.execute("INSERT INTO media_assets(listing_id,media_type,source_url,local_path,created_at) VALUES(?,?,?,?,?)",
                         (web_client.listing_id, kind, source, "private/local/path.jpg", "2026-10-22"))
        conn.commit()
        saved = list(conn.iterdump())
    response = await web_client.get(f"/api/tasks/{web_client.task_id}/listings/{web_client.listing_id}/images")
    assert response.status_code == 200
    data = response.json()
    assert data["listing_id"] == web_client.listing_id
    # The current contract exposes prepared local media, never raw source URLs.
    assert data["images"] == []
    assert data["local_count"] == 0
    assert "images.example.test" not in response.text
    assert "private/local" not in response.text and "secret" not in response.text
    with connect(web_client.database_path) as conn:
        assert list(conn.iterdump()) == saved
    assert before != saved  # Only the test fixture inserted data.


async def test_product_images_rejects_out_of_project_and_missing_listings(web_client):
    with connect(web_client.database_path) as conn:
        other_task = create_research_task(conn, title="Other", goal="Other", city="上海")
        other_run = create_search_run(conn, goal="Other", city="上海")
        attach_run_to_task(conn, task_id=other_task, run_id=other_run)
        other_listing = upsert_listing(conn, platform="xianyu", url="https://example.test/other-image")
        add_listing_snapshot(conn, listing_id=other_listing, run_id=other_run, title="Other")
        conn.commit()
    for task, listing in [(web_client.task_id, other_listing), (other_task, web_client.listing_id), (99999, web_client.listing_id), (web_client.task_id, 99999)]:
        response = await web_client.get(f"/api/tasks/{task}/listings/{listing}/images")
        assert response.status_code == 404


async def test_product_images_empty_is_not_an_unavailable_endpoint(web_client):
    response = await web_client.get(f"/api/tasks/{web_client.task_id}/listings/{web_client.listing_id}/images")
    assert response.status_code == 200
    data = response.json()
    assert data["listing_id"] == web_client.listing_id
    assert data["images"] == []
    assert data["local_count"] == 0
    assert data["cover_url"] is None
    assert data["cover_media_id"] is None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def web_client(tmp_path: Path, monkeypatch) -> AsyncIterator[AsyncClient]:
    database_path = tmp_path / "workbench.sqlite"
    reports_dir = tmp_path / "reports"
    config_path = tmp_path / "default.toml"
    config_path.write_text(
        (
            f'default_city = "上海"\n'
            f'database_path = "{database_path.as_posix()}"\n'
            f'reports_dir = "{reports_dir.as_posix()}"\n'
        ),
        encoding="utf-8",
    )
    settings_path = tmp_path / "settings.json"
    initialize(database_path)

    with connect(database_path) as conn:
        task_id = create_research_task(
            conn,
            title="MacBook Air M2",
            goal="Find a MacBook Air M2",
            city="上海",
        )
        run_id = create_search_run(conn, goal="MacBook Air M2", city="上海")
        attach_run_to_task(conn, task_id=task_id, run_id=run_id)
        listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://example.test/macbook-air-m2",
        )
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="MacBook Air M2 16GB",
            description="Clean used laptop",
            price_text="5200",
            location="上海",
            seller_name="Seller A",
        )
        updated_at = conn.execute(
            "SELECT updated_at FROM research_tasks WHERE id = ?", (task_id,)
        ).fetchone()["updated_at"]
        conn.commit()

    monkeypatch.setattr(
        "shopping_agent.setup_status.check_codex_availability",
        lambda: CodexStatus(
            cli_available=True,
            auth_available=True,
            detail="authenticated",
        ),
    )
    app = create_app(config_path, settings_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
    ) as client:
        client.app = app
        client.task_id = task_id
        client.listing_id = listing_id
        client.updated_at = updated_at
        client.settings_path = settings_path
        client.database_path = database_path
        client.reports_dir = reports_dir
        yield client


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({"host": "attacker.example"}, "invalid_host"),
        (
            {"host": "127.0.0.1", "origin": "https://attacker.example"},
            "invalid_origin",
        ),
    ],
)
async def test_rejects_non_loopback_host_and_origin(
    web_client,
    headers: dict[str, str],
    code: str,
) -> None:
    response = await web_client.get("/api/tasks", headers=headers)

    assert response.status_code in {400, 403}
    assert response.json()["error"]["code"] == code


async def test_rejects_cross_origin_settings_patch(web_client) -> None:
    response = await web_client.patch(
        "/api/settings",
        headers={"origin": "https://attacker.example"},
        json={"default_city": "杭州"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_origin"
    assert not web_client.settings_path.exists()


@pytest.mark.parametrize("origin", ["http://127.0.0.1:9999", "http://localhost", "https://127.0.0.1"])
async def test_rejects_other_local_origin_without_mutation(web_client, origin):
    response = await web_client.patch("/api/settings", headers={"origin": origin}, json={"default_city": "杭州"})
    assert response.status_code == 403
    assert not web_client.settings_path.exists()


async def test_accepts_same_origin_and_rejects_cross_site_actions(web_client):
    assert (await web_client.get("/api/tasks", headers={"origin": "http://127.0.0.1"})).status_code == 200
    response = await web_client.patch("/api/settings", headers={"sec-fetch-site": "cross-site"}, json={"default_city": "杭州"})
    assert response.status_code == 403 and not web_client.settings_path.exists()


async def test_get_tasks_returns_stable_envelope(web_client) -> None:
    response = await web_client.get("/api/tasks")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": web_client.task_id,
                "title": "MacBook Air M2",
                "city": "上海",
                "status": "active",
                "run_count": 1,
                "report_count": 0,
                "updated_at": web_client.updated_at,
                "operation_state": None,
            }
        ],
        "total_count": 1,
        "returned_count": 1,
        "truncated": False,
        "page": {
            "offset": 0,
            "limit": 50,
            "has_more": False,
            "next_offset": None,
        },
    }


async def test_api_maps_missing_task_and_bad_cursor(web_client) -> None:
    missing = await web_client.get("/api/tasks/99999")
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {
            "code": "not_found",
            "message": "Research task not found: 99999",
        }
    }

    response = await web_client.get(
        f"/api/tasks/{web_client.task_id}/candidates",
        params={"limit": 20, "cursor": "broken"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


async def test_read_only_task_routes_return_service_dtos(web_client) -> None:
    task = await web_client.get(f"/api/tasks/{web_client.task_id}")
    candidates = await web_client.get(f"/api/tasks/{web_client.task_id}/candidates")
    market = await web_client.get(f"/api/tasks/{web_client.task_id}/market")
    debug = await web_client.get(f"/api/tasks/{web_client.task_id}/debug")
    evidence = await web_client.get(
        f"/api/listings/{web_client.listing_id}/evidence",
        params={"task_id": web_client.task_id},
    )

    assert task.status_code == 200
    assert task.json()["task"]["id"] == web_client.task_id
    assert candidates.status_code == 200
    assert candidates.json()["deduplicated_count"] == 1
    assert market.status_code == 200
    assert market.json()["run_ids"]
    assert debug.status_code == 200
    assert debug.json()["global_platform_access_events"]["scope"] == "global"
    assert evidence.status_code == 200
    assert evidence.json()["listing_id"] == web_client.listing_id


async def test_setup_and_health_routes_are_browser_free(web_client) -> None:
    health = await web_client.get("/api/health")
    status = await web_client.get("/api/setup/status")
    environment = await web_client.post("/api/setup/check-environment")
    codex = await web_client.post("/api/setup/" "check-codex")

    assert health.json() == {"status": "ok"}
    assert status.status_code == 200
    assert status.json()["can_browse_existing_data"] is True
    assert [check["name"] for check in environment.json()] == ["config", "database"]
    assert codex.status_code == 200
    assert codex.json()["auth_available"] is True


async def test_settings_patch_merges_non_none_fields_and_persists(web_client) -> None:
    original = await web_client.get("/api/settings")
    patched = await web_client.patch(
        "/api/settings",
        json={"setup_completed": True, "default_city": "杭州", "allow_ocr": None},
    )

    assert original.json()["allow_ocr"] is True
    assert patched.status_code == 200
    assert patched.json() == {
        "setup_completed": True,
        "setup_mode": "basic",
        "default_city": "杭州",
        "platforms": ["xianyu"],
        "allow_ocr": True,
        "preferred_view": "research",
    }
    saved = await web_client.get("/api/settings")
    assert saved.json() == patched.json()
    assert web_client.settings_path.exists()


@pytest.mark.parametrize("mode", ["basic", "ai"])
async def test_setup_completion_mode_is_persisted_without_creating_projects(web_client, mode) -> None:
    before = (await web_client.get("/api/tasks")).json()
    response = await web_client.patch(
        "/api/settings", json={"setup_completed": True, "setup_mode": mode}
    )
    assert response.status_code == 200
    assert response.json()["setup_mode"] == mode
    assert (await web_client.get("/api/settings")).json() == response.json()
    from shopping_agent.user_settings import load_user_settings
    assert load_user_settings(web_client.settings_path).setup_mode == mode
    assert (await web_client.get("/api/tasks")).json() == before


async def test_setup_mode_rejects_unknown_values(web_client) -> None:
    response = await web_client.patch("/api/settings", json={"setup_mode": "automatic"})
    assert response.status_code == 422
    assert not web_client.settings_path.exists()


async def test_settings_patch_preserves_explicit_null_default_city(web_client) -> None:
    await web_client.patch("/api/settings", json={"default_city": "杭州"})

    cleared = await web_client.patch("/api/settings", json={"default_city": None})

    assert cleared.status_code == 200
    assert cleared.json()["default_city"] is None
    assert (await web_client.get("/api/settings")).json()["default_city"] is None


async def test_settings_patch_rejects_extra_fields(web_client) -> None:
    response = await web_client.patch(
        "/api/settings", json={"database_path": "outside.sqlite"}
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "Request validation failed.",
        }
    }
    assert not web_client.settings_path.exists()


async def test_invalid_candidate_limit_returns_validation_envelope(web_client) -> None:
    response = await web_client.get(
        f"/api/tasks/{web_client.task_id}/candidates",
        params={"limit": 101},
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "Request validation failed.",
        }
    }


async def test_unknown_api_route_returns_not_found_envelope(web_client) -> None:
    response = await web_client.get("/api/unknown")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found"}
    }


async def test_prohibited_post_returns_method_not_allowed_envelope(web_client) -> None:
    response = await web_client.post("/api/health")

    assert response.status_code == 405
    assert response.json() == {
        "error": {
            "code": "method_not_allowed",
            "message": "Method Not Allowed",
        }
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/tasks/1/collect"),
    ],
)
async def test_collection_routes_remain_unavailable(
    web_client, method: str, path: str
) -> None:
    documented_path = path.replace("/1/", "/{task_id}/")

    assert method not in web_client.app.openapi()["paths"].get(documented_path, {})


async def test_task_list_exposes_total_and_explicit_pagination(web_client) -> None:
    with connect(web_client.database_path) as conn:
        for index in range(104):
            create_research_task(
                conn,
                title=f"History {index}",
                goal=f"Goal {index}",
                city="上海",
            )
        conn.commit()

    first = await web_client.get("/api/tasks", params={"limit": 100, "offset": 0})
    second = await web_client.get("/api/tasks", params={"limit": 100, "offset": 100})

    assert first.status_code == 200
    assert first.json()["total_count"] == 105
    assert first.json()["returned_count"] == 100
    assert first.json()["truncated"] is True
    assert first.json()["page"] == {
        "offset": 0,
        "limit": 100,
        "has_more": True,
        "next_offset": 100,
    }
    assert second.status_code == 200
    assert second.json()["total_count"] == 105
    assert second.json()["returned_count"] == 5
    assert second.json()["truncated"] is False
    assert second.json()["page"]["next_offset"] is None
    assert {
        item["id"] for item in first.json()["items"]
    }.isdisjoint(item["id"] for item in second.json()["items"])


async def test_report_endpoint_is_task_scoped_and_confined_to_reports_dir(
    web_client,
    tmp_path: Path,
) -> None:
    web_client.reports_dir.mkdir()
    report_path = web_client.reports_dir / "task-report.md"
    report_path.write_text("# Scoped report", encoding="utf-8")
    outside_path = tmp_path / "outside-report.md"
    outside_path.write_text("private", encoding="utf-8")
    with connect(web_client.database_path) as conn:
        report_id = add_saved_report(
            conn,
            task_id=web_client.task_id,
            path=report_path,
            title="Scoped report",
            report_format="markdown",
        )
        outside_report_id = add_saved_report(
            conn,
            task_id=web_client.task_id,
            path=outside_path,
            title="Outside report",
            report_format="markdown",
        )
        other_task_id = create_research_task(
            conn,
            title="Other task",
            goal="Other goal",
            city="上海",
        )
        conn.commit()

    task_response = await web_client.get(f"/api/tasks/{web_client.task_id}")
    report_response = await web_client.get(
        f"/api/tasks/{web_client.task_id}/reports/{report_id}"
    )
    wrong_task_response = await web_client.get(
        f"/api/tasks/{other_task_id}/reports/{report_id}"
    )
    outside_response = await web_client.get(
        f"/api/tasks/{web_client.task_id}/reports/{outside_report_id}"
    )

    assert all("path" not in report for report in task_response.json()["reports"])
    assert report_response.status_code == 200
    assert report_response.text == "# Scoped report"
    assert report_response.headers["content-disposition"].startswith("attachment;")
    assert wrong_task_response.status_code == 404
    assert outside_response.status_code == 404


def test_launcher_rejects_non_loopback_host() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--host", "0.0.0.0"])

    assert exc_info.value.code == 2


def test_launcher_defaults_to_loopback_reserved_port() -> None:
    args = build_parser().parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8765
