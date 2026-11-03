from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from httpx import ASGITransport, AsyncClient
import pytest

from shopping_agent.web.app import create_app
from shopping_agent.web.app import STATIC_DIR


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def web_client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    config_path = tmp_path / "default.toml"
    config_path.write_text(
        f'database_path = "{(tmp_path / "workbench.sqlite").as_posix()}"\n',
        encoding="utf-8",
    )
    app = create_app(config_path, tmp_path / "settings.json")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
    ) as client:
        yield client


async def test_spa_fallback_serves_index_for_task_route(web_client) -> None:
    response = await web_client.get("/tasks/8")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text


async def test_unknown_api_route_stays_json_404(web_client) -> None:
    response = await web_client.get("/api/not-real")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


async def test_javascript_assets_use_browser_module_mime_type(web_client) -> None:
    javascript_asset = next((STATIC_DIR / "assets").glob("*.js"))

    response = await web_client.get(f"/assets/{javascript_asset.name}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")


async def test_static_assets_cannot_escape_package_directory(web_client) -> None:
    response = await web_client.get("/assets/%2e%2e/%2e%2e/app.py")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found"}
    }


async def test_missing_static_asset_returns_json_404_instead_of_spa(web_client) -> None:
    response = await web_client.get("/assets/missing.js")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "not_found"
