from __future__ import annotations

from pathlib import Path

from PIL import Image

from shopping_agent.analysis import analyze_downloaded_images
from shopping_agent.cli import build_parser
from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_listing_snapshot,
    add_media_asset,
    connect,
    create_search_run,
    initialize,
    upsert_listing,
)
from shopping_agent.media import download_pending_media


def test_media_commands_accept_listing_id_target() -> None:
    parser = build_parser()

    download_args = parser.parse_args(["download-media", "--listing-id", "42", "--limit", "2"])
    analyze_args = parser.parse_args(["analyze-images", "--listing-id", "42", "--limit", "2"])

    assert download_args.listing_id == 42
    assert analyze_args.listing_id == 42


def test_download_pending_media_targets_single_listing(tmp_path: Path, monkeypatch) -> None:
    config, listing_ids = _media_fixture(tmp_path, downloaded=False)

    def fake_download(_source_url: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(b"image")

    monkeypatch.setattr("shopping_agent.media._download", fake_download)

    results = download_pending_media(config, listing_id=listing_ids[1], limit=10)

    assert len(results) == 1
    assert f"listing-{listing_ids[1]}" in str(results[0].local_path)


def test_analyze_downloaded_images_targets_single_listing(tmp_path: Path) -> None:
    config, listing_ids = _media_fixture(tmp_path, downloaded=True)

    records = analyze_downloaded_images(
        config,
        listing_id=listing_ids[1],
        limit=10,
        backend="unsupported",
    )

    assert len(records) == 1
    assert f"listing-{listing_ids[1]}" in str(records[0].local_path)


def _media_fixture(tmp_path: Path, *, downloaded: bool) -> tuple[AppConfig, list[int]]:
    config = AppConfig(database_path=tmp_path / "shopping.sqlite", media_dir=tmp_path / "media")
    initialize(config.database_path)
    listing_ids = []
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="media selection", city="Shanghai")
        for index in range(2):
            listing_id = upsert_listing(
                conn,
                platform="xianyu",
                url=f"https://www.goofish.com/item?id={index}",
            )
            add_listing_snapshot(conn, listing_id=listing_id, run_id=run_id, title=f"listing {index}")
            local_path = ""
            if downloaded:
                image_path = config.media_dir / f"listing-{listing_id}" / "image.png"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (10, 10), color="white").save(image_path)
                local_path = str(image_path)
            add_media_asset(
                conn,
                listing_id=listing_id,
                media_type="product_image_url",
                source_url=f"https://example.test/{index}.png",
                local_path=local_path,
            )
            listing_ids.append(listing_id)
    return config, listing_ids
